# # from __future__ import annotations
# # from typing import Optional, List
# # import pandas as pd
# # from pa_backtester.strategy import Strategy, Context
# # from pa_backtester.types import Order, Side, OrderType, Bar
# # from pa_backtester.sessions import session_of
# # from pa_backtester.news import load_news, is_news_blackout

# # def _to_utc(ts) -> pd.Timestamp:
# #     t = pd.Timestamp(ts)
# #     return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

# # class PriceActionBreakout(Strategy):
# #     """
# #     Pure price/volume/session/news strategy:
# #     - Breaks above prior N-minute high → long; below prior N-minute low → short.
# #     - Trade only in allowed sessions (TOKYO/LONDON/NEWYORK).
# #     - Skip entering within news blackout windows for affected currencies.
# #     - Volume filter: bar volume >= percentile(volume, pctl) over rolling window.
# #     - Risk unit = entry_stop_distance from range; size by risk_perc of equity.
# #     """
# #     def __init__(
# #         self,
# #         df: pd.DataFrame,
# #         symbol: str,
# #         lookback: int = 20,
# #         rr: float = 2.0,
# #         risk_perc: float = 0.01,
# #         vol_percentile: float = 0.8,
# #         allowed_sessions: Optional[List[str]] = None,
# #         news_csv: Optional[str] = None,
# #         news_blackout_pre_min: int = 30,
# #         news_blackout_post_min: int = 15,
# #         min_impact: str = "medium",
# #     ):
# #         self.df = df.copy()
# #         self.symbol = symbol.upper()
# #         self.lookback = int(lookback)
# #         self.rr = float(rr)
# #         self.risk_perc = float(risk_perc)
# #         self.vol_pctl = float(vol_percentile)
# #         self.allowed_sessions = set((allowed_sessions or ["TOKYO","LONDON","NEWYORK"]))
# #         self.news_csv = news_csv
# #         self.news_blackout_pre_min = int(news_blackout_pre_min)
# #         self.news_blackout_post_min = int(news_blackout_post_min)
# #         self.min_impact = min_impact

# #         self.news_df = load_news(news_csv) if news_csv else pd.DataFrame(columns=["ts","currency","impact","event"])

# #     def init(self, ctx: Context) -> None:
# #         self.df["ts"] = self.df["ts"].apply(_to_utc)
# #         self.df["session"] = self.df["ts"].apply(session_of)
# #         self.df["hi_lb"] = self.df["high"].rolling(self.lookback, min_periods=self.lookback).max().shift(1)
# #         self.df["lo_lb"] = self.df["low"].rolling(self.lookback, min_periods=self.lookback).min().shift(1)
# #         self.df["vol_thresh"] = self.df["volume"].rolling(self.lookback, min_periods=self.lookback).quantile(self.vol_pctl).shift(1)

# #     def _eligible(self, row: pd.Series) -> bool:
# #         if row["session"] not in self.allowed_sessions:
# #             return False
# #         if pd.isna(row["hi_lb"]) or pd.isna(row["lo_lb"]) or pd.isna(row["vol_thresh"]):
# #             return False
# #         return True

# #     def on_bar(self, bar: Bar, ctx: Context) -> Optional[Order]:
# #         ts = _to_utc(bar.ts)
# #         row = self.df.loc[self.df["ts"] == ts]
# #         if row.empty:
# #             return None
# #         r = row.iloc[0]
# #         if not self._eligible(r):
# #             return None

# #         in_blackout, bucket = is_news_blackout(ts, self.symbol, self.news_df, self.news_blackout_pre_min, self.news_blackout_post_min, self.min_impact)
# #         if in_blackout:
# #             return None

# #         vol_ok = (r["volume"] >= r["vol_thresh"])
# #         long_sig = (r["close"] > r["hi_lb"]) and vol_ok
# #         short_sig = (r["close"] < r["lo_lb"]) and vol_ok

# #         if not (long_sig or short_sig):
# #             return None

# #         # Risk from breakout distance; why: ties risk to current structure, indicator-free
# #         if long_sig:
# #             risk_unit = max(1e-6, float(r["close"] - r["lo_lb"]))
# #             side = Side.LONG
# #         else:
# #             risk_unit = max(1e-6, float(r["hi_lb"] - r["close"]))
# #             side = Side.SHORT

# #         acct_risk = ctx.equity * self.risk_perc
# #         qty = acct_risk / risk_unit
# #         if qty <= 0:
# #             return None

