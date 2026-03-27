# file: tools/run_ny_open_strategy.py
"""
NY-Open Momentum strategy backtest for EURUSD (or similar majors).

Rules:
- Determine New York session open at 08:00 America/New_York (DST-aware) for each trading day.
- If within the first 15 minutes after 08:00 (inclusive), price moves ≥ N pips from the 08:00 open,
  enter in that direction at the minute that first hits the threshold.
- Initial stop = 5 pips beyond the 08:00 open.
- Trailing by R multiples: once price reaches >= 2R, move TSL to +1R; >=3R -> +2R; ... Keep ratcheting.
- Exit only when the trailing stop is hit (or if data ends, exit at last close).

Output:
- Trade ledger CSV with detailed fields.
- Printed metrics: total trades, winrate, expectancy, profit factor, counts by max R reached.

Usage:
  python tools/run_ny_open_strategy.py \
    --csv-root ./data \
    --symbol EURUSD \
    --timeframe 1m \
    --price-tz UTC \
    --pip-size 0.0001 \
    --pip-move 10 \
    --pip-sl-from-open 5 \
    --out-ledger ./ny_open_ledger_EURUSD_1m.csv
"""

from __future__ import annotations
import argparse
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import math

import pandas as pd
import numpy as np
import pytz

NY_TZ = "America/New_York"

def load_bars(csv_root: Path, symbol: str, timeframe: str, price_tz: str) -> pd.DataFrame:
    fp = csv_root / f"{symbol}_{timeframe}.csv"
    df = pd.read_csv(fp)
    if "ts" not in df.columns:
        raise ValueError("CSV must have a 'ts' column.")
    # Parse timestamps and set timezone
    ts = pd.to_datetime(df["ts"], utc=True)
    if price_tz.upper() != "UTC":
        # Assume stored tz is whatever the string carries; normalize to requested tz for alignment
        # If CSV already tz-aware in a different tz, convert to that tz; otherwise localize then convert to tz.
        if ts.dt.tz is not None:
            ts = ts.dt.tz_convert(price_tz)
        else:
            ts = pd.to_datetime(df["ts"]).dt.tz_localize(price_tz)
    df["ts"] = ts
    # Ensure standard columns
    for col in ["open","high","low","close"]:
        if col not in df.columns:
            raise ValueError(f"Missing '{col}' column.")
    if "volume" not in df.columns:
        df["volume"] = np.nan
    df = df.sort_values("ts").reset_index(drop=True)
    return df

def ny_open_ts_for_day(day_ts_price_tz: pd.Timestamp, price_tz: str) -> pd.Timestamp:
    """
    Given any timestamp of the day in price tz, return the timestamp of 08:00 New_York for that day,
    expressed in the price timezone (tz-aware).
    """
    # Get date in NY tz
    ny_day = day_ts_price_tz.tz_convert(NY_TZ).normalize()
    ny_open = ny_day + pd.Timedelta(hours=8)  # 08:00 in NY time for that calendar day (DST-aware)
    # Convert that 08:00 NY timestamp to the price tz
    return ny_open.tz_convert(price_tz)

def first_bar_at_or_after(df: pd.DataFrame, ts_target: pd.Timestamp) -> Optional[int]:
    idx = df.index[df["ts"] >= ts_target]
    return int(idx[0]) if len(idx) else None

def scan_first_15_min_trigger(df: pd.DataFrame,
                              start_idx: int,
                              end_ts_exclusive: pd.Timestamp,
                              ny_open_price: float,
                              pip_move: float,
                              pip_size: float,
                              direction_priority: str = "either") -> Optional[Tuple[str, int]]:
    """
    Within [start_idx, bars where ts < end_ts_exclusive], find first bar index where:
    - long trigger: high >= ny_open + pip_move*pip_size
    - short trigger: low  <= ny_open - pip_move*pip_size
    Returns (direction, trigger_index) or None if no trigger.
    If both are met on the same bar, prioritize the one that exceeds first by distance;
    tie-breaker: 'direction_priority' ('long'/'short'/'either') defaults to 'either' -> long if equal.
    """
    up_level = ny_open_price + pip_move * pip_size
    dn_level = ny_open_price - pip_move * pip_size
    # Iterate minute by minute
    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        if row["ts"] >= end_ts_exclusive:
            break
        hit_up = row["high"] >= up_level
        hit_dn = row["low"]  <= dn_level
        if hit_up and not hit_dn:
            return ("long", i)
        if hit_dn and not hit_up:
            return ("short", i)
        if hit_up and hit_dn:
            # choose by which distance exceeded more
            dist_up = row["high"] - up_level
            dist_dn = dn_level - row["low"]
            if dist_up > dist_dn:
                return ("long", i)
            elif dist_dn > dist_up:
                return ("short", i)
            else:
                if direction_priority == "long":
                    return ("long", i)
                if direction_priority == "short":
                    return ("short", i)
                return ("long", i)
    return None

