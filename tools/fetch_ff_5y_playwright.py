# file: tools/fetch_ff_5y_playwright.py
"""
ForexFactory weekly export via Playwright (browser automation), robust & slow:
- Opens each week page, clicks "Weekly Export" → JSON (fallback CSV)
- Parses with a chosen calendar timezone (default Asia/Kolkata), converts to UTC
- Validates rows belong to that week, filters by impact, and appends to a master CSV
- Optional per-week raw caching for auditing/re-runs

Setup (once):
  pip install playwright pandas beautifulsoup4 python-dateutil pytz
  playwright install chromium

Example (fetch 5y in yearly chunks, append):
  python tools/fetch_ff_5y_playwright.py \
    --out ./data/news_ff_UTC.csv \
    --start 2020-01-01 --end 2020-12-31 \
    --calendar-tz Asia/Kolkata \
    --min-impact low \
    --headless false \
    --sleep 5.0 \
    --profile-dir ./secrets/ff_profile \
    --cache-dir ./data/news_raw \
    --append

Then repeat per year (2021..today) with --append, you may switch --headless true after first login.
"""

from __future__ import annotations
import argparse, json, time, os
from pathlib import Path
from typing import List, Optional, Tuple
import pandas as pd
from dateutil import parser as dtp
from playwright.sync_api import sync_playwright, BrowserContext, Download, TimeoutError as PWTimeout

# ---------- helpers ----------

def _weeks_between(start: str, end: str) -> List[pd.Timestamp]:
    s = pd.Timestamp(start).normalize()
    e = pd.Timestamp(end).normalize()
    s_mon = (s - pd.Timedelta(days=s.weekday())).normalize()
    e_mon = (e - pd.Timedelta(days=e.weekday())).normalize()
    out, cur = [], s_mon
    while cur <= e_mon:
        out.append(pd.Timestamp(cur))
        cur += pd.Timedelta(days=7)
    return out

def _week_bounds_utc(week_monday: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = week_monday.tz_localize("UTC")
    end   = (week_monday + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)).tz_localize("UTC")
    return start, end

def _norm_impact(s: str) -> str:
    s = (s or "").lower()
    if "high" in s: return "high"
    if "med" in s: return "medium"
    if "low" in s: return "low"
    # default
    return "low"

def _parse_json_bytes(b: bytes, calendar_tz: str) -> pd.DataFrame:
    """
    Parse FF weekly JSON. If 'timestamp' exists, treat as UTC (seconds or ms).
    Else parse 'datetime'/'date'/'time' in calendar_tz, then convert to UTC.
    """
    js = json.loads(b.decode("utf-8", errors="ignore"))
    rows = []
    for ev in js:
        ts = None
        tsv = ev.get("timestamp")
        if tsv is not None:
            tsv = int(tsv)
            ts = pd.to_datetime(tsv, unit="ms" if tsv > 10_000_000_000 else "s", utc=True)
        else:
            t_raw = ev.get("datetime") or ev.get("date") or ev.get("time")
            if t_raw:
                try:
                    dt_naive = dtp.parse(str(t_raw))
                    ts = pd.Timestamp(dt_naive).tz_localize(calendar_tz).tz_convert("UTC")
                except Exception:
                    ts = None
        cur = (ev.get("currency") or ev.get("country") or "").upper()
        imp = str(ev.get("impact") or ev.get("impactDescription") or ev.get("importance") or "").lower()
        title = str(ev.get("title") or ev.get("event") or "").strip()
        if ts is not None and cur and title:
            rows.append({"ts": ts, "currency": cur, "impact": _norm_impact(imp), "event": title})
    return pd.DataFrame(rows, columns=["ts","currency","impact","event"])

