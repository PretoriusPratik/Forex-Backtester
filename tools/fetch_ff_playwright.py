# file: tools/fetch_ff_playwright.py
"""
ForexFactory weekly export via a real browser (Playwright).
- Opens each week page, clicks Weekly Export → JSON (fallback CSV)
- Parses and normalizes to UTC
- Appends to one CSV in backtester format: ts,currency,impact,event

Setup:
  pip install playwright pandas beautifulsoup4 python-dateutil pytz
  playwright install chromium

Run (one year at a time is recommended):
  python tools/fetch_ff_playwright.py \
    --out ./data/news_ff_UTC.csv \
    --start 2020-01-01 --end 2020-12-31 \
    --min-impact low \
    --headless true \
    --sleep 5.0 \
    --profile-dir ./secrets/ff_profile \
    --append

If login needed:
  - First run with --headless false (opens a window), log in once.
  - The session cookies persist in --profile-dir for future runs.
"""

from __future__ import annotations
import argparse, json, time, tempfile
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
    # Some FF JSON uses icons/text — default to low
    return "low"

def _parse_json_bytes(b: bytes) -> pd.DataFrame:
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
                    ts = pd.Timestamp(dtp.parse(str(t_raw))).tz_localize("UTC")
                except Exception:
                    ts = None
        cur = (ev.get("currency") or ev.get("country") or "").upper()
        imp = str(ev.get("impact") or ev.get("impactDescription") or ev.get("importance") or "").lower()
        title = str(ev.get("title") or ev.get("event") or "").strip()
        if ts is not None and cur and title:
            rows.append({"ts": ts, "currency": cur, "impact": _norm_impact(imp), "event": title})
    return pd.DataFrame(rows)

def _parse_csv_bytes(b: bytes) -> pd.DataFrame:
    from io import StringIO
    txt = b.decode("utf-8", errors="ignore")
    if not txt.strip(): return pd.DataFrame(columns=["ts","currency","impact","event"])
    cdf = pd.read_csv(StringIO(txt))
    cols = {c.lower(): c for c in cdf.columns}
    def pick(*names): 
        for n in names:
            if n in cols: return cols[n]
        return None
    dcol = pick("date")
    tcol = pick("time","time (utc)")
    ccol = pick("currency","country")
    icol = pick("impact","importance")
    ecol = pick("event","title")
    if not all([dcol, tcol, ccol, icol, ecol]):
        return pd.DataFrame(columns=["ts","currency","impact","event"])
    ts = pd.to_datetime((cdf[dcol].astype(str)+" "+cdf[tcol].astype(str)), errors="coerce", utc=True)
    df = pd.DataFrame({
        "ts": ts,
        "currency": cdf[ccol].astype(str).str.upper(),
        "impact": cdf[icol].astype(str).str.lower().map(_norm_impact),
        "event": cdf[ecol].astype(str).str.strip(),
    }).dropna(subset=["ts"])
    return df

def _append_save(out_path: Path, df_new: pd.DataFrame) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        cur = pd.read_csv(out_path, parse_dates=["ts"])
        merged = (pd.concat([cur, df_new], ignore_index=True)
                    .drop_duplicates()
                    .sort_values("ts"))
        merged.to_csv(out_path, index=False)
    else:
        df_new.sort_values("ts").to_csv(out_path, index=False)

# ---------- core ----------

def _download_week_export(page, prefer_json: bool=True) -> Optional[bytes]:
    # Wait for Weekly Export block then attempt JSON or CSV link clicks
    page.wait_for_selector("text=Weekly Export", timeout=15000)
    link_json = page.locator("a:has-text('JSON')")
    link_csv  = page.locator("a:has-text('CSV')")
    # Try JSON first
    if prefer_json and link_json.count():
        try:
            with page.expect_download(timeout=15000) as dl_info:
                link_json.first.click(button="left", force=True)
            dl: Download = dl_info.value
            return dl.read()
        except PWTimeout:
            pass
        except Exception:
            pass
    # Fallback to CSV
    if link_csv.count():
        try:
            with page.expect_download(timeout=15000) as dl_info:
                link_csv.first.click(button="left", force=True)
            dl: Download = dl_info.value
            return dl.read()
        except Exception:
            return None
    return None

