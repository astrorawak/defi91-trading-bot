# 🤖 DeFi91 Trading Bot: Master Handoff to Hermes Agent

## 📌 Project Overview
The **DeFi91 Trading Bot** is an automated crypto trading ecosystem running on **Hyperliquid Perpetual Futures**. It consists of a dual-strategy engine (Scalping + Grid) designed for recovery and growth of the user's portfolio.

### 💼 Account Context
- **Owner**: Pak Rizky Karman
- **Wallet**: `0x03562722fE32Ff3BaFE214be3F1828A9157eC23D`
- **Current State**: Bot is **OFF** (Watchlist cleared) awaiting re-activation with optimized strategy.

---

## 🛠 Technical Specifications

### 1. Scalping Engine (`github_bot_v2.py`)
- **Logic**: Hybrid of **CVD/Order Flow** (Volume-weighted) + **RSI/MACD** (Momentum).
- **Core Signal**: Scores each coin from -12 to +12. Entry threshold is ±4.
- **Risk Management**: 
  - Margin: $3.00/trade (Agile for small balances).
  - Leverage: 20x (Capped by API limits per coin).
  - TP: 2.0% | SL: 1.5% (Recovery focus).
  - **Smart Exit**: Early close if signal reverses with score >= 7.

### 2. Grid Engine (`grid_bot.py`)
- **Logic**: ATR-based range trading.
- **Regime Activation**: Only active during **NEUTRAL** or **CHOPSAW** markets.
- **Structure**: 3 Buy + 3 Sell levels, $20 total budget, 5x leverage.

### 3. Market Regime Filter (`market_regime_filter.py`)
- **Metrics**: ATR (Volatility), ADX (Trend Strength), Bollinger Band Width.
- **States**: `TRENDING`, `NEUTRAL`, `CHOPSAW`.

### 4. Infrastructure
- **Host**: GitHub Actions (11 scheduled sessions per day).
- **Reporting**: Real-time Telegram signals + Daily Performance Reports + Weekly Insights.

---

## 📈 Performance Analysis (Context for Hermes)
- **Total Realized PnL (DeFi91 Era)**: ~-$3.11 (Nearly breakeven).
- **Primary Issue**: High fees due to frequent trades ($18.94 fees vs $15.83 gross profit).
- **Strategy Failure**: "Smart Exit" was too sensitive (previously 4, now 7), causing panic closes on minor pullbacks.
- **Winning Coins**: ETH, XRP, SOL, SUI, BNB.

---

## 🧠 Hermes Agent Capability Analysis
Hermes is uniquely qualified to take DeFi91 to the next level because of:
1. **Self-Evolving Memory**: Hermes can store execution traces and evaluate which trade setups led to profit vs loss.
2. **Dynamic Skill Creation**: Hermes can write its own Python scripts or modify existing logic based on market shifts without human intervention.
3. **Multi-Source Analysis**: Unlike Manus, Hermes can autonomously monitor X (Twitter), Whale Alerts, and News APIs to adjust "Market Regime" sentiment.

---

## 🚀 MASTER PROMPT FOR HERMES AGENT

> **Identity**: You are the **Hermes DeFi91 Strategist**, a self-evolving AI fund manager.
>
> **Objective**: Manage, evaluate, and optimize the DeFi91 Trading Bot. Your goal is to recover drawdown and maximize profit through superior market awareness and self-correction.
>
> **Task 1: System Ingestion**
> 1. Read and analyze all `.py` files in the repository.
> 2. Analyze `performance.json` and `trades.json` to identify the "DNA" of winning trades vs losing trades.
> 3. Provide a structural audit: where are the inefficiencies in the current logic?
>
> **Task 2: Advanced Awareness (Hermes Speciality)**
> 1. **Sentiment Layer**: Integrate a "News/Whale Sentiment" check before any entry. If whale inflows are massive or news is bearish, override the technical LONG signal.
> 2. **Self-Evaluation**: After every 24 hours, run an internal "Eval". Ask yourself: "Why did we lose today? Was it the entry threshold or the exit timing?"
> 3. **Strategy Mutation**: If a specific coin (e.g., VVV) has a win rate < 30% over 10 trades, automatically remove it from the watchlist or adjust its parameters.
>
> **Task 3: Re-Activation**
> 1. Restore the `WATCHLIST` in `github_bot_v2.py` and `grid_bot.py`.
> 2. Ensure `MARGIN_PER_TRADE` is aligned with the latest account balance.
> 3. Monitor the next 3 trades closely and report to Pak Karman on Telegram with a "Confidence Score" for each trade.
>
> **Guardrails**:
> - Never exceed 20x leverage.
> - Never use more than 50% of total equity as margin.
> - Report all "Strategy Mutations" to Pak Karman for transparency.

---

## 📋 Suggestions for Hermes (from Manus)
1. **Dynamic SL/TP**: Instead of fixed 2% / 1.5%, make Hermes calculate TP/SL based on the current ATR (e.g., SL = 1.5 * ATR).
2. **Whale Tracker**: Monitor Hyperliquid's top vault positions and copy-trade the "smart money" within the bot's framework.
3. **Auto-Optimization**: Hermes should periodically run `optimize_params.py` to find the best RSI/MACD settings for the current week's volatility.

**Status: READY FOR TRANSITION**
*Prepared by Manus AI on Aug 19, 2026*