def _parse_csv_bytes(b: bytes, calendar_tz: str) -> pd.DataFrame:
    """
    Parse FF weekly CSV. Build naive timestamps from Date+Time in calendar_tz, then convert to UTC.
    """
    from io import StringIO
    txt = b.decode("utf-8", errors="ignore")
    if not txt.strip(): 
        return pd.DataFrame(columns=["ts","currency","impact","event"])
    cdf = pd.read_csv(StringIO(txt))
    cols = {c.lower(): c for c in cdf.columns}
    def pick(*names): 
        for n in names:
            if n in cols: return cols[n]
        return None
    dcol = pick("date")
    tcol = pick("time","time (utc)")     # sometimes explicitly UTC; we still localize to calendar_tz, then convert
    ccol = pick("currency","country")
    icol = pick("impact","importance")
    ecol = pick("event","title")
    if not all([dcol, tcol, ccol, icol, ecol]):
        return pd.DataFrame(columns=["ts","currency","impact","event"])
    # Build local naive -> localize calendar_tz -> convert to UTC
    ts_local = (cdf[dcol].astype(str).str.strip() + " " + cdf[tcol].astype(str).str.strip())
    ts = pd.to_datetime(ts_local, errors="coerce")
    df = pd.DataFrame({
        "ts": ts,
        "currency": cdf[ccol].astype(str).str.upper(),
        "impact": cdf[icol].astype(str).str.lower().map(_norm_impact),
        "event": cdf[ecol].astype(str).str.strip(),
    }).dropna(subset=["ts"])
    # time zone normalization
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(calendar_tz, nonexistent="NaT", ambiguous="NaT").dt.tz_convert("UTC")
    df = df.dropna(subset=["ts"])
    return df[["ts","currency","impact","event"]]

def _append_save(out_path: Path, df_new: pd.DataFrame) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and out_path.stat().st_size > 0:
        cur = pd.read_csv(out_path, parse_dates=["ts"])
        merged = (pd.concat([cur, df_new], ignore_index=True)
                    .drop_duplicates()
                    .sort_values("ts"))
        merged.to_csv(out_path, index=False)
    else:
        df_new.sort_values("ts").to_csv(out_path, index=False)

def _download_week_export(page, prefer_json: bool=True) -> Optional[Tuple[bytes, str]]:
    """
    Click Weekly Export JSON (fallback CSV). Return (bytes, "json"/"csv") or None.
    """
    page.wait_for_selector("text=Weekly Export", timeout=20000)
    link_json = page.locator("a:has-text('JSON')")
    link_csv  = page.locator("a:has-text('CSV')")
    if prefer_json and link_json.count():
        try:
            with page.expect_download(timeout=20000) as dl_info:
                link_json.first.click(button="left", force=True)
            dl: Download = dl_info.value
            return dl.read(), "json"
        except Exception:
            pass
    if link_csv.count():
        try:
            with page.expect_download(timeout=20000) as dl_info:
                link_csv.first.click(button="left", force=True)
            dl: Download = dl_info.value
            return dl.read(), "csv"
        except Exception:
            return None
    return None

def _save_raw(cache_dir: Optional[Path], week: str, kind: str, payload: bytes) -> None:
    if not cache_dir: 
        return
    (cache_dir / "weeks").mkdir(parents=True, exist_ok=True)
    ext = ".json" if kind == "json" else ".csv"
    fp = cache_dir / "weeks" / f"{week}{ext}"
    fp.write_bytes(payload)

def _skip_if_already_present(out_csv: Path, week_monday: pd.Timestamp) -> bool:
    """
    Fast skip: if out_csv exists and already has rows inside this week's UTC bounds, skip download.
    """
    if not out_csv.exists() or out_csv.stat().st_size == 0:
        return False
    try:
        df = pd.read_csv(out_csv, parse_dates=["ts"], usecols=["ts"])
    except Exception:
        return False
    st, en = _week_bounds_utc(week_monday)
    return ((df["ts"] >= st) & (df["ts"] <= en)).any()

# ---------- core ----------

