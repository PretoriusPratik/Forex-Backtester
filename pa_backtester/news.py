# from __future__ import annotations
# from dataclasses import dataclass
# from typing import List, Tuple
# import pandas as pd

# @dataclass(frozen=True)
# class NewsEvent:
#     ts: pd.Timestamp
#     currency: str
#     impact: str
#     event: str

# _IMPACT_ORDER = {"low": 0, "medium": 1, "high": 2}

# def load_news(csv_path) -> pd.DataFrame:
#     """
#     CSV schema: ts, currency, impact, event
#     ts must be parseable datetime (UTC naive or timezone-aware).
#     """
#     df = pd.read_csv(csv_path)
#     df["ts"] = pd.to_datetime(df["ts"], utc=True)
#     df["currency"] = df["currency"].str.upper()
#     df["impact"] = df["impact"].str.lower()
#     for col in ["currency","impact","event"]:
#         if col not in df.columns:
#             raise ValueError(f"news.csv missing column: {col}")
#     return df.sort_values("ts").reset_index(drop=True)

# def is_news_blackout(ts: pd.Timestamp, pair: str, news_df: pd.DataFrame, pre_min: int, post_min: int, min_impact: str) -> Tuple[bool, str]:
#     """
#     Return (in_blackout, bucket). bucket in {"PRE","POST","NONE"} if an event is within windows.
#     Why: avoid entering around events for either currency in the pair at or above min_impact.
#     """
#     base, quote = pair[:3].upper(), pair[3:].upper()
#     th = _IMPACT_ORDER[min_impact]
#     # focus only relevant currencies and impact level
#     df = news_df[(news_df["currency"].isin([base, quote])) & (news_df["impact"].map(_IMPACT_ORDER) >= th)]
#     if df.empty:
#         return (False, "NONE")
#     # nearest event
#     dt = (df["ts"] - ts).dt.total_seconds() / 60.0
#     before = df[(dt <= 0) & (dt >= -pre_min)]
#     after = df[(dt >= 0) & (dt <= post_min)]
#     if not before.empty:
#         return (True, "PRE")
#     if not after.empty:
#         return (True, "POST")
#     return (False, "NONE")

# file: pa_backtester/news.py
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from .utils import ensure_series_utc

@dataclass(frozen=True)
class NewsEvent:
    ts: pd.Timestamp
    currency: str
    impact: str
    event: str

_IMPACT_ORDER = {"low": 0, "medium": 1, "high": 2}

def load_news(csv_path, input_tz: str = "UTC") -> pd.DataFrame:
    """
    CSV schema: ts, currency, impact, event
    ts may be tz-naive (assumed input_tz) or tz-aware strings; normalized to UTC.
    """
    df = pd.read_csv(csv_path)
    for col in ["ts","currency","impact","event"]:
        if col not in df.columns:
            raise ValueError(f"news.csv missing column: {col}")
    df["ts"] = ensure_series_utc(df["ts"], input_tz)
    df["currency"] = df["currency"].str.upper()
    df["impact"] = df["impact"].str.lower()
    return df.sort_values("ts").reset_index(drop=True)

def is_news_blackout(ts: pd.Timestamp, pair: str, news_df: pd.DataFrame, pre_min: int, post_min: int, min_impact: str):
    base, quote = pair[:3].upper(), pair[3:].upper()
    th = _IMPACT_ORDER[min_impact]
    df = news_df[(news_df["currency"].isin([base, quote])) & (news_df["impact"].map(_IMPACT_ORDER) >= th)]
    if df.empty: return (False, "NONE")
    dt = (df["ts"] - ts).dt.total_seconds() / 60.0
    before = df[(dt <= 0) & (dt >= -pre_min)]
    after  = df[(dt >= 0) & (dt <= post_min)]
    if not before.empty: return (True, "PRE")
    if not after.empty:  return (True, "POST")
    return (False, "NONE")
