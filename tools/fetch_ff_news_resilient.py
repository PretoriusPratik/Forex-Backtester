# file: tools/fetch_ff_news_resilient.py
"""
Robust ForexFactory weekly export fetcher with 429 handling, host fallback, week validation,
resume/append, and incremental saving.

Usage:
  pip install requests pandas python-dateutil pytz

  python tools/fetch_ff_news_resilient.py \
    --out ./data/news_ff_UTC.csv \
    --start 2020-01-01 --end today \
    --min-impact low \
    --sleep 6.0 --append

Tips:
- Start with a small range first (e.g., 6 months) to confirm.
- For very long ranges, run multiple passes (year by year).
"""

from __future__ import annotations
import argparse, time, random
from pathlib import Path
from typing import List, Optional, Dict
import pandas as pd
import requests
from dateutil import parser as dtp
from requests import RequestException

# JSON_ENDPOINTS = [
#     "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
#     "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json",
# ]
# CSV_ENDPOINTS = [
#     "https://nfs.faireconomy.media/ff_calendar_thisweek.csv",
#     "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.csv",
# ]
JSON_ENDPOINTS = ["https://nfs.faireconomy.media/ff_calendar_thisweek.json"]
CSV_ENDPOINTS  = ["https://nfs.faireconomy.media/ff_calendar_thisweek.csv"]


def _weeks_between(start: str, end: Optional[str]) -> List[pd.Timestamp]:
    end_ts = (pd.Timestamp.utcnow().normalize()
              if (end is None or str(end).lower()=="today") else pd.Timestamp(end))
    st_ts = pd.Timestamp(start)
    st_mon = (st_ts - pd.Timedelta(days=st_ts.weekday())).normalize()
    en_mon = (end_ts - pd.Timedelta(days=end_ts.weekday())).normalize()
    out, cur = [], st_mon
    while cur <= en_mon:
        out.append(pd.Timestamp(cur))  # tz-naive, midnight
        cur += pd.Timedelta(days=7)
    return out

def _build_session(timeout: int = 25, cookie_str: Optional[str] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/csv, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    })
    if cookie_str:
        s.headers["Cookie"] = cookie_str
    # attach default timeout
    old = s.request
    def req(method, url, **kw):
        kw.setdefault("timeout", timeout)
        return old(method, url, **kw)
    s.request = req  # type: ignore
    return s

def _norm_impact(s: str) -> str:
    s = (s or "").lower()
    if "high" in s: return "high"
    if "med"  in s: return "medium"
    if "low"  in s: return "low"
    return "low"

def _rate_limit_sleep(resp: requests.Response, base_sleep: float, attempt: int):
    # Honor Retry-After if present; else exp backoff + jitter
    ra = resp.headers.get("Retry-After")
    if ra and ra.isdigit():
        wait = max(base_sleep, float(ra))
    else:
        wait = base_sleep * (2 ** attempt)
    wait += random.uniform(0.5, 1.5)  # jitter
    time.sleep(wait)

def _week_bounds_utc(week_monday: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(week_monday).tz_localize("UTC")
    end = (pd.Timestamp(week_monday) + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)).tz_localize("UTC")
    return start, end

def _filter_to_week(df: pd.DataFrame, week_monday: pd.Timestamp) -> pd.DataFrame:
    if df.empty: return df
    ts = pd.to_datetime(df["ts"], utc=True)
    df = df.copy()
    df["ts"] = ts
    start, end = _week_bounds_utc(week_monday)
    return df[(df["ts"] >= start) & (df["ts"] <= end)]

# def _fetch_json(sess: requests.Session, url: str, week: str, headers: Dict[str,str], base_sleep: float) -> Optional[pd.DataFrame]:
#     for attempt in range(4):
#         r = sess.get(url, params={"week": week}, headers=headers)
#         print(f"  GET {url} ?week={week} -> {r.status_code}, len={len(r.content)}")
#         if r.status_code == 429:
#             _rate_limit_sleep(r, base_sleep, attempt); continue
#         r.raise_for_status()
#         try:
#             js = r.json()
#         except Exception:
#             return None
#         rows = []
#         for ev in js:
#             ts_val = ev.get("timestamp")
#             ts = None
#             if ts_val is not None:
#                 ts = int(ts_val)
#                 ts = pd.to_datetime(ts, unit="ms" if ts > 10_000_000_000 else "s", utc=True)
#             else:
#                 t_raw = ev.get("datetime") or ev.get("date") or ev.get("time")
#                 if t_raw:
#                     try:
#                         ts = pd.Timestamp(dtp.parse(str(t_raw))).tz_localize("UTC")
#                     except Exception:
#                         ts = None
#             cur = (ev.get("currency") or ev.get("country") or "").upper()
#             imp = str(ev.get("impact") or ev.get("impactDescription") or ev.get("importance") or "").lower()
#             title = str(ev.get("title") or ev.get("event") or "").strip()
#             if ts is not None and cur and title:
#                 rows.append({"ts": ts, "currency": cur, "impact": imp, "event": title})
#         return pd.DataFrame(rows) if rows else pd.DataFrame()
#     return None