def fetch_ff_range_playwright(
    out_csv: Path,
    start: str,
    end: str,
    calendar_tz: str,
    min_impact: str,
    headless: bool,
    sleep_sec: float,
    profile_dir: Path,
    cache_dir: Optional[Path],
    append: bool,
    skip_existing: bool
) -> None:
    weeks = _weeks_between(start, end)
    if not weeks:
        raise SystemExit("No weeks in range.")
    rank = {"low":0,"medium":1,"high":2}
    thr = rank[min_impact]

    profile_dir.mkdir(parents=True, exist_ok=True)
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context: BrowserContext = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            locale="en-US"
        )
        page = context.new_page()
        page.set_default_timeout(25000)

        pending = []  # only used if not append
        try:
            for i, wk in enumerate(weeks, 1):
                week_qs = wk.strftime("%Y-%m-%d")
                url = f"https://www.forexfactory.com/calendar?week={week_qs}"
                print(f"[{i}/{len(weeks)}] {url}")

                if skip_existing and _skip_if_already_present(out_csv, wk):
                    print("  already present in OUT; skipping")
                    time.sleep(0.5)
                    continue

                # navigate and download
                try:
                    page.goto(url, wait_until="domcontentloaded")
                except Exception as e:
                    print(f"  nav error: {e}; retrying once...")
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                    except Exception as e2:
                        print(f"  nav failed again: {e2}; skipping")
                        time.sleep(sleep_sec)
                        continue

                got = _download_week_export(page, prefer_json=True)
                if not got:
                    print("  (no download; skipping)")
                    time.sleep(sleep_sec)
                    continue
                payload, kind = got
                _save_raw(cache_dir, week_qs, kind, payload)

                # parse
                if kind == "json":
                    df = _parse_json_bytes(payload, calendar_tz)
                else:
                    df = _parse_csv_bytes(payload, calendar_tz)
                if df.empty:
                    print("  parsed 0 rows")
                    time.sleep(sleep_sec)
                    continue

                # filter by week (UTC)
                st, en = _week_bounds_utc(wk)
                df = df[(df["ts"] >= st) & (df["ts"] <= en)]
                print(f"  rows after week-filter: {len(df)}")
                if df.empty:
                    time.sleep(sleep_sec)
                    continue

                # min-impact filter + normalization
                df["impact"] = df["impact"].map(lambda x: _norm_impact(str(x)))
                df = df[df["impact"].map(rank).fillna(0) >= thr]
                df = df[["ts","currency","impact","event"]]
                if df.empty:
                    print("  rows dropped by min-impact filter")
                    time.sleep(sleep_sec)
                    continue

                if append:
                    _append_save(out_csv, df)
                    print(f"  appended {len(df)} rows → {out_csv}")
                else:
                    pending.append(df)

                time.sleep(sleep_sec)
        finally:
            context.close()

    if not append:
        if not pending:
            raise SystemExit("No data fetched.")
        out = (pd.concat(pending, ignore_index=True)
                 .drop_duplicates()
                 .sort_values("ts"))
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(out_csv, index=False)
        print(f"✓ wrote {out_csv} rows={len(out)} range={out['ts'].min()} → {out['ts'].max()}")
    else:
        print(f"✓ append mode complete → {out_csv}")

def main():
    ap = argparse.ArgumentParser(description="ForexFactory weekly export → UTC CSV via Playwright.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--start", type=str, required=True)
    ap.add_argument("--end", type=str, required=True)
    ap.add_argument("--calendar-tz", type=str, default="Asia/Kolkata", help="Your FF calendar display timezone.")
    ap.add_argument("--min-impact", type=str, choices=["low","medium","high"], default="low")
    ap.add_argument("--headless", type=str, default="true", help="true|false")
    ap.add_argument("--sleep", type=float, default=5.0)
    ap.add_argument("--profile-dir", type=Path, default=Path("./secrets/ff_profile"))
    ap.add_argument("--cache-dir", type=Path, default=None)
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--skip-existing", action="store_true", help="Skip weeks already present in OUT.")
    args = ap.parse_args()
    headless = str(args.headless).lower() in {"true","1","yes","y"}

    fetch_ff_range_playwright(
        out_csv=args.out,
        start=args.start,
        end=args.end,
        calendar_tz=args.calendar_tz,
        min_impact=args.min_impact,
        headless=headless,
        sleep_sec=args.sleep,
        profile_dir=args.profile_dir,
        cache_dir=args.cache_dir,
        append=args.append,
        skip_existing=args.skip_existing,
    )

if __name__ == "__main__":
    main()
