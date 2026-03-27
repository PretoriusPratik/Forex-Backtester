# # from __future__ import annotations
# # from typing import List, Optional, Dict
# # import pandas as pd
# # from .types import Bar, Trade, Side, OrderType, Order
# # from .strategy import Strategy, Context
# # from .broker import BrokerSim
# # from .sessions import session_of
# # from .news import load_news, is_news_blackout

# # class Backtester:
# #     """Event loop with news/session gating and OCO exits recording."""
# #     def __init__(self, data_df: pd.DataFrame, symbol: str, timeframe: str, strategy: Strategy, broker: Optional[BrokerSim] = None):
# #         self.df = data_df.copy()
# #         self.symbol = symbol
# #         self.timeframe = timeframe
# #         self.strategy = strategy
# #         self.broker = broker or BrokerSim()
# #         self.trades: List[Trade] = []

# #         self._open: Optional[dict] = None
# #         self._pending_entry_id: Optional[int] = None
# #         self._oco: Dict[int, int] = {}
# #         self._id_to_order: Dict[int, Order] = {}

# #     def _place(self, o: Order) -> int:
# #         oid = self.broker.place(o)
# #         self._id_to_order[oid] = o
# #         return oid

# #     def _place_oco_exits(self, side: Side, qty: float, entry_price: float, risk_unit: float, rr: float) -> None:
# #         if side == Side.LONG:
# #             stop_px = entry_price - risk_unit
# #             tgt_px  = entry_price + rr * risk_unit
# #             stop_order = Order(id=0, symbol=self.symbol, side=Side.SHORT, qty=qty, type=OrderType.STOP, stop_price=stop_px)
# #             tgt_order  = Order(id=0, symbol=self.symbol, side=Side.SHORT, qty=qty, type=OrderType.LIMIT, limit_price=tgt_px)
# #         else:
# #             stop_px = entry_price + risk_unit
# #             tgt_px  = entry_price - rr * risk_unit
# #             stop_order = Order(id=0, symbol=self.symbol, side=Side.LONG, qty=qty, type=OrderType.STOP, stop_price=stop_px)
# #             tgt_order  = Order(id=0, symbol=self.symbol, side=Side.LONG, qty=qty, type=OrderType.LIMIT, limit_price=tgt_px)
# #         sid1 = self._place(stop_order)
# #         sid2 = self._place(tgt_order)
# #         self._oco[sid1] = sid2
# #         self._oco[sid2] = sid1
# #         self._open.update({"stop_price": stop_px, "target_price": tgt_px})

# #     def run(self) -> List[Trade]:
# #         ctx = Context(self.symbol, self.timeframe, self.broker.equity)
# #         self.strategy.init(ctx)

# #         # strategy exposes news_df if needed
# #         if hasattr(self.strategy, "news_df"):
# #             self.news_df = self.strategy.news_df
# #         else:
# #             self.news_df = None

# #         last_bar: Optional[Bar] = None

# #         for row in self.df.itertuples(index=False):
# #             bar = Bar(row.ts.to_pydatetime(), float(row.open), float(row.high), float(row.low), float(row.close), float(row.volume), self.timeframe)
# #             last_bar = bar

# #             ctx.equity = self.broker.equity
# #             ctx.state["in_position"] = self._open is not None

# #             if self._open is None:
# #                 order = self.strategy.on_bar(bar, ctx)
# #                 if order is not None:
# #                     self._pending_entry_id = self._place(order)

# #             fills = self.broker.on_bar(bar)

# #             for f in fills:
# #                 # entry fill
# #                 if self._pending_entry_id == f.order_id and self._open is None:
# #                     o = self._id_to_order[f.order_id]
# #                     risk_unit = float(ctx.state.get("risk_unit", 0.0))
# #                     rr = float(ctx.state.get("rr", 2.0))
# #                     sess = session_of(pd.Timestamp(f.ts, tz="UTC"))
# #                     news_bucket = ctx.state.get("news_bucket", "NONE")

