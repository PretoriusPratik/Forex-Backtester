# file: tools/fetch_ff_news_direct.py
"""
Fetch ForexFactory weekly 'Weekly Export' files from the CDN (no HTML scraping).
Aggregates (JSON preferred, CSV fallback) into one UTC CSV:
    ts,currency,impact,event

Usage:
  pip install requests pandas python-dateutil pytz

  python tools/fetch_ff_news_direct.py \
    --out ./data/news_ff_UTC.csv \
    --start 2020-01-01 \
    --end today \
    --min-impact low \
    --sleep 3.5 \
    --cookie-file ""           # optional Netscape or "k=v; ..." string

Notes:
- We call:
    https://nfs.faireconomy.media/ff_calendar_thisweek.json?week=YYYY-MM-DD
  and fallback to:
    https://nfs.faireconomy.media/ff_calendar_thisweek.csv?week=YYYY-MM-DD
- Add a Referer to mimic a browser.
- If your IP is still throttled, supply cookies via --cookie-file (copy from your browser).
"""

from __future__ import annotations
import argparse, time, os
from pathlib import Path
from typing import List, Optional, Dict
import pandas as pd
import requests
from dateutil import parser as dtp
from datetime import date, timedelta  # at top if not present


# CDN_JSON = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# CDN_CSV  = "https://nfs.faireconomy.media/ff_calendar_thisweek.csv"
JSON_ENDPOINTS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json",
]
CSV_ENDPOINTS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.csv",
    "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.csv",
]

# def _weeks_between(start: str, end: Optional[str]) -> List[pd.Timestamp]:
#     end_ts = (pd.Timestamp.utcnow().normalize()
#               if (end is None or end.lower()=="today") else pd.Timestamp(end))
#     st_ts = pd.Timestamp(start)
#     # align both to Monday
#     st_mon = st_ts - pd.Timedelta(days=st_ts.weekday())
#     en_mon = end_ts - pd.Timedelta(days=end_ts.weekday())
#     weeks = []
#     cur = st_mon.normalize()
#     while cur <= en_mon:
#         weeks.append(cur)
#         cur = cur + pd.Timedelta(days=7)
#     return weeks
def _weeks_between(start: str, end: str | None) -> list[pd.Timestamp]:
    """
    Return a list of week-Mondays as tz-naive pandas Timestamps.
    Works entirely in date space to avoid tz issues, then converts to Timestamp.
    """
    # Parse to date in UTC, then discard tz
    start_dt = pd.to_datetime(start, utc=True).date()
    if end is None or str(end).lower() == "today":
        end_dt = pd.Timestamp.utcnow().date()
    else:
        end_dt = pd.to_datetime(end, utc=True).date()

    # Align both to Monday
    start_mon = start_dt - timedelta(days=start_dt.weekday())
    end_mon   = end_dt   - timedelta(days=end_dt.weekday())

    weeks = []
    cur = start_mon
    while cur <= end_mon:
        # make tz-naive Timestamp (date → midnight)
        weeks.append(pd.Timestamp(cur))
        cur = cur + timedelta(days=7)
    return weeks

def _load_cookie_file(path: Optional[Path]) -> Optional[str]:
    if not path: return None
    if not path.exists(): return None
    txt = path.read_text().strip()
    # Accept either Netscape format or simple "k=v; k2=v2"
    if "HttpOnly_" in txt or "\t" in txt:
        # crude Netscape parser: take last column as value; build "name=value" lines
        cookie_lines = []
        for line in txt.splitlines():
            if not line or line.startswith("#"): continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                cookie_lines.append(f"{name}={value}")
        return "; ".join(cookie_lines) if cookie_lines else None
    return txt

# def _sess(cookie_str: Optional[str], timeout=20) -> requests.Session:
#     s = requests.Session()
#     s.headers.update({
#         "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 "
#                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
#         "Accept": "*/*",
#         "Connection": "keep-alive",
#     })
#     if cookie_str:
#         s.headers["Cookie"] = cookie_str
#     s.request = _wrap_timeout(s.request, timeout)  # type: ignore
#     return s

