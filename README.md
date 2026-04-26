# 📈 Forex-Backtester

> A Python-based price-action forex backtesting engine that simulates trades around **high-impact economic news events**, with full session filtering, volume filtering, and timezone awareness.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Data Requirements](#data-requirements)
- [Running the Backtester](#running-the-backtester)
- [All CLI Arguments](#all-cli-arguments)
- [Example Commands](#example-commands)
- [Understanding the Output](#understanding-the-output)
- [Strategy Logic](#strategy-logic)
- [Notes & Tips](#notes--tips)

---

## Overview

Forex-Backtester is a **CLI-driven backtesting framework** built around a Price Action Breakout strategy. It reads historical OHLCV price data from local CSV files and a news events CSV, then simulates trades based on:

- **Session filters** — only trade during Tokyo, London, or New York sessions
- **News blackout windows** — avoid trading X minutes before/after high-impact news
- **Volume filters** — only enter trades above a configurable volume percentile
- **Breakout logic** — detect price breakouts using a configurable lookback window
- **Risk management** — configurable risk-per-trade percentage and risk:reward ratio

Results are printed to the terminal and saved as a `trade_ledger.csv` for further analysis.

---

## Project Structure

```
Forex-Backtester/
│
├── cli.py                          # Main entry point — run this to start the backtest
│
├── pa_backtester/                  # Core backtesting engine
│   ├── data.py                     # CSVFeed: loads and parses price CSV files
│   ├── backtester.py               # Backtester: iterates candles and executes strategy
│   └── metrics.py                  # Calculates equity metrics, win rates, saves ledger
│
├── strategies/
│   └── price_action.py             # PriceActionBreakout strategy implementation
│
├── data/                           # Your price & news data goes here
│   ├── EURUSD_1m.csv               # 1-minute OHLCV data for EURUSD (not on GitHub - too large)
│   ├── GBPUSD_1m.csv               # 1-minute OHLCV data for GBPUSD (not on GitHub - too large)
│   ├── USDJPY_1m.csv               # 1-minute OHLCV data for USDJPY (not on GitHub - too large)
│   ├── XAUUSD_1m.csv               # 1-minute OHLCV data for XAUUSD (not on GitHub - too large)
│   └── news.csv                    # Economic news calendar with impact levels
│
├── tools/                          # Utility/helper scripts
├── secrets/                        # API keys or credentials (never commit to git)
│
├── trade_ledger.csv                # Output file: every simulated trade logged here
├── wide_candles_EURUSD_5m.csv      # Pre-processed wide candle data for EURUSD
├── .gitignore                      # Excludes large CSVs and sensitive files
└── README.md                       # This file
```

> ⚠️ **Note:** The large price CSV files (`*_1m.csv`) are **not included in this repository** due to GitHub's 100 MB file size limit. You must source and add them locally to the `data/` folder before running.

---

## How It Works

```
Price CSV (OHLCV)          News CSV (events)
        │                         │
        ▼                         ▼
   CSVFeed.history()        News blackout windows
        │                         │
        └──────────┬──────────────┘
                   ▼
        PriceActionBreakout Strategy
          - Session filter (Tokyo/London/NY)
          - Volume percentile filter
          - Breakout range detection (lookback)
          - News blackout enforcement
                   │
                   ▼
            Backtester.run()
          (iterates each candle)
                   │
                   ▼
         Trades List (Win/Loss)
                   │
          ┌────────┴────────┐
          ▼                 ▼
    equity_metrics()   trade_ledger.csv
    winrate_by_session()
    winrate_by_news_bucket()
```

---

## Prerequisites

- **Python 3.8+**
- **pip** (Python package manager)

Check your Python version:
```bash
python3 --version
```

---

## Installation

**1. Clone the repository:**
```bash
git clone https://github.com/PretoriusPratik/Forex-Backtester.git
cd Forex-Backtester
```

**2. Install dependencies:**
```bash
pip3 install pandas numpy
```

---

## Data Requirements

### Price Data (`data/*.csv`)

Each price CSV should follow standard OHLCV format with a datetime column. Example:

```
datetime,open,high,low,close,volume
2023-01-02 00:00:00,1.07012,1.07045,1.06998,1.07031,1250
2023-01-02 00:01:00,1.07031,1.07060,1.07020,1.07055,980
...
```

File naming convention expected by the backtester:
- `EURUSD_1m.csv` — Euro / US Dollar, 1-minute bars
- `GBPUSD_1m.csv` — British Pound / US Dollar, 1-minute bars
- `USDJPY_1m.csv` — US Dollar / Japanese Yen, 1-minute bars
- `XAUUSD_1m.csv` — Gold / US Dollar, 1-minute bars

> You can source 1-minute forex data from providers like **Dukascopy**, **TrueFX**, **HistData.com**, or your broker's export tool.

### News Data (`data/news.csv`)

The news file should contain economic event data. Expected columns:

```
datetime,currency,impact,event
2023-01-06 13:30:00,USD,high,Non-Farm Payrolls
2023-01-12 13:30:00,USD,high,CPI m/m
2023-01-26 13:30:00,USD,high,Advance GDP q/q
...
```

| Column | Description |
|--------|-------------|
| `datetime` | Date and time of the news release |
| `currency` | Currency affected (USD, EUR, GBP, etc.) |
| `impact` | Impact level: `low`, `medium`, or `high` |
| `event` | Name of the economic event |

> You can download news calendars from **Forex Factory**, **Investing.com**, or **DailyFX**.

---

## Running the Backtester

The main entry point is `cli.py`. The minimum required arguments are:

```bash
python3 cli.py \
  --csv-root ./data \
  --symbol EURUSD \
  --news-file ./data/news.csv
```

---

## All CLI Arguments

| Argument | Type | Default | Required | Description |
|---|---|---|---|---|
| `--csv-root` | path | — | ✅ Yes | Folder containing your price CSV files |
| `--symbol` | string | — | ✅ Yes | Currency pair to backtest (e.g. `EURUSD`) |
| `--news-file` | path | — | ✅ Yes | Path to your news events CSV |
| `--timeframe` | choice | `1m` | No | Candle timeframe: `1m`, `15m`, or `1h` |
| `--rr` | float | `2.0` | No | Risk:Reward ratio (e.g. `2.0` = 1:2 RR) |
| `--risk-perc` | float | `0.01` | No | Fraction of account risked per trade (e.g. `0.01` = 1%) |
| `--lookback` | int | `20` | No | Minutes of candles to look back for breakout range detection |
| `--vol-pctl` | float | `0.8` | No | Volume percentile threshold (0.0–1.0). Only trade when volume is above this percentile |
| `--sessions` | string | `TOKYO,LONDON,NEWYORK` | No | Comma-separated list of sessions to trade |
| `--news-blackout-pre` | int | `30` | No | Minutes before a news event to stop trading |
| `--news-blackout-post` | int | `15` | No | Minutes after a news event to resume trading |
| `--min-impact` | choice | `medium` | No | Minimum news impact level to apply blackout: `low`, `medium`, `high` |
| `--price-tz` | string | `UTC` | No | Timezone of your price data (e.g. `Asia/Kolkata`, `UTC`) |
| `--news-tz` | string | `UTC` | No | Timezone of your news data |
| `--out-ledger` | path | `./trade_ledger.csv` | No | File path to save the trade ledger output |

---

## Example Commands

### Minimal Run (all defaults)
```bash
python3 cli.py \
  --csv-root ./data \
  --symbol EURUSD \
  --news-file ./data/news.csv
```

### Conservative — RR 1.5, high-impact news only, London & New York sessions
```bash
python3 cli.py \
  --csv-root ./data \
  --symbol EURUSD \
  --timeframe 1m \
  --news-file ./data/news.csv \
  --rr 1.5 \
  --risk-perc 0.01 \
  --sessions LONDON,NEWYORK \
  --min-impact high \
  --news-blackout-pre 60 \
  --news-blackout-post 30 \
  --vol-pctl 0.8
```

### Balanced — RR 2.0, medium+ news, all sessions
```bash
python3 cli.py \
  --csv-root ./data \
  --symbol GBPUSD \
  --timeframe 1m \
  --news-file ./data/news.csv \
  --rr 2.0 \
  --risk-perc 0.01 \
  --sessions TOKYO,LONDON,NEWYORK \
  --min-impact medium \
  --news-blackout-pre 30 \
  --news-blackout-post 15
```

### Aggressive — RR 3.0, Gold (XAUUSD), 15-minute timeframe
```bash
python3 cli.py \
  --csv-root ./data \
  --symbol XAUUSD \
  --timeframe 15m \
  --news-file ./data/news.csv \
  --rr 3.0 \
  --risk-perc 0.02 \
  --sessions LONDON,NEWYORK \
  --min-impact medium \
  --lookback 30 \
  --vol-pctl 0.7
```

### IST Timezone Data (India)
```bash
python3 cli.py \
  --csv-root ./data \
  --symbol USDJPY \
  --timeframe 1m \
  --news-file ./data/news.csv \
  --price-tz Asia/Kolkata \
  --news-tz Asia/Kolkata \
  --rr 2.0 \
  --sessions TOKYO,LONDON,NEWYORK
```

### Save Output to a Custom File
```bash
python3 cli.py \
  --csv-root ./data \
  --symbol EURUSD \
  --news-file ./data/news.csv \
  --out-ledger ./results/eurusd_backtest.csv
```

---

## Understanding the Output

After running, the terminal will display:

```
Total trades: 142

net_pnl          :  3.24%
win_rate         :  58.45%
max_drawdown     :  -6.12%
sharpe_ratio     :  1.43
total_trades     :  142
...

Win rate by session:
           win_rate   trades
TOKYO        52.00%       25
LONDON       61.00%       72
NEWYORK      56.00%       45

Win rate by news proximity:
                    win_rate   trades
far_from_news         63.0%      98
near_news             44.0%      44

Saved trade ledger to: /path/to/trade_ledger.csv
```

### trade_ledger.csv

Every simulated trade is logged here with columns like:

| Column | Description |
|--------|-------------|
| `entry_time` | Candle timestamp when trade was entered |
| `symbol` | Currency pair traded |
| `direction` | `LONG` or `SHORT` |
| `entry_price` | Price at entry |
| `stop_loss` | Stop loss price |
| `take_profit` | Take profit price |
| `exit_price` | Price at exit |
| `result` | `WIN` or `LOSS` |
| `pnl_pct` | Profit/loss as a percentage of account |
| `session` | Which session the trade occurred in |
| `news_proximity` | How close the trade was to a news event |

---

## Strategy Logic

The **PriceActionBreakout** strategy works as follows:

1. **Session Check** — Is the current candle within an allowed trading session (Tokyo / London / New York)?
2. **News Blackout** — Is the current candle too close (pre or post) to a news event above the minimum impact level? If yes, skip.
3. **Volume Filter** — Is the current candle's volume above the configured percentile of recent volume? If not, skip.
4. **Breakout Detection** — Look back `N` candles (`--lookback`) and identify the high/low range. If price breaks out of this range, a signal is triggered.
5. **Entry & Risk Management** — Enter the trade with a stop loss at the opposite end of the breakout range. Take profit is set at `entry ± (stop_distance × RR)`.
6. **Trade Simulation** — The backtester steps forward candle-by-candle until stop loss or take profit is hit.

---

## Notes & Tips

- **Large data files** (`*_1m.csv`) are excluded from GitHub but required locally. Keep them in the `./data/` folder.
- The `secrets/` folder is gitignored — store any API keys or broker credentials there safely.
- To test a strategy quickly, use `--timeframe 1h` which runs much faster than `1m`.
- Start with `--min-impact high` to get the cleanest signal from major news events like NFP, CPI, and Fed decisions.
- If your data is in IST, always pass both `--price-tz Asia/Kolkata` and `--news-tz Asia/Kolkata` together.
- The `wide_candles_EURUSD_5m.csv` in the root is a pre-processed file and does not need to be in the `data/` folder.

---

## License

This project is for personal research and educational purposes.

---

*Built with Python · Price Action · News-Driven Forex Backtesting*