def _fetch_json(sess: requests.Session, url: str, week: str, headers: Dict[str,str], base_sleep: float) -> Optional[pd.DataFrame]:
    for attempt in range(4):
        try:
            r = sess.get(url, params={"week": week}, headers=headers)
            print(f"  GET {url} ?week={week} -> {r.status_code}, len={len(r.content)}")
        except RequestException as e:
            print(f"    JSON connect error: {e} (skipping host)")
            return None  # this host is unreachable; try next host
        if r.status_code == 429:
            _rate_limit_sleep(r, base_sleep, attempt); continue
        try:
            r.raise_for_status()
        except RequestException as e:
            print(f"    JSON HTTP error: {e}")
            return None
        try:
            js = r.json()
        except Exception as e:
            print(f"    JSON parse error: {e}")
            return pd.DataFrame()
        rows = []
        for ev in js:
            ts_val = ev.get("timestamp")
            ts = None
            if ts_val is not None:
                ts = int(ts_val)
                ts = pd.to_datetime(ts, unit="ms" if ts > 10_000_000_000 else "s", utc=True)
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
                rows.append({"ts": ts, "currency": cur, "impact": imp, "event": title})
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    return None


# def _fetch_csv(sess: requests.Session, url: str, week: str, headers: Dict[str,str], base_sleep: float) -> Optional[pd.DataFrame]:
#     from io import StringIO
#     for attempt in range(4):
#         r = sess.get(url, params={"week": week}, headers=headers)
#         print(f"  GET {url} ?week={week} -> {r.status_code}, len={len(r.content)}")
#         if r.status_code == 429:
#             _rate_limit_sleep(r, base_sleep, attempt); continue
#         r.raise_for_status()
#         text = r.text
#         if not text.strip(): return pd.DataFrame()
#         cdf = pd.read_csv(StringIO(text))
#         cols = {c.lower(): c for c in cdf.columns}
#         def pick(*names):
#             for n in names:
#                 if n in cols: return cols[n]
#             return None
#         dcol = pick("date")
#         tcol = pick("time","time (utc)")
#         ccol = pick("currency","country")
#         icol = pick("impact","importance")
#         ecol = pick("event","title")
#         if not all([dcol, tcol, ccol, icol, ecol]):
#             print("    CSV columns not recognized:", list(cdf.columns))
#             return pd.DataFrame()
#         ts = pd.to_datetime((cdf[dcol].astype(str)+" "+cdf[tcol].astype(str)), errors="coerce", utc=True)
#         df = pd.DataFrame({
#             "ts": ts,
#             "currency": cdf[ccol].astype(str).str.upper(),
#             "impact": cdf[icol].astype(str).str.lower(),
#             "event": cdf[ecol].astype(str).str.strip(),
#         }).dropna(subset=["ts"])
#         return df
#     return None

def _fetch_csv(sess: requests.Session, url: str, week: str, headers: Dict[str,str], base_sleep: float) -> Optional[pd.DataFrame]:
    from io import StringIO
    for attempt in range(4):
        try:
            r = sess.get(url, params={"week": week}, headers=headers)
            print(f"  GET {url} ?week={week} -> {r.status_code}, len={len(r.content)}")
        except RequestException as e:
            print(f"    CSV connect error: {e} (skipping host)")
            return None
        if r.status_code == 429:
            _rate_limit_sleep(r, base_sleep, attempt); continue
        try:
            r.raise_for_status()
        except RequestException as e:
            print(f"    CSV HTTP error: {e}")
            return None
        text = r.text
        if not text.strip():
            return pd.DataFrame()
        cdf = pd.read_csv(StringIO(text))
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
            print("    CSV columns not recognized:", list(cdf.columns))
            return pd.DataFrame()
        ts = pd.to_datetime((cdf[dcol].astype(str)+" "+cdf[tcol].astype(str)), errors="coerce", utc=True)
        df = pd.DataFrame({
            "ts": ts,
            "currency": cdf[ccol].astype(str).str.upper(),
            "impact": cdf[icol].astype(str).str.lower(),
            "event": cdf[ecol].astype(str).str.strip(),
        }).dropna(subset=["ts"])
        return df
    return None