# #         ctx.state["risk_unit"] = risk_unit
# #         ctx.state["rr"] = self.rr
# #         ctx.state["news_bucket"] = bucket

# #         return Order(id=0, symbol=self.symbol, side=side, qty=qty, type=OrderType.MARKET)

# # file: strategies/price_action.py
# from __future__ import annotations
# from typing import Optional, List
# import pandas as pd
# from pa_backtester.strategy import Strategy, Context
# from pa_backtester.types import Order, Side, OrderType, Bar
# from pa_backtester.sessions import session_of
# from pa_backtester.news import load_news, is_news_blackout
# from pa_backtester.utils import to_utc  # <-- use shared util

# class PriceActionBreakout(Strategy):
#     """
#     Pure price/volume/session/news strategy:
#     - Breakout of prior N-minute range; volume percentile filter; session gate; news blackout.
#     """
#     def __init__(
#         self,
#         df: pd.DataFrame,
#         symbol: str,
#         lookback: int = 20,
#         rr: float = 2.0,
#         risk_perc: float = 0.01,
#         vol_percentile: float = 0.8,
#         allowed_sessions: Optional[List[str]] = None,
#         news_csv: Optional[str] = None,
#         news_blackout_pre_min: int = 30,
#         news_blackout_post_min: int = 15,
#         min_impact: str = "medium",
#     ):
#         self.df = df.copy()
#         self.symbol = symbol.upper()
#         self.lookback = int(lookback)
#         self.rr = float(rr)
#         self.risk_perc = float(risk_perc)
#         self.vol_pctl = float(vol_percentile)
#         self.allowed_sessions = set((allowed_sessions or ["TOKYO","LONDON","NEWYORK"]))
#         self.news_csv = news_csv
#         self.news_blackout_pre_min = int(news_blackout_pre_min)
#         self.news_blackout_post_min = int(news_blackout_post_min)
#         self.min_impact = min_impact

#         self.news_df = load_news(news_csv) if news_csv else pd.DataFrame(columns=["ts","currency","impact","event"])

#     def init(self, ctx: Context) -> None:
#         self.df["ts"] = self.df["ts"].apply(to_utc)
#         self.df["session"] = self.df["ts"].apply(session_of)
#         self.df["hi_lb"] = self.df["high"].rolling(self.lookback, min_periods=self.lookback).max().shift(1)
#         self.df["lo_lb"] = self.df["low"].rolling(self.lookback, min_periods=self.lookback).min().shift(1)
#         self.df["vol_thresh"] = self.df["volume"].rolling(self.lookback, min_periods=self.lookback).quantile(self.vol_pctl).shift(1)

#     def _eligible(self, row: pd.Series) -> bool:
#         if row["session"] not in self.allowed_sessions:
#             return False
#         if pd.isna(row["hi_lb"]) or pd.isna(row["lo_lb"]) or pd.isna(row["vol_thresh"]):
#             return False
#         return True

#     def on_bar(self, bar: Bar, ctx: Context):
#         ts = to_utc(bar.ts)
#         row = self.df.loc[self.df["ts"] == ts]
#         if row.empty:
#             return None
#         r = row.iloc[0]
#         if not self._eligible(r):
#             return None

#         in_blackout, bucket = is_news_blackout(ts, self.symbol, self.news_df, self.news_blackout_pre_min, self.news_blackout_post_min, self.min_impact)
#         if in_blackout:
#             return None

#         vol_ok = (r["volume"] >= r["vol_thresh"])
#         long_sig = (r["close"] > r["hi_lb"]) and vol_ok
#         short_sig = (r["close"] < r["lo_lb"]) and vol_ok

#         if not (long_sig or short_sig):
#             return None

#         if long_sig:
#             risk_unit = max(1e-6, float(r["close"] - r["lo_lb"]))
#             side = Side.LONG
#         else:
#             risk_unit = max(1e-6, float(r["hi_lb"] - r["close"]))
#             side = Side.SHORT

#         acct_risk = ctx.equity * self.risk_perc
#         qty = acct_risk / risk_unit
#         if qty <= 0:
#             return None

#         ctx.state["risk_unit"] = risk_unit
#         ctx.state["rr"] = self.rr
#         ctx.state["news_bucket"] = bucket

#         return Order(id=0, symbol=self.symbol, side=side, qty=qty, type=OrderType.MARKET)