# #                     self._open = dict(
# #                         symbol=self.symbol,
# #                         side=o.side,
# #                         entry_ts=f.ts,
# #                         entry_price=f.price,
# #                         qty=f.qty,
# #                         fee_entry=f.fee,
# #                         timeframe=self.timeframe,
# #                         session=sess,
# #                         news_bucket=news_bucket,
# #                         rr_planned=rr,
# #                         risk_unit=risk_unit,
# #                         meta={},
# #                     )
# #                     self._place_oco_exits(o.side, f.qty, f.price, risk_unit, rr)
# #                     self._pending_entry_id = None
# #                     continue

# #                 # exit fill via OCO
# #                 if f.order_id in self._oco and self._open is not None:
# #                     sibling = self._oco.pop(f.order_id)
# #                     self._oco.pop(sibling, None)
# #                     self.broker.cancel(sibling)

# #                     t = self._open
# #                     direction = 1.0 if t["side"] == Side.LONG else -1.0
# #                     gross = direction * (f.price - t["entry_price"]) * t["qty"]
# #                     pnl_r = gross / max(1e-9, t["risk_unit"] * t["qty"])

# #                     tr = Trade(
# #                         symbol=t["symbol"],
# #                         side=t["side"],
# #                         entry_ts=t["entry_ts"],
# #                         exit_ts=f.ts,
# #                         entry_price=t["entry_price"],
# #                         exit_price=f.price,
# #                         qty=t["qty"],
# #                         fee_entry=t["fee_entry"],
# #                         fee_exit=f.fee,
# #                         stop_price=self._open.get("stop_price"),
# #                         target_price=self._open.get("target_price"),
# #                         timeframe=t["timeframe"],
# #                         session=t["session"],
# #                         news_bucket=t["news_bucket"],
# #                         rr_planned=t["rr_planned"],
# #                         pnl=gross - t["fee_entry"] - f.fee,
# #                         pnl_r=pnl_r,
# #                         meta=t["meta"],
# #                     )
# #                     self.trades.append(tr)
# #                     self._open = None

# #             for f in fills:
# #                 self._id_to_order.pop(f.order_id, None)

# #         # flatten if still open
# #         if self._open is not None and last_bar is not None:
# #             t = self._open
# #             exit_price = last_bar.close
# #             fee_exit = abs(exit_price * t["qty"]) * self.broker.fee_perc
# #             direction = 1.0 if t["side"] == Side.LONG else -1.0
# #             gross = direction * (exit_price - t["entry_price"]) * t["qty"]
# #             pnl_r = gross / max(1e-9, t["risk_unit"] * t["qty"])
# #             self.trades.append(Trade(
# #                 symbol=t["symbol"], side=t["side"],
# #                 entry_ts=t["entry_ts"], exit_ts=last_bar.ts,
# #                 entry_price=t["entry_price"], exit_price=exit_price,
# #                 qty=t["qty"], fee_entry=t["fee_entry"], fee_exit=fee_exit,
# #                 stop_price=self._open.get("stop_price"), target_price=self._open.get("target_price"),
# #                 timeframe=t["timeframe"], session=t["session"], news_bucket=t["news_bucket"],
# #                 rr_planned=t["rr_planned"], pnl=gross - t["fee_entry"] - fee_exit, pnl_r=pnl_r, meta=t["meta"]
# #             ))
# #             self._open = None

# #         return self.trades
# # file: pa_backtester/backtester.py
# from __future__ import annotations
# from typing import List, Optional, Dict
# import pandas as pd
# from .types import Bar, Trade, Side, OrderType, Order
# from .strategy import Strategy, Context
# from .broker import BrokerSim
# from .sessions import session_of
# from .news import load_news, is_news_blackout
# from .utils.dates import to_utc  # <-- added

# class Backtester:
#     """Event loop with news/session gating and OCO exits recording."""
#     def __init__(self, data_df: pd.DataFrame, symbol: str, timeframe: str, strategy: Strategy, broker: Optional[BrokerSim] = None):
#         self.df = data_df.copy()
#         self.symbol = symbol
#         self.timeframe = timeframe
#         self.strategy = strategy
#         self.broker = broker or BrokerSim()
#         self.trades: List[Trade] = []

#         self._open: Optional[dict] = None
#         self._pending_entry_id: Optional[int] = None
#         self._oco: Dict[int, int] = {}
#         self._id_to_order: Dict[int, Order] = {}

