# file: tools/extract_wide_5m.py
"""
Extract 5-minute EURUSD candles whose high-low range > N pips,
and output date, time, volume in UTC.

Usage:
  python tools/extract_wide_5m.py \
    --csv-root ./data \
    --symbol EURUSD \
    --timeframe 5m \
    --threshold-pips 25 \
    --pip-size 0.0001 \
    --out ./wide_candles_EURUSD_5m.csv
"""

from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

def load_bars(fp: Path) -> pd.DataFrame:
    if not fp.exists():
        raise SystemExit(f"CSV not found: {fp}")
    df = pd.read_csv(fp)
    for c in ("ts","open","high","low","close"):
        if c not in df.columns:
            raise SystemExit(f"Missing required column '{c}' in {fp}")
    # Parse timestamps → tz-aware UTC; if already tz-aware, convert; if naive, localize as UTC.
    ts = pd.to_datetime(df["ts"], errors="coerce")
    if ts.dt.tz is None:
        ts = pd.to_datetime(df["ts"], utc=True, errors="coerce")  # assume UTC if naive
    else:
        ts = ts.dt.tz_convert("UTC")
    df["ts"] = ts
    if "volume" not in df.columns:
        df["volume"] = np.nan
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return df

def main():
    ap = argparse.ArgumentParser(description="Filter 5m candles with range > N pips and output UTC date/time/volume.")
    ap.add_argument("--csv-root", type=Path, required=True)
    ap.add_argument("--symbol", type=str, default="EURUSD")
    ap.add_argument("--timeframe", type=str, default="5m")
    ap.add_argument("--threshold-pips", type=float, default=25.0, help="Range threshold in pips (high-low).")
    ap.add_argument("--pip-size", type=float, default=0.0001, help="EURUSD pip size.")
    ap.add_argument("--out", type=Path, default=None, help="Output CSV path.")
    args = ap.parse_args()

    src = args.csv_root / f"{args.symbol}_{args.timeframe}.csv"
    df = load_bars(src)

    # Range in pips
    df["range_pips"] = (df["high"] - df["low"]).abs() / args.pip_size

    wide = df[df["range_pips"] > args.threshold_pips].copy()
    if wide.empty:
        print("No candles found above threshold.")
        return

    ts_utc = wide["ts"].dt.tz_convert("UTC")
    out_df = pd.DataFrame({
        "ts_utc": ts_utc.dt.strftime("%Y-%m-%d %H:%M:%S%z"),
        "date_utc": ts_utc.dt.strftime("%Y-%m-%d"),
        "time_utc": ts_utc.dt.strftime("%H:%M"),
        "volume": wide["volume"],
        "range_pips": wide["range_pips"].round(2),
    })

    out_path = args.out or (args.csv_root / f"wide_candles_{args.symbol}_{args.timeframe}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)

    print(f"✓ Found {len(out_df)} candles with range > {args.threshold_pips} pips")
    print(f"→ Saved: {out_path}")

if __name__ == "__main__":
    main()
