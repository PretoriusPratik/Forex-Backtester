# from __future__ import annotations
# from pathlib import Path
# import pandas as pd
# from typing import Iterator, Optional
# from .types import Bar

# class DataFeed:
#     def stream(self, symbol: str, timeframe: str) -> Iterator[Bar]:
#         raise NotImplementedError

#     def history(self, symbol: str, timeframe: str, start: Optional[pd.Timestamp], end: Optional[pd.Timestamp]) -> pd.DataFrame:
#         raise NotImplementedError

# class CSVFeed(DataFeed):
#     """CSV with columns: ts, open, high, low, close, volume; ts naive UTC or ISO with tz."""
#     def __init__(self, root: Path):
#         self.root = Path(root)

#     def _load_df(self, symbol: str, tf: str) -> pd.DataFrame:
#         fp = self.root / f"{symbol}_{tf}.csv"
#         if not fp.exists():
#             raise FileNotFoundError(fp)
#         df = pd.read_csv(fp)
#         df["ts"] = pd.to_datetime(df["ts"], utc=True)
#         df = df.sort_values("ts").reset_index(drop=True)
#         required = {"ts","open","high","low","close","volume"}
#         missing = required - set(df.columns)
#         if missing:
#             raise ValueError(f"Missing columns: {missing}")
#         return df

#     def stream(self, symbol: str, timeframe: str):
#         df = self._load_df(symbol, timeframe)
#         for r in df.itertuples(index=False):
#             yield Bar(r.ts.to_pydatetime(), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume), timeframe)

#     def history(self, symbol: str, timeframe: str, start: Optional[pd.Timestamp], end: Optional[pd.Timestamp]) -> pd.DataFrame:
#         df = self._load_df(symbol, timeframe)
#         if start is not None:
#             df = df[df["ts"] >= pd.Timestamp(start, tz="UTC")]
#         if end is not None:
#             df = df[df["ts"] <= pd.Timestamp(end, tz="UTC")]
#         return df.reset_index(drop=True)

# file: pa_backtester/data.py
from __future__ import annotations
from pathlib import Path
import pandas as pd
from typing import Iterator, Optional
from .types import Bar
from .utils import ensure_series_utc

class DataFeed:
    def stream(self, symbol: str, timeframe: str): raise NotImplementedError
    def history(self, symbol: str, timeframe: str, start: Optional[pd.Timestamp], end: Optional[pd.Timestamp]) -> pd.DataFrame: raise NotImplementedError

class CSVFeed(DataFeed):
    """
    CSV columns: ts, open, high, low, close, volume.
    Supports tz-aware strings (e.g., +05:30) or tz-naive timestamps with input_tz.
    """
    def __init__(self, root: Path, input_tz: str = "UTC"):
        self.root = Path(root)
        self.input_tz = input_tz

    def _load_df(self, symbol: str, tf: str) -> pd.DataFrame:
        fp = self.root / f"{symbol}_{tf}.csv"
        if not fp.exists(): raise FileNotFoundError(fp)
        df = pd.read_csv(fp)
        req = {"ts","open","high","low","close","volume"}
        miss = req - set(df.columns)
        if miss: raise ValueError(f"Missing columns: {miss}")
        df["ts"] = ensure_series_utc(df["ts"], self.input_tz)
        df = df.sort_values("ts").reset_index(drop=True)
        return df

    def stream(self, symbol: str, timeframe: str):
        df = self._load_df(symbol, timeframe)
        for r in df.itertuples(index=False):
            yield Bar(r.ts.to_pydatetime(), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume), timeframe)

    def history(self, symbol: str, timeframe: str, start: Optional[pd.Timestamp], end: Optional[pd.Timestamp]) -> pd.DataFrame:
        df = self._load_df(symbol, timeframe)
        if start is not None: df = df[df["ts"] >= pd.Timestamp(start, tz="UTC")]
        if end is not None:   df = df[df["ts"] <= pd.Timestamp(end, tz="UTC")]
        return df.reset_index(drop=True)
