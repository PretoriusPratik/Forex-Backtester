from __future__ import annotations
import pandas as pd
from typing import List
from .types import Trade

def _df(trades: List[Trade]) -> pd.DataFrame:
    return pd.DataFrame([t.__dict__ for t in trades])

def equity_metrics(trades: List[Trade]) -> dict:
    df = _df(trades)
    if df.empty:
        return {"winrate": 0.0, "expectancy": 0.0, "profit_factor": 0.0}
    df["win"] = (df["pnl"] > 0).astype(int)
    gross_win = df.loc[df["pnl"] > 0, "pnl"].sum()
    gross_loss = -df.loc[df["pnl"] < 0, "pnl"].sum()
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    exp = df["pnl"].mean()
    wr = df["win"].mean()
    return {"winrate": float(wr), "expectancy": float(exp), "profit_factor": float(pf)}

def winrate_by_session(trades: List[Trade]) -> pd.DataFrame:
    df = _df(trades)
    if df.empty:
        return pd.DataFrame()
    df["win"] = (df["pnl"] > 0).astype(int)
    out = df.groupby("session", observed=False)["win"].mean().rename("winrate").to_frame()
    for s in ["TOKYO","LONDON","NEWYORK","OTHER"]:
        if s not in out.index:
            out.loc[s] = 0.0
    return out.loc[["TOKYO","LONDON","NEWYORK","OTHER"]]

def winrate_by_news_bucket(trades: List[Trade]) -> pd.DataFrame:
    df = _df(trades)
    if df.empty:
        return pd.DataFrame()
    df["win"] = (df["pnl"] > 0).astype(int)
    out = df.groupby("news_bucket", observed=False)["win"].mean().rename("winrate").to_frame()
    for b in ["PRE","POST","NONE"]:
        if b not in out.index:
            out.loc[b] = 0.0
    return out.loc[["PRE","POST","NONE"]]

def save_ledger_csv(trades: List[Trade], path) -> None:
    df = _df(trades)
    if df.empty:
        pd.DataFrame(columns=[
            "entry_ts","exit_ts","side","entry_price","exit_price","qty","pnl","pnl_r","session","news_bucket","rr_planned","stop_price","target_price"
        ]).to_csv(path, index=False)
        return
    cols = ["entry_ts","exit_ts","side","entry_price","exit_price","qty","pnl","pnl_r","session","news_bucket","rr_planned","stop_price","target_price"]
    out = df[cols].copy()
    out.to_csv(path, index=False)