def fetch_ff_range_playwright(out_csv: Path, start: str, end: str, min_impact: str,
                              headless: bool, sleep_sec: float, profile_dir: Path, append: bool) -> None:
    weeks = _weeks_between(start, end)
    if not weeks:
        raise SystemExit("No weeks in range.")
    rank = {"low":0,"medium":1,"high":2}
    thr = rank[min_impact]

    profile_dir.mkdir(parents=True, exist_ok=True)

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
        page.set_default_timeout(20000)

        buf = []  # used if not append

        try:
            for i, wk in enumerate(weeks, 1):
                week_qs = wk.strftime("%Y-%m-%d")
                url = f"https://www.forexfactory.com/calendar?week={week_qs}"
                print(f"[{i}/{len(weeks)}] {url}")
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    # if not logged in and FF blocks, you can log in manually (when headless=false), then re-run headless
                    b = _download_week_export(page, prefer_json=True)
                except Exception as e:
                    print(f"  navigation/export error: {e}")
                    b = None

                if not b:
                    print("  (no download; skipping)"); time.sleep(sleep_sec); continue

                # detect format by peeking
                text_snippet = b[:64].decode("utf-8", errors="ignore").lstrip()
                if text_snippet.startswith("{") or text_snippet.startswith("["):
                    df = _parse_json_bytes(b)
                else:
                    df = _parse_csv_bytes(b)

                if df.empty:
                    print("  (parsed 0 rows)"); time.sleep(sleep_sec); continue

                # week filter (UTC)
                start_utc, end_utc = _week_bounds_utc(wk)
                df = df[(df["ts"] >= start_utc) & (df["ts"] <= end_utc)]
                print(f"  rows after week-filter: {len(df)}")
                if df.empty:
                    time.sleep(sleep_sec); continue

                # min-impact and normalization
                df["impact"] = df["impact"].map(lambda x: _norm_impact(str(x)))
                df = df[df["impact"].map(rank).fillna(0) >= thr]
                df = df[["ts","currency","impact","event"]]
                if df.empty:
                    print("  (rows dropped by min-impact filter)"); time.sleep(sleep_sec); continue

                if append:
                    _append_save(out_csv, df)
                    print(f"  appended {len(df)} rows → {out_csv}")
                else:
                    buf.append(df)

                time.sleep(sleep_sec)
        finally:
            context.close()

    if not append:
        if not buf:
            raise SystemExit("No data fetched.")
        out = (pd.concat(buf, ignore_index=True)
                 .drop_duplicates()
                 .sort_values("ts"))
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(out_csv, index=False)
        print(f"✓ wrote {out_csv} rows={len(out)} range={out['ts'].min()} → {out['ts'].max()}")
    else:
        print(f"✓ append mode complete → {out_csv}")

def main():
    ap = argparse.ArgumentParser(description="ForexFactory weekly export via Playwright (browser).")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--start", type=str, required=True)
    ap.add_argument("--end", type=str, required=True)
    ap.add_argument("--min-impact", type=str, choices=["low","medium","high"], default="low")
    ap.add_argument("--headless", type=str, default="true", help="true|false")
    ap.add_argument("--sleep", type=float, default=5.0)
    ap.add_argument("--profile-dir", type=Path, default=Path("./secrets/ff_profile"))
    ap.add_argument("--append", action="store_true")
    args = ap.parse_args()
    headless = str(args.headless).lower() in {"true","1","yes","y"}
    fetch_ff_range_playwright(args.out, args.start, args.end, args.min_impact, headless, args.sleep, args.profile_dir, args.append)

if __name__ == "__main__":
    main()
