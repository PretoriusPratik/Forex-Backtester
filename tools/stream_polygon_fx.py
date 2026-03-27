# # file: tools/stream_polygon_fx.py
# """
# (OPTIONAL) Minimal realtime poller using Polygon.io Currencies aggregates.
# Requires: free account + POLYGON_API_KEY env var.
# Limits & coverage depend on their current free plan.

# It appends each completed 1-minute bar to ./data/<SYMBOL>_1m.csv if new.

# pip install requests pandas python-dotenv
# export POLYGON_API_KEY=your_key
# python tools/stream_polygon_fx.py --symbol EURUSD --out ./data/EURUSD_1m.csv
# """
# from __future__ import annotations
# import argparse, os, time
# from pathlib import Path
# import requests, pandas as pd

# BASE = "https://api.polygon.io/v2/aggs/ticker/C:{pair}/range/1/minute/{from}/{to}"

# def fetch_last_min(pair: str, api_key: str) -> pd.DataFrame:
#     # get last ~2 minutes to ensure we catch the latest closed bar
#     now = pd.Timestamp.utcnow().floor("min")
#     frm = (now - pd.Timedelta(minutes=3)).strftime("%Y-%m-%d")
#     to  = now.strftime("%Y-%m-%d")
#     url = BASE.format(pair=pair, from=frm, to=to)
#     r = requests.get(url, params={"apiKey": api_key, "adjusted": "true", "sort": "desc", "limit": 3}, timeout=15)
#     r.raise_for_status()
#     js = r.json()
#     results = js.get("results", [])
#     if not results:
#         return pd.DataFrame(columns=["ts","open","high","low","close","volume"])
#     df = pd.DataFrame(results)
#     # polygon fields: t (ms), o,h,l,c,v
#     df = df.rename(columns={"t":"ts","o":"open","h":"high","l":"low","c":"close","v":"volume"})
#     df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
#     df = df[["ts","open","high","low","close","volume"]].sort_values("ts")
#     return df

# def append_new(out: Path, newbars: pd.DataFrame) -> None:
#     if not out.exists():
#         newbars.to_csv(out, index=False); return
#     cur = pd.read_csv(out, parse_dates=["ts"])
#     merged = pd.concat([cur, newbars]).drop_duplicates(subset=["ts"]).sort_values("ts")
#     merged.to_csv(out, index=False)

# def main():
#     ap = argparse.ArgumentParser()
#     ap.add_argument("--symbol", type=str, required=True)  # e.g., EURUSD
#     ap.add_argument("--out", type=Path, required=True)
#     ap.add_argument("--sleep", type=int, default=30)
#     args = ap.parse_args()
#     key = os.environ.get("POLYGON_API_KEY")
#     if not key: raise SystemExit("Set POLYGON_API_KEY env var.")

#     pair = args.symbol.upper()
#     print(f"Polling Polygon 1m aggregates for {pair} → {args.out} (Ctrl+C to stop)")
#     try:
#         while True:
#             df = fetch_last_min(pair, key)
#             if not df.empty:
#                 append_new(args.out, df)
#                 print("Appended up to", df["ts"].max())
#             time.sleep(args.sleep)
#     except KeyboardInterrupt:
#         print("\nStopped.")

# if __name__ == "__main__":
#     main()
