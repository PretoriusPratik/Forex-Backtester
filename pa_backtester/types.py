from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Optional, Literal, Dict

class Side(Enum):
    LONG = auto()
    SHORT = auto()

class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()

@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: Literal["1m", "15m", "1h"]

@dataclass
class Order:
    id: int
    symbol: str
    side: Side
    qty: float
    type: OrderType
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: Literal["IOC", "FOK", "GTC"] = "GTC"

@dataclass
class Fill:
    order_id: int
    ts: datetime
    price: float
    qty: float
    fee: float

@dataclass
class Trade:
    symbol: str
    side: Side
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    qty: float
    fee_entry: float
    fee_exit: float
    stop_price: Optional[float]
    target_price: Optional[float]
    timeframe: str
    session: str
    news_bucket: str
    rr_planned: Optional[float]
    pnl: float
    pnl_r: Optional[float]
    meta: Dict[str, str]
