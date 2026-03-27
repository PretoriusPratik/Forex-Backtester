# tools/fetch_fx_dcp4.py
"""
Fetch FX candles using dukascopy-python >= 4.x (preferred), with
automatic fallback to 'duka' CLI if the Python API isn't present.

Outputs backtester-ready CSVs: ts,open,high,low,close,volume
"""

from __future__ import annotations
import argparse
from pathlib import Path
from typing import Dict, List, Optional
import sys
import subprocess
import shutil
import pandas as pd

# ---------------------------
# Helpers
# ---------------------------

INSTR_MAP: Dict[str, str] = {
    "EURUSD": "INSTRUMENT_FX_MAJORS_EUR_USD",
    "GBPUSD": "INSTRUMENT_FX_MAJORS_GBP_USD",
    "USDJPY": "INSTRUMENT_FX_MAJORS_USD_JPY",
    "AUDUSD": "INSTRUMENT_FX_MAJORS_AUD_USD",
    "USDCAD": "INSTRUMENT_FX_MAJORS_USD_CAD",
    "USDCHF": "INSTRUMENT_FX_MAJORS_USD_CHF",
    "NZDUSD": "INSTRUMENT_FX_MAJORS_NZD_USD",
    "EURJPY": "INSTRUMENT_FX_MAJORS_EUR_JPY",
    "GBPJPY": "INSTRUMENT_FX_MAJORS_GBP_JPY",
}

def _parse_list(s: str) -> List[str]:
    return [x.strip().upper() for x in s.split(",") if x.strip()]

def _parse_tf_list(s: str) -> List[str]:
    # Accept 1m/1M/1min forms and normalize to 1m/5m/15m
    out = []
    for x in s.split(","):
        t = x.strip().lower()
        t = t.replace("min", "m")  # allow '1min' etc.
        out.append(t)
    return [t for t in out if t in {"1m","5m","15m"}]

def _convert_tz(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    if df.empty:
        return df
    ts = pd.to_datetime(df["ts"], utc=True)
    df["ts"] = ts.dt.tz_convert(tz)
    return df

def _write_csv(df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

# ---------------------------
# Path A: dukascopy-python >=4.x
# ---------------------------

def _fetch_with_dcp4(symbol: str, tf: str, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> Optional[pd.DataFrame]:
    """
    Try dukascopy-python 4.x live_fetch route.
    Returns DataFrame or None if API not available.
    """
    try:
        import dukascopy_python as dcp  # installed per user's log
        from dukascopy_python import instruments as inst
    except Exception:
        return None

    # Determine instrument constant
    name = INSTR_MAP.get(symbol)
    if not name or not hasattr(inst, name):
        raise SystemExit(f"Unsupported symbol: {symbol}. Supported: {', '.join(sorted(INSTR_MAP))}")
    instrument = getattr(inst, name)

    # live_fetch + time unit constants may or may not exist depending on build
    live_fetch = getattr(dcp, "live_fetch", None)
    TIME_UNIT_MIN = getattr(dcp, "TIME_UNIT_MIN", None)
    OFFER_SIDE_BID = getattr(dcp, "OFFER_SIDE_BID", None)
    if live_fetch is None or TIME_UNIT_MIN is None or OFFER_SIDE_BID is None:
        # API not present in this build → signal to caller to try fallback
        return None

    iv = {"1m": 1, "5m": 5, "15m": 15}.get(tf)
    if iv is None:
        raise SystemExit(f"Unsupported timeframe: {tf}")

    # Iterate generator to completion; last df holds all rows
    df_last = None
    for df in live_fetch(
        instrument=instrument,
        interval_value=iv,
        time_unit=TIME_UNIT_MIN,
        offer_side=OFFER_SIDE_BID,
        start=start_utc,
        end=end_utc,
    ):
        df_last = df

    if df_last is None or df_last.empty:
        return pd.DataFrame(columns=["ts","open","high","low","close","volume"])

    out = df_last.reset_index().rename(columns={"timestamp": "ts"})
    return out[["ts","open","high","low","close","volume"]].copy()

# ---------------------------
# Path B: fallback to duka CLI
# ---------------------------

def _duka_available() -> bool:
    return shutil.which("duka") is not None

def _install_duka_if_missing() -> None:
    if not _duka_available():
        print("Installing 'duka' CLI as a fallback...", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "duka"])

def _fetch_with_duka(symbol: str, tf: str, start: str, end: str, out_dir: Path) -> pd.DataFrame:
    """
    Use duka CLI to download ticks, then resample to tf.
    """
    _install_duka_if_missing()
    raw_dir = out_dir / "duka_raw" / symbol
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Download ticks (UTC)
    print(f"[duka] downloading ticks for {symbol} {start}→{end} ...")
    subprocess.check_call([
        "duka", symbol,
        "--from", start, "--to", end,
        "--duka-format", "ticks",
        "--out", str(raw_dir.parent),
    ])

    # Load & resample
    import glob
    import numpy as np

    files = sorted(glob.glob(str(raw_dir / "**/*.csv"), recursive=True))
    if not files:
        return pd.DataFrame(columns=["ts","open","high","low","close","volume"])

    # duka ticks: timestamp,bid,ask,volume,flag (no header)
    it = (pd.read_csv(f, names=["ts","bid","ask","vol","flag"]) for f in files)
    ticks = pd.concat(it, ignore_index=True)
    ticks["ts"] = pd.to_datetime(ticks["ts"], utc=True)
    ticks["mid"] = (ticks["bid"] + ticks["ask"]) / 2.0
    ticks = ticks.set_index("ts").sort_index()

    rule = {"1m": "1min", "5m": "5min", "15m": "15min"}[tf]
    o = ticks["mid"].resample(rule).first()
    h = ticks["mid"].resample(rule).max()
    l = ticks["mid"].resample(rule).min()
    c = ticks["mid"].resample(rule).last()
    v = ticks["mid"].resample(rule).count()  # tick count

    bars = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()
    return bars.reset_index().rename(columns={"ts": "ts"})

# ---------------------------
# Main
# ---------------------------

def main():
    ap = argparse.ArgumentParser(description="Backfill FX candles (Dukascopy).")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--symbols", type=str, default="EURUSD")
    ap.add_argument("--start", type=str, required=True)  # YYYY-MM-DD
    ap.add_argument("--end", type=str, required=True)    # YYYY-MM-DD
    ap.add_argument("--timeframes", type=str, default="1m,5m,15m")
    ap.add_argument("--tz", type=str, default="UTC")     # e.g., Asia/Kolkata
    args = ap.parse_args()

    out = args.out_dir
    syms = _parse_list(args.symbols)
    tfs = _parse_tf_list(args.timeframes)
    start_utc = pd.Timestamp(args.start, tz="UTC")
    end_utc   = pd.Timestamp(args.end,   tz="UTC")

    for sym in syms:
        for tf in tfs:
            if tf not in {"1m","5m","15m"}:
                print(f"[skip] unsupported timeframe: {tf}")
                continue

            print(f"\n=== {sym} {tf} {args.start} → {args.end} ===")
            df = _fetch_with_dcp4(sym, tf, start_utc, end_utc)

            if df is None:
                print("[info] dukascopy-python 4.x API not available in this build; falling back to 'duka' CLI.")
                df = _fetch_with_duka(sym, tf, args.start, args.end, out)

            if df.empty:
                print(f"[warn] no data for {sym} {tf}")
                continue

            df = _convert_tz(df, args.tz)
            fp = out / f"{sym}_{tf}.csv"
            _write_csv(df, fp)
            print(f"✓ Wrote {fp} rows={len(df)}")

if __name__ == "__main__":
    main()
