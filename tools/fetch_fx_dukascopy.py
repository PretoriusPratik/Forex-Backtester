# # # file: tools/fetch_fx_dukascopy.py
# # """
# # Download FX ticks from Dukascopy and resample to 1m/5m/15m CSVs
# # that match the backtester format: ts,open,high,low,close,volume (UTC by default).

# # Usage:
# #   pip install pandas numpy pytz dukascopy-python
# #   python tools/fetch_fx_dukascopy.py \
# #     --out-dir ./data \
# #     --symbols EURUSD,GBPUSD,USDJPY \
# #     --start 2020-01-01 --end 2025-01-01 \
# #     --timeframes 1m,5m,15m \
# #     --tz UTC

# # Notes:
# # - Volume is tick count per bar (typical for FX).
# # - Dukascopy instrument codes use no slash, uppercase (e.g., 'EURUSD', 'USDJPY').
# # """
# # from __future__ import annotations
# # import argparse
# # from pathlib import Path
# # from typing import List
# # from datetime import datetime, timezone
# # import pandas as pd
# # import numpy as np

# # # lib: https://pypi.org/project/dukascopy-python/
# # # from dukascopy_python.downloader import Downloader as DukaDL
# # from dukascopy_python.downloader import Downloader as DukaDL

# # def _parse_list(s: str) -> List[str]:
# #     return [x.strip() for x in s.split(",") if x.strip()]

# # def _resample_ticks_to_ohlcv(ticks: pd.DataFrame, tf: str) -> pd.DataFrame:
# #     """
# #     ticks columns expected: ['timestamp','bid','ask'] (UTC tz-aware)
# #     Price: use mid = (bid+ask)/2. Volume: tick count.
# #     """
# #     if ticks.empty:
# #         return pd.DataFrame(columns=["ts","open","high","low","close","volume"])

# #     ticks = ticks.copy()
# #     # Ensure datetime64[ns, UTC]
# #     if not pd.api.types.is_datetime64tz_dtype(ticks["timestamp"]):
# #         ticks["timestamp"] = pd.to_datetime(ticks["timestamp"], utc=True)

# #     ticks = ticks.set_index("timestamp").sort_index()
# #     ticks["mid"] = (ticks["bid"] + ticks["ask"]) / 2.0

# #     rule = {"1m": "1min", "5m": "5min", "15m": "15min"}[tf]
# #     o = ticks["mid"].resample(rule).first()
# #     h = ticks["mid"].resample(rule).max()
# #     l = ticks["mid"].resample(rule).min()
# #     c = ticks["mid"].resample(rule).last()
# #     v = ticks["mid"].resample(rule).count()  # tick volume

# #     df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()
# #     df = df.reset_index().rename(columns={"timestamp": "ts"})
# #     return df

# # def _convert_tz(df: pd.DataFrame, tz: str) -> pd.DataFrame:
# #     """Convert ts (currently UTC tz-aware) to chosen timezone and write tz-aware string."""
# #     if df.empty:
# #         return df
# #     ts = pd.to_datetime(df["ts"], utc=True)
# #     df["ts"] = ts.dt.tz_convert(tz)
# #     return df

# # def download_pair(symbol: str, start: str, end: str) -> pd.DataFrame:
# #     """
# #     Return ticks df: ['timestamp','bid','ask'] tz-aware UTC.
# #     Warning: Large downloads will take time; dukascopy-python paginates internally.
# #     """
# #     start_dt = pd.Timestamp(start, tz="UTC")
# #     end_dt = pd.Timestamp(end, tz="UTC")
# #     dl = DukaDL()
# #     data = dl.download(symbol=symbol, from_date=start_dt, to_date=end_dt, format="df", verbose=True)
# #     # dukascopy-python returns DataFrame with columns timestamp,bid,ask (tz-aware)
# #     if data is None or len(data) == 0:
# #         return pd.DataFrame(columns=["timestamp","bid","ask"])
# #     return data[["timestamp","bid","ask"]].dropna()

# # def main():
# #     ap = argparse.ArgumentParser(description="Backfill FX candles using Dukascopy (free).")
# #     ap.add_argument("--out-dir", type=Path, required=True)
# #     ap.add_argument("--symbols", type=str, default="EURUSD")
# #     ap.add_argument("--start", type=str, required=True)  # e.g., 2020-01-01
# #     ap.add_argument("--end", type=str, required=True)    # e.g., 2025-01-01
# #     ap.add_argument("--timeframes", type=str, default="1m,5m,15m")
# #     ap.add_argument("--tz", type=str, default="UTC", help="Output timezone for ts column (UTC or Asia/Kolkata etc.)")
# #     args = ap.parse_args()

# #     out = args.out_dir; out.mkdir(parents=True, exist_ok=True)
# #     syms = _parse_list(args.symbols)
# #     tfs  = _parse_list(args.timeframes)

# #     for sym in syms:
# #         print(f"\n=== Downloading ticks: {sym} {args.start} → {args.end} ===")
# #         ticks = download_pair(sym, args.start, args.end)
# #         if ticks.empty:
# #             print(f"[warn] no ticks for {sym} in range.")
# #             continue
# #         for tf in tfs:
# #             print(f"  → Resampling {tf}...")
# #             df = _resample_ticks_to_ohlcv(ticks, tf)
# #             df = _convert_tz(df, args.tz)
# #             fp = out / f"{sym}_{tf}.csv"
# #             df.to_csv(fp, index=False)
# #             print(f"  ✓ Wrote {fp} rows={len(df)}")