# file: strategies/price_action.py
from __future__ import annotations
from typing import Optional, List
import pandas as pd
from pa_backtester.strategy import Strategy, Context
from pa_backtester.types import Order, Side, OrderType, Bar
from pa_backtester.sessions import session_of
from pa_backtester.news import load_news, is_news_blackout
from pa_backtester.utils import to_utc

class PriceActionBreakout(Strategy):
    """
    Pure price/volume/session/news strategy (indicator-free):
    - Breakout of prior N-minute range with volume percentile filter.
    - Gate by allowed sessions (TOKYO/LONDON/NEWYORK).
    - Skip entries in news blackout windows for affected currencies.
    - Risk unit from breakout distance; position sized by risk_perc of equity.
    """
    def __init__(
        self,
        df: pd.DataFrame,
        symbol: str,
        lookback: int = 20,
        rr: float = 2.0,
        risk_perc: float = 0.01,
        vol_percentile: float = 0.8,
        allowed_sessions: Optional[List[str]] = None,
        news_csv: Optional[str] = None,
        news_blackout_pre_min: int = 30,
        news_blackout_post_min: int = 15,
        min_impact: str = "medium",
        # <-- this is the parameter your CLI passes
        news_input_tz: str = "UTC",
    ):
        self.df = df.copy()
        self.symbol = symbol.upper()
        self.lookback = int(lookback)
        self.rr = float(rr)
        self.risk_perc = float(risk_perc)
        self.vol_pctl = float(vol_percentile)
        self.allowed_sessions = set((allowed_sessions or ["TOKYO","LONDON","NEWYORK"]))
        self.news_csv = news_csv
        self.news_blackout_pre_min = int(news_blackout_pre_min)
        self.news_blackout_post_min = int(news_blackout_post_min)
        self.min_impact = min_impact

        # Load news in the provided input timezone (e.g., Asia/Kolkata), normalize to UTC inside loader.
        self.news_df = load_news(news_csv, news_input_tz) if news_csv else pd.DataFrame(columns=["ts","currency","impact","event"])

    def init(self, ctx: Context) -> None:
        self.df["ts"] = self.df["ts"].apply(to_utc)
        self.df["session"] = self.df["ts"].apply(session_of)
        self.df["hi_lb"] = self.df["high"].rolling(self.lookback, min_periods=self.lookback).max().shift(1)
        self.df["lo_lb"] = self.df["low"].rolling(self.lookback, min_periods=self.lookback).min().shift(1)
        self.df["vol_thresh"] = self.df["volume"].rolling(self.lookback, min_periods=self.lookback).quantile(self.vol_pctl).shift(1)

    def _eligible(self, row: pd.Series) -> bool:
        if row["session"] not in self.allowed_sessions:
            return False
        if pd.isna(row["hi_lb"]) or pd.isna(row["lo_lb"]) or pd.isna(row["vol_thresh"]):
            return False
        return True

    def on_bar(self, bar: Bar, ctx: Context):
        ts = to_utc(bar.ts)
        row = self.df.loc[self.df["ts"] == ts]
        if row.empty:
            return None
        r = row.iloc[0]
        if not self._eligible(r):
            return None

        in_blackout, bucket = is_news_blackout(
            ts, self.symbol, self.news_df,
            self.news_blackout_pre_min, self.news_blackout_post_min, self.min_impact
        )
        if in_blackout:
            return None

        vol_ok = (r["volume"] >= r["vol_thresh"])
        long_sig  = (r["close"] > r["hi_lb"]) and vol_ok
        short_sig = (r["close"] < r["lo_lb"]) and vol_ok
        if not (long_sig or short_sig):
            return None

        if long_sig:
            risk_unit = max(1e-6, float(r["close"] - r["lo_lb"]))
            side = Side.LONG
        else:
            risk_unit = max(1e-6, float(r["hi_lb"] - r["close"]))
            side = Side.SHORT

        acct_risk = ctx.equity * self.risk_perc
        qty = acct_risk / risk_unit
        if qty <= 0:
            return None

        # Store planned parameters for the backtester to create OCO exits and annotate trades
        ctx.state["risk_unit"] = risk_unit
        ctx.state["rr"] = self.rr
        ctx.state["news_bucket"] = bucket

        return Order(id=0, symbol=self.symbol, side=side, qty=qty, type=OrderType.MARKET)