#     def _place(self, o: Order) -> int:
#         oid = self.broker.place(o)
#         self._id_to_order[oid] = o
#         return oid

#     def _place_oco_exits(self, side: Side, qty: float, entry_price: float, risk_unit: float, rr: float) -> None:
#         if side == Side.LONG:
#             stop_px = entry_price - risk_unit
#             tgt_px  = entry_price + rr * risk_unit
#             stop_order = Order(id=0, symbol=self.symbol, side=Side.SHORT, qty=qty, type=OrderType.STOP, stop_price=stop_px)
#             tgt_order  = Order(id=0, symbol=self.symbol, side=Side.SHORT, qty=qty, type=OrderType.LIMIT, limit_price=tgt_px)
#         else:
#             stop_px = entry_price + risk_unit
#             tgt_px  = entry_price - rr * risk_unit
#             stop_order = Order(id=0, symbol=self.symbol, side=Side.LONG, qty=qty, type=OrderType.STOP, stop_price=stop_px)
#             tgt_order  = Order(id=0, symbol=self.symbol, side=Side.LONG, qty=qty, type=OrderType.LIMIT, limit_price=tgt_px)
#         sid1 = self._place(stop_order)
#         sid2 = self._place(tgt_order)
#         self._oco[sid1] = sid2
#         self._oco[sid2] = sid1
#         self._open.update({"stop_price": stop_px, "target_price": tgt_px})

#     def run(self) -> List[Trade]:
#         ctx = Context(self.symbol, self.timeframe, self.broker.equity)
#         self.strategy.init(ctx)

#         if hasattr(self.strategy, "news_df"):
#             self.news_df = self.strategy.news_df
#         else:
#             self.news_df = None

#         last_bar: Optional[Bar] = None

#         for row in self.df.itertuples(index=False):
#             bar = Bar(row.ts.to_pydatetime(), float(row.open), float(row.high), float(row.low), float(row.close), float(row.volume), self.timeframe)
#             last_bar = bar

#             ctx.equity = self.broker.equity
#             ctx.state["in_position"] = self._open is not None

#             if self._open is None:
#                 order = self.strategy.on_bar(bar, ctx)
#                 if order is not None:
#                     self._pending_entry_id = self._place(order)

#             fills = self.broker.on_bar(bar)

#             for f in fills:
#                 # entry fill
#                 if self._pending_entry_id == f.order_id and self._open is None:
#                     o = self._id_to_order[f.order_id]
#                     risk_unit = float(ctx.state.get("risk_unit", 0.0))
#                     rr = float(ctx.state.get("rr", 2.0))
#                     # FIX: normalize timestamp to UTC safely
#                     sess = session_of(to_utc(f.ts))
#                     news_bucket = ctx.state.get("news_bucket", "NONE")

#                     self._open = dict(
#                         symbol=self.symbol,
#                         side=o.side,
#                         entry_ts=f.ts,
#                         entry_price=f.price,
#                         qty=f.qty,
#                         fee_entry=f.fee,
#                         timeframe=self.timeframe,
#                         session=sess,
#                         news_bucket=news_bucket,
#                         rr_planned=rr,
#                         risk_unit=risk_unit,
#                         meta={},
#                     )
#                     self._place_oco_exits(o.side, f.qty, f.price, risk_unit, rr)
#                     self._pending_entry_id = None
#                     continue

#                 # exit fill via OCO
#                 if f.order_id in self._oco and self._open is not None:
#                     sibling = self._oco.pop(f.order_id)
#                     self._oco.pop(sibling, None)
#                     self.broker.cancel(sibling)

#                     t = self._open
#                     direction = 1.0 if t["side"] == Side.LONG else -1.0
#                     gross = direction * (f.price - t["entry_price"]) * t["qty"]
#                     pnl_r = gross / max(1e-9, t["risk_unit"] * t["qty"])