# # if __name__ == "__main__":
# #     main()
# # tools/fetch_fx_dukascopy.py
# """
# Download FX ticks from Dukascopy and resample to 1m/5m/15m CSVs
# that match the backtester format: ts,open,high,low,close,volume.

# Usage:
#   python tools/fetch_fx_dukascopy.py \
#     --out-dir ./data \
#     --symbols EURUSD,GBPUSD,USDJPY \
#     --start 2020-01-01 --end 2025-01-01 \
#     --timeframes 1m,5m,15m \
#     --tz UTC
# """
# from __future__ import annotations
# import argparse
# from pathlib import Path
# from typing import List
# import pandas as pd
# import numpy as np

# # --- Robust import: prefer 'dukascopy', fallback to 'dukascopy_python' ---
# try:
#     # pip install dukascopy
#     from dukascopy import Downloader as DukaDL
# except Exception:
#     try:
#         # older alt package name some guides mention
#         from dukascopy_python.downloader import Downloader as DukaDL  # type: ignore
#     except Exception as e:
#         raise SystemExit(
#             "Missing Dukascopy client.\n"
#             "Install with:\n"
#             "  pip install dukascopy\n\n"
#             "If you still get import issues, try:\n"
#             "  pip uninstall dukascopy-python dukascopy -y && pip install dukascopy\n"
#             f"\nOriginal import error: {e}"
#         )

# def _parse_list(s: str) -> List[str]:
#     return [x.strip() for x in s.split(",") if x.strip()]

# def _resample_ticks_to_ohlcv(ticks: pd.DataFrame, tf: str) -> pd.DataFrame:
#     """
#     Input columns: ['timestamp','bid','ask'] (UTC tz-aware).
#     Price = mid = (bid+ask)/2. Volume = tick count.
#     """
#     if ticks is None or ticks.empty:
#         return pd.DataFrame(columns=["ts","open","high","low","close","volume"])

#     ticks = ticks.copy()
#     if "timestamp" not in ticks.columns or "bid" not in ticks.columns or "ask" not in ticks.columns:
#         raise ValueError(f"Unexpected tick columns: {list(ticks.columns)}")

#     ticks["timestamp"] = pd.to_datetime(ticks["timestamp"], utc=True)
#     ticks = ticks.sort_values("timestamp").set_index("timestamp")
#     ticks["mid"] = (ticks["bid"] + ticks["ask"]) / 2.0

#     rule = {"1m": "1min", "5m": "5min", "15m": "15min"}[tf]
#     o = ticks["mid"].resample(rule).first()
#     h = ticks["mid"].resample(rule).max()
#     l = ticks["mid"].resample(rule).min()
#     c = ticks["mid"].resample(rule).last()
#     v = ticks["mid"].resample(rule).count()  # tick volume

#     df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()
#     df = df.reset_index().rename(columns={"timestamp": "ts"})
#     return df

# def _convert_tz(df: pd.DataFrame, tz: str) -> pd.DataFrame:
#     if df.empty:
#         return df
#     ts = pd.to_datetime(df["ts"], utc=True)
#     df["ts"] = ts.dt.tz_convert(tz)
#     return df

# def download_pair(symbol: str, start: str, end: str) -> pd.DataFrame:
#     """
#     Returns ticks DataFrame with ['timestamp','bid','ask'] (UTC tz-aware).
#     """
#     start_dt = pd.Timestamp(start, tz="UTC")
#     end_dt = pd.Timestamp(end, tz="UTC")
#     dl = DukaDL()
#     # The dukascopy client paginates internally; format="df" returns a DataFrame.
#     data = dl.download(symbol=symbol, from_date=start_dt, to_date=end_dt, format="df", verbose=True)
#     if data is None or len(data) == 0:
#         return pd.DataFrame(columns=["timestamp","bid","ask"])
#     # some versions return extra cols; keep only what we need
#     return data[["timestamp", "bid", "ask"]].dropna().reset_index(drop=True)

# def main():
#     ap = argparse.ArgumentParser(description="Backfill FX candles using Dukascopy (free).")
#     ap.add_argument("--out-dir", type=Path, required=True)
#     ap.add_argument("--symbols", type=str, default="EURUSD")
#     ap.add_argument("--start", type=str, required=True)   # e.g., 2020-01-01
#     ap.add_argument("--end", type=str, required=True)     # e.g., 2025-01-01
#     ap.add_argument("--timeframes", type=str, default="1m,5m,15m")
#     ap.add_argument("--tz", type=str, default="UTC", help="Output timezone for ts column (e.g., UTC or Asia/Kolkata)")
#     args = ap.parse_args()

#     out = args.out_dir
#     out.mkdir(parents=True, exist_ok=True)
#     syms = _parse_list(args.symbols)
#     tfs  = _parse_list(args.timeframes)

#     for sym in syms:
#         print(f"\n=== Downloading ticks: {sym} {args.start} → {args.end} ===")
#         ticks = download_pair(sym, args.start, args.end)
#         if ticks.empty:
#             print(f"[warn] no ticks for {sym} in range.")
#             continue
#         for tf in tfs:
#             if tf not in {"1m","5m","15m"}:
#                 print(f"[skip] unsupported timeframe: {tf}")
#                 continue
#             print(f"  → Resampling {tf}...")
#             df = _resample_ticks_to_ohlcv(ticks, tf)
#             df = _convert_tz(df, args.tz)
#             fp = out / f"{sym}_{tf}.csv"
#             df.to_csv(fp, index=False)
#             print(f"  ✓ Wrote {fp} rows={len(df)}")

# if __name__ == "__main__":
#     main()