def simulate_trade(df: pd.DataFrame,
                   entry_idx: int,
                   direction: str,
                   ny_open_price: float,
                   pip_sl_from_open: float,
                   pip_size: float) -> Dict:
    """
    Simulate trailing-by-R trade from entry_idx+1 forward.
    Initial SL is relative to NY open (not entry).
    Ratchet TSL: at kR reached (k >= 2), TSL = (k-1)R; keep increasing. Exit when price crosses TSL.
    Returns a ledger dict.
    """
    # Define entry price at bar close of trigger bar (more conservative than mid)
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    entry_ts = entry_bar["ts"]

    # Initial SL from NY open:
    if direction == "long":
        sl0_price = ny_open_price - pip_sl_from_open * pip_size
        R = entry_price - sl0_price
    else:
        sl0_price = ny_open_price + pip_sl_from_open * pip_size
        R = sl0_price - entry_price
    if R <= 0:
        return {}

    # Walk forward
    max_k_reached = 1  # number of full R multiples the price has *ever* surpassed; starts at 1 (entry)
    tsl_price = sl0_price  # trailing stop starts at initial SL
    exit_price = None
    exit_ts = None

    for j in range(entry_idx + 1, len(df)):
        bar = df.iloc[j]
        high = float(bar["high"])
        low  = float(bar["low"])
        # Update targets & TSL
        if direction == "long":
            # compute highest k such that high >= entry + k*R
            if high > entry_price:
                k = int(math.floor((high - entry_price) / R))
                if k >= 2 and k > max_k_reached:
                    # raise TSL to (k-1)R above entry
                    max_k_reached = k
                    tsl_price = entry_price + (k - 1) * R
            # Check stop after ratchet
            if low <= tsl_price:
                exit_price = tsl_price
                exit_ts = bar["ts"]
                break
        else:  # short
            if low < entry_price:
                k = int(math.floor((entry_price - low) / R))
                if k >= 2 and k > max_k_reached:
                    max_k_reached = k
                    tsl_price = entry_price - (k - 1) * R
            if high >= tsl_price:
                exit_price = tsl_price
                exit_ts = bar["ts"]
                break

    # If never stopped before data end, exit at last close
    if exit_price is None:
        last = df.iloc[-1]
        exit_price = float(last["close"])
        exit_ts = last["ts"]

    # Metrics
    signed_pnl = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    rr_exit = signed_pnl / R
    pips = signed_pnl / pip_size
    outcome = "win" if rr_exit > 0 else "loss"

    return {
        "symbol": None,
        "timeframe": None,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "direction": direction,
        "ny_open": ny_open_price,
        "entry": entry_price,
        "sl0": sl0_price,
        "R": R,
        "exit": exit_price,
        "rr_exit": rr_exit,
        "pips": pips,
        "max_R_reached": max_k_reached,
        "outcome": outcome,
    }

def run_strategy(csv_root: Path,
                 symbol: str,
                 timeframe: str,
                 price_tz: str,
                 pip_size: float,
                 pip_move: float,
                 pip_sl_from_open: float) -> pd.DataFrame:
    df = load_bars(csv_root, symbol, timeframe, price_tz)
    trades: List[Dict] = []

    # Build daily group by date in price tz
    df["date_price_tz"] = df["ts"].dt.tz_convert(price_tz).dt.date if df["ts"].dt.tz is not None else df["ts"].dt.date
    days = sorted(pd.unique(df["date_price_tz"]))

    for d in days:
        # a representative timestamp for the day in price tz (noon helps)
        rep_ts = pd.Timestamp(d).tz_localize(price_tz) + pd.Timedelta(hours=12)
        ny_open_ts_price_tz = ny_open_ts_for_day(rep_ts, price_tz)
        idx0 = first_bar_at_or_after(df, ny_open_ts_price_tz)
        if idx0 is None:
            continue

        open_bar = df.iloc[idx0]
        ny_open_price = float(open_bar["open"])

        # 15-minute window end ts (exclusive)
        end_ts = ny_open_ts_price_tz + pd.Timedelta(minutes=15)

        trig = scan_first_15_min_trigger(
            df=df,
            start_idx=idx0,
            end_ts_exclusive=end_ts,
            ny_open_price=ny_open_price,
            pip_move=pip_move,
            pip_size=pip_size,
        )
        if trig is None:
            continue

        direction, trig_idx = trig
        trade = simulate_trade(
            df=df,
            entry_idx=trig_idx,
            direction=direction,
            ny_open_price=ny_open_price,
            pip_sl_from_open=pip_sl_from_open,
            pip_size=pip_size,
        )
        if not trade:
            continue
        trade["symbol"] = symbol
        trade["timeframe"] = timeframe
        trades.append(trade)

    return pd.DataFrame(trades)

