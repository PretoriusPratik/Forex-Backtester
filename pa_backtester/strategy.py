from __future__ import annotations
from typing import Optional, Dict
from abc import ABC, abstractmethod
from .types import Bar, Side, Order, OrderType

class Context:
    def __init__(self, symbol: str, timeframe: str, equity: float):
        self.symbol = symbol
        self.timeframe = timeframe
        self.equity = equity
        self.state: Dict[str, float] = {}

class Strategy(ABC):
    @abstractmethod
    def init(self, ctx: Context) -> None: ...
    @abstractmethod
    def on_bar(self, bar: Bar, ctx: Context) -> Optional[Order]: ...
