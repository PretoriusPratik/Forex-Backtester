# file: tools/fetch_ff_selenium.py
"""
ForexFactory Weekly Export -> CSV via Selenium + requests (robust, slow, IST-aware).

- Opens each weekly page with your Chrome profile (keeps login + timezone = IST if you set it on FF)
- Reads the 'CSV' export link, downloads via requests using Selenium cookies
- Parses Date+Time in --calendar-tz (e.g., Asia/Kolkata) and converts to UTC
- Validates rows belong to that UTC week window
- Appends to one master CSV: ts,currency,impact,event

Setup:
  pip install selenium requests pandas python-dateutil pytz
  # Selenium 4.6+ includes Selenium Manager; no manual chromedriver needed

First run (visible) to log in to FF and set your calendar timezone to IST:
  python tools/fetch_ff_selenium.py \
    --out ./data/news_ff_UTC.csv \
    --start 2020-01-01 --end 2020-12-31 \
    --calendar-tz Asia/Kolkata \
    --sleep 5.0 \
    --profile-dir ./secrets/ff_chrome_profile \
    --append

Subsequent runs can reuse the same profile (still visible by default).
"""

from __future__ import annotations
import argparse
from pathlib import Path
from typing import List, Optional, Dict
import time
import requests
import pandas as pd
from dateutil import parser as dtp

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

CAL_URL = "https://www.forexfactory.com/calendar"

def weeks_between(start: str, end: str) -> List[pd.Timestamp]:
    s = pd.Timestamp(start).normalize()
    e = pd.Timestamp(end).normalize()
    s_mon = (s - pd.Timedelta(days=s.weekday())).normalize()
    e_mon = (e - pd.Timedelta(days=e.weekday())).normalize()
    out, cur = [], s_mon
    while cur <= e_mon:
        out.append(pd.Timestamp(cur))
        cur += pd.Timedelta(days=7)
    return out

def week_bounds_utc(week_monday: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    st = week_monday.tz_localize("UTC")
    en = (week_monday + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)).tz_localize("UTC")
    return st, en

def norm_impact(s: str) -> str:
    s = (s or "").lower()
    if "high" in s: return "high"
    if "med" in s: return "medium"
    if "low" in s: return "low"
    return "low"

def parse_csv_bytes(csv_bytes: bytes, calendar_tz: str) -> pd.DataFrame:
    from io import StringIO
    txt = csv_bytes.decode("utf-8", errors="ignore")
    if not txt.strip():
        return pd.DataFrame(columns=["ts","currency","impact","event"])
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
        # unexpected format; return empty to skip
        return pd.DataFrame(columns=["ts","currency","impact","event"])

    # Build naive local time, then localize to calendar_tz (IST), then convert to UTC
    ts_local = (cdf[dcol].astype(str).str.strip() + " " + cdf[tcol].astype(str).str.strip())
    ts_naive = pd.to_datetime(ts_local, errors="coerce")
    df = pd.DataFrame({
        "ts": ts_naive,
        "currency": cdf[ccol].astype(str).str.upper(),
        "impact": cdf[icol].astype(str).str.lower().map(norm_impact),
        "event": cdf[ecol].astype(str).str.strip(),
    }).dropna(subset=["ts"])

    # Localize to calendar_tz then convert to UTC
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(calendar_tz, nonexistent="NaT", ambiguous="NaT").dt.tz_convert("UTC")
    df = df.dropna(subset=["ts"])

    return df[["ts","currency","impact","event"]]

def append_save(out_csv: Path, df_new: pd.DataFrame) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    if out_csv.exists() and out_csv.stat().st_size > 0:
        cur = pd.read_csv(out_csv, parse_dates=["ts"])
        merged = (pd.concat([cur, df_new], ignore_index=True)
                  .drop_duplicates()
                  .sort_values("ts"))
        merged.to_csv(out_csv, index=False)
    else:
        df_new.sort_values("ts").to_csv(out_csv, index=False)

def skip_if_week_present(out_csv: Path, week_monday: pd.Timestamp) -> bool:
    if not out_csv.exists() or out_csv.stat().st_size == 0:
        return False
    try:
        df = pd.read_csv(out_csv, parse_dates=["ts"], usecols=["ts"])
    except Exception:
        return False
    st, en = week_bounds_utc(week_monday)
    return ((df["ts"] >= st) & (df["ts"] <= en)).any()

def build_cookie_header(sdriver) -> str:
    cookies = sdriver.get_cookies()
    # Build "name=value; name2=value2"
    parts = []
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if name and value:
            parts.append(f"{name}={value}")
    return "; ".join(parts)