def metrics(ledger: pd.DataFrame) -> Dict:
    if ledger.empty:
        return {"total": 0, "winrate": 0.0, "expectancy": 0.0, "profit_factor": 0.0}

    pnl = ledger["rr_exit"]  # in R units
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl <= 0].sum()
    profit_factor = (wins / losses) if losses > 0 else np.inf
    return {
        "total": len(ledger),
        "winrate": float((ledger["rr_exit"] > 0).mean()),
        "expectancy_R": float(pnl.mean()),
        "profit_factor": float(profit_factor),
        "avg_rr_win": float(ledger.loc[ledger["rr_exit"] > 0, "rr_exit"].mean()) if (ledger["rr_exit"] > 0).any() else 0.0,
        "avg_rr_loss": float(ledger.loc[ledger["rr_exit"] <= 0, "rr_exit"].mean()) if (ledger["rr_exit"] <= 0).any() else 0.0,
    }

def breakdown_by_maxR(ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return pd.DataFrame(columns=["max_R_floor","count","wins","losses","winrate"])
    m = ledger.copy()
    m["max_R_floor"] = m["max_R_reached"].astype(int)
    g = m.groupby("max_R_floor", observed=True)
    out = pd.DataFrame({
        "count": g.size(),
        "wins": g.apply(lambda x: (x["rr_exit"] > 0).sum()),
        "losses": g.apply(lambda x: (x["rr_exit"] <= 0).sum()),
        "winrate": g.apply(lambda x: (x["rr_exit"] > 0).mean()),
    }).reset_index()
    return out.sort_values("max_R_floor")

def main():
    ap = argparse.ArgumentParser(description="NY-Open Momentum strategy backtest.")
    ap.add_argument("--csv-root", type=Path, required=True)
    ap.add_argument("--symbol", type=str, default="EURUSD")
    ap.add_argument("--timeframe", type=str, default="1m", help="1m,5m,15m; 1m recommended for 15-min window fidelity.")
    ap.add_argument("--price-tz", type=str, default="UTC", help="Timezone of 'ts' column for alignment (e.g., UTC or Asia/Kolkata).")
    ap.add_argument("--pip-size", type=float, default=0.0001)
    ap.add_argument("--pip-move", type=float, default=10.0, help="Pips from NY open to trigger entry (default 10).")
    ap.add_argument("--pip-sl-from-open", type=float, default=5.0, help="Initial SL distance in pips from NY open (default 5).")
    ap.add_argument("--out-ledger", type=Path, required=True)
    args = ap.parse_args()

    ledger = run_strategy(
        csv_root=args.csv_root,
        symbol=args.symbol,
        timeframe=args.timeframe,
        price_tz=args.price_tz,
        pip_size=args.pip_size,
        pip_move=args.pip_move,
        pip_sl_from_open=args.pip_sl_from_open,
    )
    if ledger.empty:
        print("No trades generated.")
        return

    # Save ledger
    args.out_ledger.parent.mkdir(parents=True, exist_ok=True)
    # Formatting
    out = ledger.copy()
    out["entry_ts"] = out["entry_ts"].astype("datetime64[ns, UTC]").astype(str)
    out["exit_ts"] = out["exit_ts"].astype("datetime64[ns, UTC]").astype(str)
    out.to_csv(args.out_ledger, index=False)

    # Metrics
    m = metrics(ledger)
    print(f"\nTotal trades: {m['total']}")
    print({"winrate": m["winrate"], "expectancy_R": m["expectancy_R"], "profit_factor": m["profit_factor"],
           "avg_rr_win": m["avg_rr_win"], "avg_rr_loss": m["avg_rr_loss"]})

    # Breakdown by max R reached
    br = breakdown_by_maxR(ledger)
    if not br.empty:
        # pretty print with percentages
        br["winrate"] = (br["winrate"] * 100.0).round(2).astype(str) + "%"
        print("\nBreakdown by max R reached (floor):")
        print(br.to_string(index=False))
    print(f"\nLedger saved to: {args.out_ledger}")

if __name__ == "__main__":
    main()
