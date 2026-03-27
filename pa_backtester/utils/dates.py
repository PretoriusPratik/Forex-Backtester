# # file: pa_backtester/utils/dates.py
# from __future__ import annotations
# import pandas as pd

# def to_utc(ts) -> pd.Timestamp:
#     """Return a UTC-aware Timestamp; localize if naive, convert if aware."""
#     t = pd.Timestamp(ts)
#     return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

# file: pa_backtester/utils/dates.py
from __future__ import annotations
import pandas as pd

def to_utc(ts) -> pd.Timestamp:
    """Return UTC-aware Timestamp; localize if naive, convert if tz-aware."""
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

def ensure_series_utc(s: pd.Series, input_tz: str) -> pd.Series:
    """
    Parse a 'ts' series into UTC:
    - If values are tz-naive → localize to input_tz, then convert to UTC.
    - If tz-aware → convert to UTC.
    """
    ts = pd.to_datetime(s, errors="coerce", utc=False)
    if getattr(ts.dt, "tz", None) is None:
        ts = ts.dt.tz_localize(input_tz)
    return ts.dt.tz_convert("UTC")