def get_week_csv_bytes(sdriver, session: requests.Session, week: pd.Timestamp) -> Optional[bytes]:
    week_qs = week.strftime("%Y-%m-%d")
    url = f"{CAL_URL}?week={week_qs}"

    try:
        sdriver.get(url)
        # Wait for the "Weekly Export" block and the CSV link to appear
        Wait(sdriver, 20).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Weekly Export')]")))
        # CSV link anchor
        # Find any anchor whose text contains 'CSV'
        csv_link = sdriver.find_element(By.XPATH, "//a[contains(., 'CSV')]")
        href = csv_link.get_attribute("href")
        if not href or not href.endswith(".csv"):
            # Try scanning all anchors in the surrounding block
            links = sdriver.find_elements(By.TAG_NAME, "a")
            href = ""
            for a in links:
                txt = (a.text or "").strip().upper()
                if txt == "CSV":
                    href = a.get_attribute("href") or ""
                    break
        if not href:
            print("  CSV link not found on page; skipping.")
            return None

        # Build cookies from the browser and fetch via requests
        cookie_header = build_cookie_header(sdriver)
        headers = {
            "User-Agent": "Mozilla/5.0 (SeleniumFetcher)",
            "Accept": "text/csv,*/*;q=0.8",
            "Referer": url,
            "Origin": "https://www.forexfactory.com",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        # Download CSV
        r = session.get(href, headers=headers, timeout=40)
        if r.status_code == 429:
            # rate-limited; caller should sleep more and retry next runs
            print(f"  429 from CSV endpoint for week={week_qs}; got len={len(r.content)}")
            return None
        r.raise_for_status()
        if not r.content:
            print("  CSV endpoint returned empty body")
            return None
        return r.content
    except TimeoutException:
        print("  Page timeout; skipping week.")
        return None
    except WebDriverException as e:
        print(f"  WebDriver error: {e}")
        return None
    except requests.RequestException as e:
        print(f"  CSV request error: {e}")
        return None

def main():
    ap = argparse.ArgumentParser(description="Fetch FF weekly CSV via Selenium + requests, IST-aware.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--start", type=str, required=True)
    ap.add_argument("--end", type=str, required=True)
    ap.add_argument("--calendar-tz", type=str, default="Asia/Kolkata", help="Your FF calendar display timezone (e.g., Asia/Kolkata).")
    ap.add_argument("--sleep", type=float, default=5.0, help="Seconds to sleep between weeks (reduce throttling).")
    ap.add_argument("--profile-dir", type=Path, default=Path("./secrets/ff_chrome_profile"), help="Chrome user data dir to persist login + timezone settings.")
    ap.add_argument("--append", action="store_true", help="Append incrementally to --out each week.")
    ap.add_argument("--skip-existing", action="store_true", help="Skip weeks already present in --out.")
    args = ap.parse_args()

    # Build weeks
    weeks = weeks_between(args.start, args.end)
    if not weeks:
        raise SystemExit("No weeks in range.")

    # Selenium Chrome with persistent profile
    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={args.profile_dir.resolve()}")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    # Leave visible (headful) so you can log in and ensure FF is set to IST
    # If you *really* need headless, comment in:
    # options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)

    sess = requests.Session()

    # Rank for impact filtering (if you decide to add min-impact later; for now keep all)
    # rank = {"low":0,"medium":1,"high":2}

    try:
        pending = []  # used only when not --append
        for i, wk in enumerate(weeks, 1):
            wk_str = wk.strftime("%Y-%m-%d")
            print(f"[{i}/{len(weeks)}] week={wk_str}")

            if args.skip_existing and skip_if_week_present(args.out, wk):
                print("  already present; skipping")
                time.sleep(0.4)
                continue

            payload = get_week_csv_bytes(driver, sess, wk)
            if not payload:
                print("  (no csv; maybe throttled)"); time.sleep(args.sleep); continue

            df = parse_csv_bytes(payload, args.calendar_tz)
            if df.empty:
                print("  parsed 0 rows from CSV")
                time.sleep(args.sleep); continue

            # Keep only rows inside this week (UTC)
            st, en = week_bounds_utc(wk)
            df = df[(df["ts"] >= st) & (df["ts"] <= en)]
            print(f"  rows after week-filter: {len(df)}")
            if df.empty:
                time.sleep(args.sleep); continue

            # Normalize + save
            df = df[["ts","currency","impact","event"]]
            if args.append:
                append_save(args.out, df)
                print(f"  appended {len(df)} rows → {args.out}")
            else:
                pending.append(df)

            time.sleep(args.sleep)

        if not args.append:
            if not pending:
                raise SystemExit("No data fetched.")
            out = (pd.concat(pending, ignore_index=True)
                     .drop_duplicates()
                     .sort_values("ts"))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            out.to_csv(args.out, index=False)
            print(f"✓ wrote {args.out} rows={len(out)} "
                  f"range={out['ts'].min()} → {out['ts'].max()}")
        else:
            print(f"✓ append mode complete → {args.out}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
