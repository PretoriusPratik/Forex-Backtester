# file: tools/convert_to_ist.py
"""
Convert any CSV with 'ts' (UTC or tz-aware) to IST (Asia/Kolkata) and save with *_IST.csv.
Works for both OHLCV and news CSVs (schema preserved).
"""
import argparse
from pathlib import Path
import pandas as pd

def main():
    ap = argparse.ArgumentParser(description="Convert CSV with 'ts' to IST (+05:30).")
    ap.add_argument("--in-file", type=Path, required=True)
    ap.add_argument("--out-file", type=Path, default=None)
    ap.add_argument("--assume-tz", type=str, default="UTC", help="If input timestamps are naive, assume this tz.")
    args = ap.parse_args()

    df = pd.read_csv(args.in_file)
    if "ts" not in df.columns: raise SystemExit("Input CSV must contain 'ts' column.")
    ts = pd.to_datetime(df["ts"], errors="coerce", utc=False)
    if getattr(ts.dt, "tz", None) is None:
        ts = ts.dt.tz_localize(args.assume_tz)
    ts_ist = ts.dt.tz_convert("Asia/Kolkata")
    df["ts"] = ts_ist
    out = args.out_file or args.in_file.with_name(args.in_file.stem + "_IST.csv")
    df.to_csv(out, index=False)
    print(f"Wrote {out}")

if __name__ == "__main__":
    main()