#                     tr = Trade(
#                         symbol=t["symbol"],
#                         side=t["side"],
#                         entry_ts=t["entry_ts"],
#                         exit_ts=f.ts,
#                         entry_price=t["entry_price"],
#                         exit_price=f.price,
#                         qty=t["qty"],
#                         fee_entry=t["fee_entry"],
#                         fee_exit=f.fee,
#                         stop_price=self._open.get("stop_price"),
#                         target_price=self._open.get("target_price"),
#                         timeframe=t["timeframe"],
#                         session=t["session"],
#                         news_bucket=t["news_bucket"],
#                         rr_planned=t["rr_planned"],
#                         pnl=gross - t["fee_entry"] - f.fee,
#                         pnl_r=pnl_r,
#                         meta=t["meta"],
#                     )
#                     self.trades.append(tr)
#                     self._open = None

#             for f in fills:
#                 self._id_to_order.pop(f.order_id, None)

#         # flatten if still open
#         if self._open is not None and last_bar is not None:
#             t = self._open
#             exit_price = last_bar.close
#             fee_exit = abs(exit_price * t["qty"]) * self.broker.fee_perc
#             direction = 1.0 if t["side"] == Side.LONG else -1.0
#             gross = direction * (exit_price - t["entry_price"]) * t["qty"]
#             pnl_r = gross / max(1e-9, t["risk_unit"] * t["qty"])
#             self.trades.append(Trade(
#                 symbol=t["symbol"], side=t["side"],
#                 entry_ts=t["entry_ts"], exit_ts=last_bar.ts,
#                 entry_price=t["entry_price"], exit_price=exit_price,
#                 qty=t["qty"], fee_entry=t["fee_entry"], fee_exit=fee_exit,
#                 stop_price=self._open.get("stop_price"), target_price=self._open.get("target_price"),
#                 timeframe=t["timeframe"], session=t["session"], news_bucket=t["news_bucket"],
#                 rr_planned=t["rr_planned"], pnl=gross - t["fee_entry"] - fee_exit, pnl_r=pnl_r, meta=t["meta"]
#             ))
#             self._open = None

#         return self.trades

# file: pa_backtester/backtester.py
from __future__ import annotations
from typing import List, Optional, Dict
import pandas as pd
from .types import Bar, Trade, Side, OrderType, Order
from .strategy import Strategy, Context
from .broker import BrokerSim
from .sessions import session_of
from .news import load_news, is_news_blackout
from pa_backtester.utils import to_utc  # <-- changed to absolute import