# --- replace _sess() with this stronger version ---
def _sess(cookie_str: Optional[str], timeout=25) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        # look like a normal browser
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/csv, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        # some CDNs check these:
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    })
    if cookie_str:
        s.headers["Cookie"] = cookie_str
    s.request = _wrap_timeout(s.request, timeout)  # type: ignore
    return s


def _wrap_timeout(fn, timeout):
    def inner(method, url, **kw):
        kw.setdefault("timeout", timeout)
        return fn(method, url, **kw)
    return inner

# def _try_fetch_week(sess: requests.Session, week: pd.Timestamp) -> pd.DataFrame:
#     qs = {"week": week.strftime("%Y-%m-%d")}
#     ref = f"https://www.forexfactory.com/calendar?week={qs['week']}"
#     # JSON first
#     try:
#         rj = sess.get(CDN_JSON, params=qs, headers={"Referer": ref})
#         rj.raise_for_status()
#         js = rj.json()
#         rows = []
#         for ev in js:
#             # Prefer UTC 'timestamp' if provided
#             ts = ev.get("timestamp")
#             if ts is not None:
#                 # often seconds; sometimes ms—handle both
#                 ts = int(ts)
#                 if ts > 10_000_000_000:  # ms
#                     ts = pd.to_datetime(ts, unit="ms", utc=True)
#                 else:
#                     ts = pd.to_datetime(ts, unit="s", utc=True)
#             else:
#                 # Build from textual fields
#                 # Common keys: 'date' or 'time'/'datetime'
#                 t_raw = ev.get("datetime") or ev.get("date") or ev.get("time")
#                 if not t_raw:
#                     continue
#                 # best-effort parse then treat as UTC (FF exports are usually UTC in feeds)
#                 try:
#                     ts = pd.Timestamp(dtp.parse(str(t_raw))).tz_localize("UTC")
#                 except Exception:
#                     continue

#             cur = (ev.get("currency") or ev.get("country") or "").upper()
#             imp = str(ev.get("impact") or ev.get("impactDescription") or ev.get("importance") or "").lower()
#             title = str(ev.get("title") or ev.get("event") or "").strip()
#             if not (cur and title):
#                 continue
#             rows.append({"ts": ts, "currency": cur, "impact": imp, "event": title})
#         df = pd.DataFrame(rows)
#         if not df.empty:
#             return df
#     except Exception:
#         pass

#     # CSV fallback
#     try:
#         rc = sess.get(CDN_CSV, params=qs, headers={"Referer": ref})
#         rc.raise_for_status()
#         from io import StringIO
#         cdf = pd.read_csv(StringIO(rc.text))
#         # Likely columns: Date, Time, Currency, Impact, Event, ...; sometimes UTC columns exist
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
#             return pd.DataFrame()

#         # Build timestamp; assume UTC if "time (utc)" existed; else treat as UTC (FF export is UTC-oriented)
#         ts_str = (cdf[dcol].astype(str).str.strip() + " " + cdf[tcol].astype(str).str.strip())
#         ts = pd.to_datetime(ts_str, errors="coerce", utc=True)
#         df = pd.DataFrame({
#             "ts": ts,
#             "currency": cdf[ccol].astype(str).str.upper(),
#             "impact": cdf[icol].astype(str).str.lower(),
#             "event": cdf[ecol].astype(str).str.strip(),
#         }).dropna(subset=["ts"])
#         return df
#     except Exception:
#         return pd.DataFrame()

