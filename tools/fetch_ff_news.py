# file: tools/fetch_ff_news.py
"""
Fetch ForexFactory calendar for a date range (weekly export), normalize to UTC,
and write a single CSV usable by your backtester: ts,currency,impact,event.

Usage:
  pip install requests pandas beautifulsoup4 python-dateutil pytz

  python tools/fetch_ff_news.py \
    --out ./data/news_ff_UTC.csv \
    --start 2020-01-01 \
    --end   today \
    --min-impact low \
    --sleep 4 \
    --max-retries 3

Notes:
- We iterate *weeks*; for each week we open the calendar page with `?week=YYYY-MM-DD`
  (Monday) and follow the "Weekly Export" link to JSON (preferred) or CSV fallback.
- ForexFactory enforces download pacing on weekly files; we default to sleep=4s and
  exponential backoff on errors to be polite.
- All timestamps are converted to UTC tz-aware.
"""

from __future__ import annotations
import argparse
import csv
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtp
from requests.adapters import HTTPAdapter, Retry

FF_CAL_BASE = "https://www.forexfactory.com/calendar"
# Weekly export links live on a separate CDN; we extract them from the page.
# Example targets: ff_calendar_thisweek.json / .csv (with a version hash).

@dataclass
class WeekRange:
    monday: datetime  # UTC date (00:00) used in query param

def _d(s: str) -> datetime:
    return pd.Timestamp(s).to_pydatetime().replace(tzinfo=None)

def weeks_between(start: str, end: str | None) -> List[WeekRange]:
    end_date = pd.Timestamp("today").normalize() if (end is None or end == "today") else pd.Timestamp(end)
    start_date = pd.Timestamp(start).normalize()
    # Align to Monday (ISO week)
    start_monday = (start_date - pd.Timedelta(days=(start_date.weekday()))).to_pydatetime()
    end_monday = (end_date - pd.Timedelta(days=(end_date.weekday()))).to_pydatetime()
    weeks: List[WeekRange] = []
    cur = start_monday
    while cur <= end_monday:
        weeks.append(WeekRange(monday=cur))
        cur = cur + timedelta(days=7)
    return weeks

def make_session(timeout: int = 20) -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=5, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({
        "User-Agent": "ff-news-fetcher/1.0 (educational; backtesting)",
        "Accept": "*/*",
        "Connection": "keep-alive",
    })
    s.request = _wrap_timeout(s.request, timeout)  # type: ignore
    return s

def _wrap_timeout(fn, timeout):
    def inner(method, url, **kw):
        kw.setdefault("timeout", timeout)
        return fn(method, url, **kw)
    return inner

def _find_weekly_export_url(page_html: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (json_url, csv_url) extracted from the week's calendar HTML.
    We look for anchor texts 'JSON' and 'CSV' under 'Weekly Export'.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    # Heuristic: find the 'Weekly Export' block, then anchors within.
    block = None
    for h in soup.find_all(text=lambda t: isinstance(t, str) and "Weekly Export" in t):
        block = h.parent
        break
    json_url = None
    csv_url = None
    if block:
        for a in block.find_all("a", href=True):
            label = (a.get_text() or "").strip().upper()
            href = a["href"]
            if label == "JSON":
                json_url = href
            elif label == "CSV":
                csv_url = href
    # Fallback: search all anchors for known filenames
    if not json_url or not csv_url:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".json") and "ff_calendar_thisweek" in href:
                json_url = json_url or href
            if href.endswith(".csv") and "ff_calendar_thisweek" in href:
                csv_url = csv_url or href
    return json_url, csv_url

