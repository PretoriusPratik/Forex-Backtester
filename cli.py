# from __future__ import annotations
# import argparse
# from pathlib import Path
# import pandas as pd

# from pa_backtester.data import CSVFeed
# from pa_backtester.backtester import Backtester
# from pa_backtester.metrics import (
#     equity_metrics,
#     winrate_by_session,
#     winrate_by_news_bucket,
#     save_ledger_csv,
# )
# from strategies.price_action import PriceActionBreakout


# def _pct(x: float) -> str:
#     return f"{round(x*100, 2)}%"


# def main() -> None:
#     p = argparse.ArgumentParser(description="Price-Action FX Backtester (sessions + news).")
#     p.add_argument("--csv-root", type=Path, required=True)
#     p.add_argument("--symbol", type=str, required=True)             # e.g., EURUSD
#     p.add_argument("--timeframe", type=str, choices=["1m","15m","1h"], default="1m")
#     p.add_argument("--news-file", type=Path, required=True)         # e.g., ./data/news.csv
#     p.add_argument("--risk-perc", type=float, default=0.01)
#     p.add_argument("--rr", type=float, default=2.0)
#     p.add_argument("--lookback", type=int, default=20)              # minutes for breakout range
#     p.add_argument("--vol-pctl", type=float, default=0.8)           # [0..1] volume percentile filter
#     p.add_argument("--sessions", type=str, default="TOKYO,LONDON,NEWYORK")
#     p.add_argument("--news-blackout-pre", type=int, default=30)     # minutes before news
#     p.add_argument("--news-blackout-post", type=int, default=15)    # minutes after news
#     p.add_argument("--min-impact", type=str, choices=["low","medium","high"], default="medium")
#     p.add_argument("--out-ledger", type=Path, default=Path("./trade_ledger.csv"))
#     args = p.parse_args()

#     allowed_sessions = [s.strip().upper() for s in args.sessions.split(",") if s.strip()]

#     feed = CSVFeed(args.csv_root)
#     df = feed.history(args.symbol, args.timeframe, None, None)

#     # Strategy configured without indicators; uses only price/volume/sessions/news.
#     strat = PriceActionBreakout(
#         df=df,
#         symbol=args.symbol,
#         lookback=args.lookback,
#         rr=args.rr,
#         risk_perc=args.risk_perc,
#         vol_percentile=args.vol_pctl,
#         allowed_sessions=allowed_sessions,
#         news_csv=args.news_file,
#         news_blackout_pre_min=args.news_blackout_pre,
#         news_blackout_post_min=args.news_blackout_post,
#         min_impact=args.min_impact,
#     )

#     bt = Backtester(df, args.symbol, args.timeframe, strat)
#     trades = bt.run()

#     # Print core metrics
#     print(f"Total trades: {len(trades)}")
#     em = equity_metrics(trades)
#     print(em)

#     # Session breakdown
#     wr_sess = winrate_by_session(trades)
#     if not wr_sess.empty:
#         print("\nWin rate by session:")
#         print(wr_sess.applymap(_pct))

#     # News bucket breakdown
#     wr_news = winrate_by_news_bucket(trades)
#     if not wr_news.empty:
#         print("\nWin rate by news proximity:")
#         print(wr_news.applymap(_pct))

#     # Save ledger
#     save_ledger_csv(trades, args.out_ledger)
#     print(f"\nSaved trade ledger to: {args.out_ledger.resolve()}")


# if __name__ == "__main__":
#     main()

# file: cli.py
from __future__ import annotations
import argparse
from pathlib import Path
from pa_backtester.data import CSVFeed
from pa_backtester.backtester import Backtester
from pa_backtester.metrics import equity_metrics, winrate_by_session, winrate_by_news_bucket, save_ledger_csv
from strategies.price_action import PriceActionBreakout

def _pct(x: float) -> str: return f"{round(x*100, 2)}%"

def main() -> None:
    p = argparse.ArgumentParser(description="Price-Action FX Backtester (sessions + news; IST/UTC aware).")
    p.add_argument("--csv-root", type=Path, required=True)
    p.add_argument("--symbol", type=str, required=True)               # e.g., EURUSD
    p.add_argument("--timeframe", type=str, choices=["1m","15m","1h"], default="1m")
    p.add_argument("--news-file", type=Path, required=True)           # e.g., ./data/news.csv
    p.add_argument("--price-tz", type=str, default="UTC")             # e.g., Asia/Kolkata
    p.add_argument("--news-tz", type=str, default="UTC")              # e.g., Asia/Kolkata
    p.add_argument("--risk-perc", type=float, default=0.01)
    p.add_argument("--rr", type=float, default=2.0)
    p.add_argument("--lookback", type=int, default=20)
    p.add_argument("--vol-pctl", type=float, default=0.8)
    p.add_argument("--sessions", type=str, default="TOKYO,LONDON,NEWYORK")
    p.add_argument("--news-blackout-pre", type=int, default=30)
    p.add_argument("--news-blackout-post", type=int, default=15)
    p.add_argument("--min-impact", type=str, choices=["low","medium","high"], default="medium")
    p.add_argument("--out-ledger", type=Path, default=Path("./trade_ledger.csv"))
    args = p.parse_args()

    feed = CSVFeed(args.csv_root, input_tz=args.price_tz)
    df = feed.history(args.symbol, args.timeframe, None, None)
    allowed_sessions = [s.strip().upper() for s in args.sessions.split(",") if s.strip()]

    strat = PriceActionBreakout(
        df=df,
        symbol=args.symbol,
        lookback=args.lookback,
        rr=args.rr,
        risk_perc=args.risk_perc,
        vol_percentile=args.vol_pctl,
        allowed_sessions=allowed_sessions,
        news_csv=args.news_file,
        news_blackout_pre_min=args.news_blackout_pre,
        news_blackout_post_min=args.news_blackout_post,
        min_impact=args.min_impact,
        news_input_tz=args.news_tz,
    )
    bt = Backtester(df, args.symbol, args.timeframe, strat)
    trades = bt.run()

    print(f"Total trades: {len(trades)}")
    em = equity_metrics(trades); print(em)
    wr_sess = winrate_by_session(trades)
    if not wr_sess.empty:
        print("\nWin rate by session:"); print(wr_sess.applymap(_pct))
    wr_news = winrate_by_news_bucket(trades)
    if not wr_news.empty:
        print("\nWin rate by news proximity:"); print(wr_news.applymap(_pct))
    save_ledger_csv(trades, args.out_ledger)
    print(f"\nSaved trade ledger to: {args.out_ledger.resolve()}")

if __name__ == "__main__":
    main()
