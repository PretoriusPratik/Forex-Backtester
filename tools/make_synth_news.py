import argparse
from pathlib import Path
from typing import List
import numpy as np
import pandas as pd

def _parse_list(s: str) -> List[str]:
    return [x.strip().upper() for x in s.split(",") if x.strip()]

def main():
    ap = argparse.ArgumentParser(description="Make synthetic FX news calendar.")
    ap.add_argument("--out-file", type=Path, required=True)
    ap.add_argument("--currencies", type=str, default="EUR,USD,GBP,JPY")
    ap.add_argument("--events", type=int, default=200)
    args = ap.parse_args()

    rng = np.random.default_rng(1337)
    currs = _parse_list(args.currencies)
    start = pd.Timestamp("2023-01-02", tz="UTC")
    end   = pd.Timestamp("2023-03-01", tz="UTC")
    times = pd.to_datetime(rng.integers(int(start.value/1e9), int(end.value/1e9), size=args.events), unit="s", utc=True)

    impact_levels = np.array(["low","medium","high"])
    impact_probs = np.array([0.5, 0.35, 0.15])

    df = pd.DataFrame({
        "ts": times.tz_localize(None),  # naive UTC
        "currency": rng.choice(currs, size=args.events),
        "impact": rng.choice(impact_levels, p=impact_probs, size=args.events),
        "event": rng.choice(["CPI","GDP","NFP","PMI","Rate Decision","Jobs","Retail Sales"], size=args.events)
    }).sort_values("ts").reset_index(drop=True)

    df.to_csv(args.out_file, index=False)
    print(f"Wrote {args.out_file} rows={len(df)}")

if __name__ == "__main__":
    main()