def _fetch_week_file(sess: requests.Session, week: WeekRange, prefer_json: bool = True) -> pd.DataFrame:
    """
    Load the week's JSON (preferred) or CSV, return DataFrame with at least:
    ['ts','currency','impact','event'] in **local calendar time** initially.
    We later convert to UTC.
    """
    week_qs = week.monday.strftime("%Y-%m-%d")
    cal_url = f"{FF_CAL_BASE}?week={week_qs}"
    r = sess.get(cal_url)
    r.raise_for_status()

    json_url, csv_url = _find_weekly_export_url(r.text)
    if not json_url and not csv_url:
        raise RuntimeError(f"Could not locate weekly export links for {cal_url}")

    if prefer_json and json_url:
        jr = sess.get(json_url)
        jr.raise_for_status()
        js = jr.json()
        # Observed schema varies; we normalize defensively.
        rows = []
        for ev in js:
            # Common keys: 'date' or 'timestamp', 'country' or 'currency', 'impact', 'title'/'event'
            # Times are the **calendar display time** (tz implied by page). We'll parse to naive first.
            t_raw = ev.get("date") or ev.get("timestamp") or ev.get("time") or ev.get("datetime")
            cur = ev.get("currency") or ev.get("country")
            imp = ev.get("impact") or ev.get("impactDescription") or ev.get("importance")
            title = ev.get("title") or ev.get("event")
            if not (t_raw and cur and imp and title):
                continue
            rows.append({"ts_local": str(t_raw), "currency": str(cur).upper(),
                         "impact": str(imp).lower(), "event": str(title)})
        df = pd.DataFrame(rows)
        return df

    # CSV fallback
    cr = sess.get(csv_url or "")
    cr.raise_for_status()
    # CSV headers typically include Date, Time, Currency, Impact, Event, etc.
    from io import StringIO
    cdf = pd.read_csv(StringIO(cr.text))
    # Normalize probable column names
    colmap = {c.lower(): c for c in cdf.columns}
    def pick(*alts): 
        for a in alts:
            if a in colmap: return colmap[a]
        return None
    date_col = pick("date")
    time_col = pick("time")
    cur_col  = pick("currency","country")
    imp_col  = pick("impact","importance")
    evt_col  = pick("event","title","detail")
    if not all([date_col, time_col, cur_col, imp_col, evt_col]):
        raise RuntimeError("CSV structure not recognized.")
    # build a single local timestamp string
    ts_local = (cdf[date_col].astype(str).str.strip() + " " + cdf[time_col].astype(str).str.strip())
    df = pd.DataFrame({
        "ts_local": ts_local,
        "currency": cdf[cur_col].astype(str).str.upper(),
        "impact":   cdf[imp_col].astype(str).str.lower(),
        "event":    cdf[evt_col].astype(str),
    })
    return df

def _local_to_utc(ts_local: str, calendar_tz: str) -> pd.Timestamp:
    """
    Parse ts_local (e.g., 'Tue Oct 01 10:00am' or '2025-10-01 10:00') as if it's in calendar_tz,
    then convert to UTC. If parsing fails or 'All Day'/'Tentative' → return NaT.
    """
    s = (ts_local or "").strip()
    if not s or s.lower().startswith("all day") or s.lower().startswith("tentative"):
        return pd.NaT
    try:
        dt_naive = dtp.parse(s, fuzzy=True)  # naive
    except Exception:
        return pd.NaT
    try:
        # localize then convert
        dt_loc = pd.Timestamp(dt_naive).tz_localize(calendar_tz, ambiguous="NaT", nonexistent="NaT")
        return dt_loc.tz_convert("UTC")
    except Exception:
        return pd.NaT