class Backtester:
    """Event loop with news/session gating and OCO exits recording."""
    def __init__(self, data_df: pd.DataFrame, symbol: str, timeframe: str, strategy: Strategy, broker: Optional[BrokerSim] = None):
        self.df = data_df.copy()
        self.symbol = symbol
        self.timeframe = timeframe
        self.strategy = strategy
        self.broker = broker or BrokerSim()
        self.trades: List[Trade] = []

        self._open: Optional[dict] = None
        self._pending_entry_id: Optional[int] = None
        self._oco: Dict[int, int] = {}
        self._id_to_order: Dict[int, Order] = {}

    def _place(self, o: Order) -> int:
        oid = self.broker.place(o)
        self._id_to_order[oid] = o
        return oid

    def _place_oco_exits(self, side: Side, qty: float, entry_price: float, risk_unit: float, rr: float) -> None:
        if side == Side.LONG:
            stop_px = entry_price - risk_unit
            tgt_px  = entry_price + rr * risk_unit
            stop_order = Order(id=0, symbol=self.symbol, side=Side.SHORT, qty=qty, type=OrderType.STOP, stop_price=stop_px)
            tgt_order  = Order(id=0, symbol=self.symbol, side=Side.SHORT, qty=qty, type=OrderType.LIMIT, limit_price=tgt_px)
        else:
            stop_px = entry_price + risk_unit
            tgt_px  = entry_price - rr * risk_unit
            stop_order = Order(id=0, symbol=self.symbol, side=Side.LONG, qty=qty, type=OrderType.STOP, stop_price=stop_px)
            tgt_order  = Order(id=0, symbol=self.symbol, side=Side.LONG, qty=qty, type=OrderType.LIMIT, limit_price=tgt_px)
        sid1 = self._place(stop_order)
        sid2 = self._place(tgt_order)
        self._oco[sid1] = sid2
        self._oco[sid2] = sid1
        self._open.update({"stop_price": stop_px, "target_price": tgt_px})

    def run(self) -> List[Trade]:
        ctx = Context(self.symbol, self.timeframe, self.broker.equity)
        self.strategy.init(ctx)

        if hasattr(self.strategy, "news_df"):
            self.news_df = self.strategy.news_df
        else:
            self.news_df = None

        last_bar: Optional[Bar] = None

        for row in self.df.itertuples(index=False):
            bar = Bar(row.ts.to_pydatetime(), float(row.open), float(row.high), float(row.low), float(row.close), float(row.volume), self.timeframe)
            last_bar = bar

            ctx.equity = self.broker.equity
            ctx.state["in_position"] = self._open is not None

            if self._open is None:
                order = self.strategy.on_bar(bar, ctx)
                if order is not None:
                    self._pending_entry_id = self._place(order)

            fills = self.broker.on_bar(bar)

            for f in fills:
                # entry fill
                if self._pending_entry_id == f.order_id and self._open is None:
                    o = self._id_to_order[f.order_id]
                    risk_unit = float(ctx.state.get("risk_unit", 0.0))
                    rr = float(ctx.state.get("rr", 2.0))
                    sess = session_of(to_utc(f.ts))  # <-- safe UTC
                    news_bucket = ctx.state.get("news_bucket", "NONE")

                    self._open = dict(
                        symbol=self.symbol,
                        side=o.side,
                        entry_ts=f.ts,
                        entry_price=f.price,
                        qty=f.qty,
                        fee_entry=f.fee,
                        timeframe=self.timeframe,
                        session=sess,
                        news_bucket=news_bucket,
                        rr_planned=rr,
                        risk_unit=risk_unit,
                        meta={},
                    )
                    self._place_oco_exits(o.side, f.qty, f.price, risk_unit, rr)
                    self._pending_entry_id = None
                    continue

                # exit fill via OCO
                if f.order_id in self._oco and self._open is not None:
                    sibling = self._oco.pop(f.order_id)
                    self._oco.pop(sibling, None)
                    self.broker.cancel(sibling)

                    t = self._open
                    direction = 1.0 if t["side"] == Side.LONG else -1.0
                    gross = direction * (f.price - t["entry_price"]) * t["qty"]
                    pnl_r = gross / max(1e-9, t["risk_unit"] * t["qty"])

                    tr = Trade(
                        symbol=t["symbol"],
                        side=t["side"],
                        entry_ts=t["entry_ts"],
                        exit_ts=f.ts,
                        entry_price=t["entry_price"],
                        exit_price=f.price,
                        qty=t["qty"],
                        fee_entry=t["fee_entry"],
                        fee_exit=f.fee,
                        stop_price=self._open.get("stop_price"),
                        target_price=self._open.get("target_price"),
                        timeframe=t["timeframe"],
                        session=t["session"],
                        news_bucket=t["news_bucket"],
                        rr_planned=t["rr_planned"],
                        pnl=gross - t["fee_entry"] - f.fee,
                        pnl_r=pnl_r,
                        meta=t["meta"],
                    )
                    self.trades.append(tr)
                    self._open = None

            for f in fills:
                self._id_to_order.pop(f.order_id, None)

        # flatten if still open
        if self._open is not None and last_bar is not None:
            t = self._open
            exit_price = last_bar.close
            fee_exit = abs(exit_price * t["qty"]) * self.broker.fee_perc
            direction = 1.0 if t["side"] == Side.LONG else -1.0
            gross = direction * (exit_price - t["entry_price"]) * t["qty"]
            pnl_r = gross / max(1e-9, t["risk_unit"] * t["qty"])
            self.trades.append(Trade(
                symbol=t["symbol"], side=t["side"],
                entry_ts=t["entry_ts"], exit_ts=last_bar.ts,
                entry_price=t["entry_price"], exit_price=exit_price,
                qty=t["qty"], fee_entry=t["fee_entry"], fee_exit=fee_exit,
                stop_price=self._open.get("stop_price"), target_price=self._open.get("target_price"),
                timeframe=t["timeframe"], session=t["session"], news_bucket=t["news_bucket"],
                rr_planned=t["rr_planned"], pnl=gross - t["fee_entry"] - fee_exit, pnl_r=pnl_r, meta=t["meta"]
            ))
            self._open = None

        return self.trades
