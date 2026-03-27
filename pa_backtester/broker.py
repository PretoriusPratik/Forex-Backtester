from __future__ import annotations
from typing import Dict, List, Optional
from dataclasses import dataclass
from .types import Order, OrderType, Fill, Side, Bar

@dataclass
class _Position:
    qty: float = 0.0   # + long, - short
    avg: float = 0.0

class BrokerSim:
    """Bar-based fills, OCO exits, signed netting, simple slippage & fees."""
    def __init__(self, starting_cash: float = 100_000.0, fee_perc: float = 0.0003, slippage_bps: float = 0.5):
        self.cash = starting_cash
        self.equity = starting_cash
        self.positions: Dict[str, _Position] = {}
        self.open_orders: Dict[int, Order] = {}
        self._next_order_id = 1
        self.fee_perc = fee_perc
        self.slippage_bps = slippage_bps

    def place(self, order: Order) -> int:
        order.id = self._next_order_id
        self._next_order_id += 1
        self.open_orders[order.id] = order
        return order.id

    def cancel(self, order_id: int) -> None:
        self.open_orders.pop(order_id, None)

    def _slip(self, price: float, side: Side) -> float:
        adj = price * (self.slippage_bps / 10_000.0)
        return price + (adj if side == Side.LONG else -adj)

    def _maybe_fill_price(self, o: Order, bar: Bar) -> Optional[float]:
        if o.type == OrderType.MARKET:
            return self._slip(bar.open, o.side)
        if o.type == OrderType.LIMIT:
            if o.side == Side.LONG and o.limit_price is not None and bar.low <= o.limit_price:
                return self._slip(o.limit_price, o.side)
            if o.side == Side.SHORT and o.limit_price is not None and bar.high >= o.limit_price:
                return self._slip(o.limit_price, o.side)
        if o.type == OrderType.STOP:
            if o.side == Side.LONG and o.stop_price is not None and bar.high >= o.stop_price:
                return self._slip(o.stop_price, o.side)
            if o.side == Side.SHORT and o.stop_price is not None and bar.low <= o.stop_price:
                return self._slip(o.stop_price, o.side)
        return None

    def _apply_fill(self, symbol: str, side: Side, price: float, qty: float, fee: float) -> None:
        pos = self.positions.setdefault(symbol, _Position(0.0, 0.0))
        signed = qty if side == Side.LONG else -qty
        self.cash -= price * signed
        new_qty = pos.qty + signed
        if pos.qty == 0 or (pos.qty > 0 and signed > 0) or (pos.qty < 0 and signed < 0):
            pos.avg = (pos.avg * abs(pos.qty) + price * abs(signed)) / max(1e-12, abs(new_qty))
            pos.qty = new_qty
        else:
            if abs(signed) <= abs(pos.qty):
                pos.qty = new_qty
                if pos.qty == 0:
                    pos.avg = 0.0
            else:
                remainder = signed + (-pos.qty)
                pos.qty = remainder
                pos.avg = price
        self.cash -= fee

    def on_bar(self, bar: Bar) -> List[Fill]:
        fills: List[Fill] = []
        to_remove = []
        for oid, o in list(self.open_orders.items()):
            price = self._maybe_fill_price(o, bar)
            if price is None:
                continue
            fee = abs(price * o.qty) * self.fee_perc
            fills.append(Fill(order_id=oid, ts=bar.ts, price=price, qty=o.qty, fee=fee))
            self._apply_fill(o.symbol, o.side, price, o.qty, fee)
            to_remove.append(oid)
        for oid in to_remove:
            self.open_orders.pop(oid, None)

        # mark-to-market equity on close
        mtm = 0.0
        for sym, pos in self.positions.items():
            mtm += pos.qty * bar.close
        self.equity = self.cash + mtm
        return fills
