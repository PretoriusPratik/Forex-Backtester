import argparse
from pathlib import Path
from typing import List
import numpy as np
import pandas as pd

def _parse_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(",") if x.strip()]

def _freq(tf: str) -> str:
    return {"1m":"1min","15m":"15min","1h":"H"}[tf]

def _start_price(symbol: str) -> float:
    s = symbol.upper()
    if s.startswith("EURUSD"): return 1.05
    if s.startswith("GBPUSD"): return 1.25
    if s.startswith("USDJPY"): return 140.0
    return 1.00

def _simulate(n: int, start_price: float, seed: int, tf: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # session-aware volatility: NY and London higher
    idx = pd.date_range("2023-01-02", periods=n, freq=_freq(tf), tz="UTC")
    hours = idx.hour
    vol_scale = np.where((hours>=12)&(hours<=21), 1.5, np.where((hours>=7)&(hours<=16), 1.3, 0.9))
    steps = rng.normal(0, 0.0006 * vol_scale, size=n).cumsum()
    base = start_price * (1 + steps)
    open_ = base + rng.normal(0, 0.0003, size=n)
    close = base + rng.normal(0, 0.0003, size=n)
    hl = rng.normal(0.0010, 0.0003, size=n)
    high = np.maximum(open_, close) + np.abs(hl)
    low  = np.minimum(open_, close) - np.abs(hl)
    # pseudo-volume: higher in London/NY
    volume = (rng.integers(900, 1500, size=n) * vol_scale).astype(int)

    return pd.DataFrame({
        "ts": idx.tz_localize(None),  # write naive UTC
        "open": open_.round(5),
        "high": high.round(5),
        "low":  low.round(5),
        "close": close.round(5),
        "volume": volume
    })

def main():
    ap = argparse.ArgumentParser(description="Make synthetic FX OHLCV CSVs.")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--symbols", type=str, default="EURUSD")
    ap.add_argument("--timeframes", type=str, default="1m,15m")
    ap.add_argument("--rows-1m", type=int, default=5000, dest="rows_1m")
    ap.add_argument("--rows-15m", type=int, default=2000, dest="rows_15m")
    ap.add_argument("--rows-1h", type=int, default=600,  dest="rows_1h")
    args = ap.parse_args()

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    syms = _parse_list(args.symbols)
    tfs = _parse_list(args.timeframes)

    for s in syms:
        for tf in tfs:
            n = {"1m": args.rows_1m, "15m": args.rows_15m, "1h": args.rows_1h}[tf]
            df = _simulate(n, _start_price(s), seed=abs(hash((s, tf))) % (2**32), tf=tf)
            fp = out / f"{s}_{tf}.csv"
            df.to_csv(fp, index=False)
            print(f"Wrote {fp} rows={len(df)}")

if __name__ == "__main__":
    main()