def _detect_calendar_tz(page_html: str) -> str:
    """
    Try to detect 'Calendar Time Zone: <Name> (GMT ...)' banner on the page; else default to UTC.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    # crude scan
    marker = "Calendar Time Zone:"
    if marker in text:
        seg = text.split(marker, 1)[1]
        name = seg.split("(")[0].strip()
        if name:
            return name
    return "UTC"

def fetch_range(out_csv: Path, start: str, end: Optional[str], min_impact: str, sleep_sec: float, max_retries: int) -> None:
    sess = make_session()
    weeks = weeks_between(start, end)
    if not weeks:
        raise SystemExit("No weeks in range.")
    all_rows: List[pd.DataFrame] = []
    min_impact = min_impact.lower().strip()
    impact_rank = {"low": 0, "medium": 1, "med": 1, "high": 2}

    for i, wk in enumerate(weeks, 1):
        week_qs = wk.monday.strftime("%Y-%m-%d")
        print(f"[{i}/{len(weeks)}] Week starting {week_qs} ...", flush=True)
        # Load page first to get JSON/CSV export links and detect tz
        cal_url = f"{FF_CAL_BASE}?week={week_qs}"
        r = None
        for attempt in range(max_retries):
            try:
                r = sess.get(cal_url)
                r.raise_for_status()
                break
            except Exception as e:
                wait = sleep_sec * (2 ** attempt)
                print(f"  page fetch failed ({e}); retrying in {wait:.1f}s")
                time.sleep(wait)
        if r is None:
            print("  skipped (page failed).")
            continue

        cal_tz = _detect_calendar_tz(r.text)  # e.g., "Asia/Kolkata" or "Europe/London"; fallback UTC
        json_url, csv_url = _find_weekly_export_url(r.text)
        if not (json_url or csv_url):
            print("  no weekly export links found; skipping.")
            continue

        # Now get the actual week data (prefer JSON)
        df_week = None
        for attempt in range(max_retries):
            try:
                df_week = _fetch_week_file(sess, wk, prefer_json=True)
                break
            except Exception as e:
                wait = sleep_sec * (2 ** attempt)
                print(f"  export fetch failed ({e}); retrying in {wait:.1f}s")
                time.sleep(wait)
        if df_week is None:
            print("  skipped (export failed)."); continue
        if df_week.empty:
            print("  no events in this week."); 
            time.sleep(sleep_sec);  # polite pause anyway
            continue

        # Map impact to canonical low/medium/high values
        def map_imp(x: str) -> str:
            s = (x or "").lower()
            # common FF labels contain words like 'high', 'medium', 'low'
            if "high" in s: return "high"
            if "med"  in s: return "medium"
            if "low"  in s: return "low"
            return "low"  # default
        df_week["impact"] = df_week["impact"].map(map_imp)

        # Convert ts_local -> UTC Timestamp
        df_week["ts"] = df_week["ts_local"].apply(lambda s: _local_to_utc(s, cal_tz))
        df_week = df_week.dropna(subset=["ts"])
        df_week = df_week.drop(columns=["ts_local"])
        # Filter by impact threshold
        th = impact_rank.get(min_impact, 0)
        df_week = df_week[df_week["impact"].map(impact_rank).fillna(0) >= th]

        all_rows.append(df_week.reset_index(drop=True))

        # Polite pause between weeks
        time.sleep(sleep_sec)

    if not all_rows:
        raise SystemExit("No news rows fetched; please try a smaller date range first, or reduce min-impact.")
    out = pd.concat(all_rows, ignore_index=True).drop_duplicates().sort_values("ts")
    out["currency"] = out["currency"].str.upper()
    out["impact"] = out["impact"].str.lower()
    out = out[["ts","currency","impact","event"]]
    out.to_csv(out_csv, index=False)
    print(f"\n✓ Wrote {out_csv.resolve()} rows={len(out)}")

def main():
    ap = argparse.ArgumentParser(description="Fetch ForexFactory weekly news (UTC).")
    ap.add_argument("--out", type=Path, required=True, help="Output CSV path, e.g., ./data/news_ff_UTC.csv")
    ap.add_argument("--start", type=str, required=True, help="Start date YYYY-MM-DD")
    ap.add_argument("--end", type=str, default="today", help="End date YYYY-MM-DD or 'today'")
    ap.add_argument("--min-impact", type=str, choices=["low","medium","high"], default="low")
    ap.add_argument("--sleep", type=float, default=4.0, help="Seconds to sleep between weeks (respect rate limits).")
    ap.add_argument("--max-retries", type=int, default=3)
    args = ap.parse_args()
    fetch_range(args.out, args.start, args.end, args.min_impact, args.sleep, args.max_retries)

if __name__ == "__main__":
    main()
