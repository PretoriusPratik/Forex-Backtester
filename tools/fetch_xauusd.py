# file: tools/fetch_xauusd.py
"""
Fetch XAUUSD minute bars (1m/5m/15m) for a date range.
Prefers dukascopy-python>=4.x; falls back to 'duka' CLI if needed.

Usage:
  # install once
  python -m pip install --upgrade pandas numpy pytz "dukascopy-python>=4.0.0"

  # run (5 years example)
  python tools/fetch_xauusd.py \
    --out-dir ./data \
    --start 2020-01-01 --end 2025-01-01 \
    --timeframes 1m,5m,15m \
    --tz UTC
"""
from __future__ import annotations
import argparse, sys, subprocess, shutil
from pathlib import Path
from typing import List, Optional
import pandas as pd

# ---------- utils ----------
def _parse_tf_list(s: str) -> List[str]:
    out = []
    for x in s.split(","):
        t = x.strip().lower().replace("min", "m")
        if t in {"1m", "5m", "15m"}:
            out.append(t)
    return out

def _convert_tz(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    if df.empty: return df
    ts = pd.to_datetime(df["ts"], utc=True)
    df["ts"] = ts.dt.tz_convert(tz)
    return df

def _write_csv(df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

# ---------- Path A: dukascopy-python >=4.x ----------
def _find_xauusd_instrument(inst_mod) -> Optional[object]:
    """
    Best-effort scan for an instrument constant referring to XAUUSD in dukascopy_python.instruments.
    If not found, return None so we fall back to 'duka'.
    """
    for name in dir(inst_mod):
        if not name.isupper(): continue
        if "XAU" in name and "USD" in name:
            try:
                val = getattr(inst_mod, name)
                # rudimentary sanity: val is typically an enum/obj stringifiable
                if val:
                    return val
            except Exception:
                pass
    return None

def _fetch_with_dcp4_xauusd(tf: str, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> Optional[pd.DataFrame]:
    try:
        import dukascopy_python as dcp
        from dukascopy_python import instruments as inst
    except Exception:
        return None

    live_fetch = getattr(dcp, "live_fetch", None)
    TIME_UNIT_MIN = getattr(dcp, "TIME_UNIT_MIN", None)
    OFFER_SIDE_BID = getattr(dcp, "OFFER_SIDE_BID", None)
    if live_fetch is None or TIME_UNIT_MIN is None or OFFER_SIDE_BID is None:
        return None

    instrument = _find_xauusd_instrument(inst)
    if instrument is None:
        # Not all builds expose a metals constant; let caller fallback to duka
        return None

    iv = {"1m": 1, "5m": 5, "15m": 15}[tf]

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

# ---------- Path B: fallback to duka CLI ----------
def _duka_available() -> bool:
    return shutil.which("duka") is not None

def _ensure_duka() -> None:
    if not _duka_available():
        print("Installing 'duka' CLI as fallback...", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "duka"])

def _fetch_with_duka_xauusd(tf: str, start: str, end: str, work_dir: Path) -> pd.DataFrame:
    """
    Use duka CLI to download XAUUSD ticks, then resample to tf.
    """
    _ensure_duka()
    raw_root = work_dir / "duka_raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    print(f"[duka] downloading ticks XAUUSD {start}→{end} ...")
    # duka writes into raw_root/XAUUSD/....csv
    subprocess.check_call([
        "duka", "XAUUSD",
        "--from", start, "--to", end,
        "--duka-format", "ticks",
        "--out", str(raw_root),
    ])

    import glob
    files = sorted(glob.glob(str(raw_root / "XAUUSD" / "**/*.csv"), recursive=True))
    if not files:
        return pd.DataFrame(columns=["ts","open","high","low","close","volume"])

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
    v = ticks["mid"].resample(rule).count()  # tick count per bar

    bars = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()
    return bars.reset_index().rename(columns={"ts": "ts"})

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Fetch XAUUSD bars (Dukascopy).")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--start", type=str, required=True)      # YYYY-MM-DD
    ap.add_argument("--end", type=str, required=True)        # YYYY-MM-DD
    ap.add_argument("--timeframes", type=str, default="1m,5m,15m")
    ap.add_argument("--tz", type=str, default="UTC")         # e.g., Asia/Kolkata
    args = ap.parse_args()

    out = args.out_dir
    tfs = _parse_tf_list(args.timeframes)
    if not tfs:
        raise SystemExit("No valid timeframes. Use any of: 1m,5m,15m")

    start_utc = pd.Timestamp(args.start, tz="UTC")
    end_utc   = pd.Timestamp(args.end,   tz="UTC")

    for tf in tfs:
        print(f"\n=== XAUUSD {tf} {args.start} → {args.end} ===")
        # Try dukascopy-python 4.x
        df = _fetch_with_dcp4_xauusd(tf, start_utc, end_utc)
        if df is None:
            print("[info] dukascopy-python 4.x path not available for XAUUSD; falling back to 'duka' ticks.")
            df = _fetch_with_duka_xauusd(tf, args.start, args.end, out)

        if df.empty:
            print(f"[warn] no data for XAUUSD {tf}")
            continue

        df = _convert_tz(df, args.tz)
        fp = out / f"XAUUSD_{tf}.csv"
        _write_csv(df, fp)
        print(f"✓ Wrote {fp} rows={len(df)}")

if __name__ == "__main__":
    main()