# --- replace _try_fetch_week() with this robust multi-endpoint version ---
def _try_fetch_week(sess: requests.Session, week: pd.Timestamp) -> pd.DataFrame:
    """
    Try JSON endpoints first (both hosts), then CSV endpoints.
    Log status codes and payload length to help debug blocks.
    """
    qs = {"week": week.strftime("%Y-%m-%d")}
    referer = f"https://www.forexfactory.com/calendar?week={qs['week']}"
    common_hdr = {"Referer": referer, "Origin": "https://www.forexfactory.com"}

    # 1) JSON attempts
    for url in JSON_ENDPOINTS:
        try:
            r = sess.get(url, params=qs, headers=common_hdr)
            print(f"  GET {url} ?week={qs['week']}  -> {r.status_code}, len={len(r.content)}")
            r.raise_for_status()
            js = r.json()
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
            if rows:
                return pd.DataFrame(rows)
        except Exception as e:
            print(f"    JSON fetch failed: {e}")

    # 2) CSV attempts
    for url in CSV_ENDPOINTS:
        try:
            rc = sess.get(url, params=qs, headers=common_hdr)
            print(f"  GET {url} ?week={qs['week']}  -> {rc.status_code}, len={len(rc.content)}")
            rc.raise_for_status()
            from io import StringIO
            text = rc.text
            if not text.strip():
                continue
            cdf = pd.read_csv(StringIO(text))
            cols = {c.lower(): c for c in cdf.columns}
            def pick(*names):
                for n in names:
                    if n in cols: return cols[n]
                return None
            dcol = pick("date")
            tcol = pick("time", "time (utc)")
            ccol = pick("currency", "country")
            icol = pick("impact", "importance")
            ecol = pick("event", "title")
            if not all([dcol, tcol, ccol, icol, ecol]):
                print("    CSV structure not recognized; cols:", list(cdf.columns))
                continue
            ts_str = (cdf[dcol].astype(str).str.strip() + " " + cdf[tcol].astype(str).str.strip())
            ts = pd.to_datetime(ts_str, errors="coerce", utc=True)
            df = pd.DataFrame({
                "ts": ts,
                "currency": cdf[ccol].astype(str).str.upper(),
                "impact": cdf[icol].astype(str).str.lower(),
                "event": cdf[ecol].astype(str).str.strip(),
            }).dropna(subset=["ts"])
            if not df.empty:
                return df
        except Exception as e:
            print(f"    CSV fetch failed: {e}")

    # none worked
    return pd.DataFrame()


def _norm_impact(s: str) -> str:
    s = (s or "").lower()
    if "high" in s: return "high"
    if "med"  in s: return "medium"
    if "low"  in s: return "low"
    return "low"

def main():
    ap = argparse.ArgumentParser(description="Fetch ForexFactory weekly exports (UTC).")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--start", type=str, required=True)
    ap.add_argument("--end", type=str, default="today")
    ap.add_argument("--min-impact", type=str, choices=["low","medium","high"], default="low")
    ap.add_argument("--sleep", type=float, default=3.5)
    ap.add_argument("--cookie-file", type=Path, default=None, help="Optional cookie file ('k=v; ...' or Netscape format).")
    args = ap.parse_args()

    weeks = _weeks_between(args.start, args.end)
    if not weeks: raise SystemExit("No weeks in range.")
    cookie_str = _load_cookie_file(args.cookie_file)
    sess = _sess(cookie_str)

    out_all = []
    for i, wk in enumerate(weeks, 1):
        print(f"[{i}/{len(weeks)}] week={wk.date()} ...", flush=True)
        dfw = _try_fetch_week(sess, wk)
        if dfw.empty:
            print("  (no data or blocked; continuing)")
        else:
            dfw["impact"] = dfw["impact"].map(_norm_impact)
            out_all.append(dfw)
        time.sleep(args.sleep)

    if not out_all:
        raise SystemExit("No news fetched. Provide --cookie-file (browser cookies) or try a shorter range.")

    out = pd.concat(out_all, ignore_index=True).drop_duplicates().sort_values("ts")
    # impact filter
    rank = {"low":0,"medium":1,"high":2}
    thr = rank[args.min_impact]
    out = out[out["impact"].map(rank) >= thr]
    out = out[["ts","currency","impact","event"]]
    out.to_csv(args.out, index=False)
    print(f"\n✓ Wrote {args.out.resolve()} rows={len(out)}")

if __name__ == "__main__":
    main()