# def _fetch_week(sess: requests.Session, week_monday: pd.Timestamp, base_sleep: float) -> pd.DataFrame:
#     week = week_monday.strftime("%Y-%m-%d")
#     referer = f"https://www.forexfactory.com/calendar?week={week}"
#     headers = {"Referer": referer, "Origin": "https://www.forexfactory.com"}

#     # JSON attempts
#     for u in JSON_ENDPOINTS:
#         df = _fetch_json(sess, u, week, headers, base_sleep)
#         if df is None: continue
#         df = _filter_to_week(df, week_monday)
#         if not df.empty: return df

#     # CSV attempts
#     for u in CSV_ENDPOINTS:
#         df = _fetch_csv(sess, u, week, headers, base_sleep)
#         if df is None: continue
#         df = _filter_to_week(df, week_monday)
#         if not df.empty: return df

#     return pd.DataFrame()

def _fetch_week(sess: requests.Session, week_monday: pd.Timestamp, base_sleep: float) -> pd.DataFrame:
    week = week_monday.strftime("%Y-%m-%d")
    referer = f"https://www.forexfactory.com/calendar?week={week}"
    headers = {"Referer": referer, "Origin": "https://www.forexfactory.com"}

    # JSON attempts (each host independent; network errors are handled inside)
    for u in JSON_ENDPOINTS:
        df = _fetch_json(sess, u, week, headers, base_sleep)
        if df is None:
            continue  # unreachable host → try next
        df = _filter_to_week(df, week_monday)
        print(f"    JSON rows after week-filter: {len(df)}")
        if not df.empty:
            return df

    # CSV attempts
    for u in CSV_ENDPOINTS:
        df = _fetch_csv(sess, u, week, headers, base_sleep)
        if df is None:
            continue
        df = _filter_to_week(df, week_monday)
        print(f"    CSV rows after week-filter: {len(df)}")
        if not df.empty:
            return df

    return pd.DataFrame()


def _load_cookie_file(path: Optional[Path]) -> Optional[str]:
    if not path: return None
    if not Path(path).exists(): return None
    txt = Path(path).read_text().strip()
    if "HttpOnly_" in txt or "\t" in txt:
        lines = []
        for line in txt.splitlines():
            if (not line) or line.startswith("#"): continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                lines.append(f"{name}={value}")
        return "; ".join(lines) if lines else None
    return txt

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

def main():
    ap = argparse.ArgumentParser(description="Resilient FF weekly news fetch (UTC).")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--start", type=str, required=True)
    ap.add_argument("--end", type=str, default="today")
    ap.add_argument("--min-impact", type=str, choices=["low","medium","high"], default="low")
    ap.add_argument("--sleep", type=float, default=6.0, help="Base sleep between weeks & for backoff.")
    ap.add_argument("--cookie-file", type=Path, default=None)
    ap.add_argument("--append", action="store_true", help="Append incrementally to OUT as we go.")
    args = ap.parse_args()

    cookie_str = _load_cookie_file(args.cookie_file)
    sess = _build_session(cookie_str=cookie_str)

    weeks = _weeks_between(args.start, args.end)
    if not weeks: raise SystemExit("No weeks in range.")

    rank = {"low":0,"medium":1,"high":2}
    thr = rank[args.min_impact]

    all_buf = []  # used only if not --append
    for i, wk in enumerate(weeks, 1):
        print(f"[{i}/{len(weeks)}] week={wk.date()} ...", flush=True)
        dfw = _fetch_week(sess, wk, args.sleep)
        if dfw.empty:
            print("  (no data or blocked; continuing)")
        else:
            dfw["impact"] = dfw["impact"].map(_norm_impact)
            dfw = dfw[dfw["impact"].map(rank).fillna(0) >= thr]
            dfw = dfw[["ts","currency","impact","event"]]
            if args.append:
                _append_save(args.out, dfw)
                print(f"  appended rows={len(dfw)} → {args.out}")
            else:
                all_buf.append(dfw)
        # polite pacing between weeks
        time.sleep(args.sleep + random.uniform(0.2, 0.8))

    if not args.append:
        if not all_buf:
            raise SystemExit("No news fetched. Try higher --sleep, a smaller range, or refresh cookies.")
        out = (pd.concat(all_buf, ignore_index=True)
                 .drop_duplicates()
                 .sort_values("ts"))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.out, index=False)
        print(f"\n✓ Wrote {args.out.resolve()} rows={len(out)}")

if __name__ == "__main__":
    main()
