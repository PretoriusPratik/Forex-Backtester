from __future__ import annotations
from typing import Literal
import pandas as pd

Session = Literal["TOKYO","LONDON","NEWYORK","OTHER"]

def session_of(ts: pd.Timestamp) -> Session:
    """
    Map UTC hour to major sessions (simple fixed windows).
    Why: robust & deterministic for backtests; ignores DST complexities for speed.
    TOKYO:   23:00–08:00 UTC
    LONDON:  07:00–16:00 UTC
    NEWYORK: 12:00–21:00 UTC
    Overlaps will belong to the first matching in order TOKYO -> LONDON -> NEWYORK.
    """
    h = ts.hour
    if (h >= 23) or (h <= 8):
        return "TOKYO"
    if 7 <= h <= 16:
        return "LONDON"
    if 12 <= h <= 21:
        return "NEWYORK"
    return "OTHER"
