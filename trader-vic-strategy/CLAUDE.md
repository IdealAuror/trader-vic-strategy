# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

Quantitative trading strategy based on Victor Sperandeo's "Trader Vic: Methods of a Wall Street Master" (专业投机原理), targeting A-shares (沪深A股). Uses a multi-layer confirmation funnel approach — not a signal-chasing system, but a risk-management system.

**Current status**: Phase 1 pre-implementation. Directory structure exists, but zero Python files written. Full implementation plan at `C:\Users\MOSS\.claude\plans\abstract-mapping-sky.md`.

## Architecture (Phase 1)

17 files, ~2400 lines, 6 implementation steps:

```
Step 1: config.py, data/providers.py, requirements.txt
Step 2: core/trend.py (SwingDetector weekly+daily), core/signals.py, core/probability.py
Step 3: core/fundamental_regime.py, core/consensus.py, core/risk.py, core/capital.py, core/market_env.py
Step 4: portfolio/mgr.py
Step 5: strategies/vic_strategy.py
Step 6: fetch.py, backtest.py, reports/backtest.py, daily_report.py, reports/daily_html.py
```

### Main flow (per-bar)

```
Step 0:   Fundamental regime update (M2/PMI/Shibor, lagged 1mo)
Step 1:   Portfolio mark-to-market + risk accounting
Step 1.3: Multi-timeframe trend (CSI300 weekly resampled from daily)
Step 1.5: Market environment classification (7-condition)
Step 1.8: Per-stock multi-timeframe trend
Step 2:   Check existing positions → exit conditions
Step 3:   Scan watchlist → entry conditions
  ├── Signal detection (1-2-3/2B/FourDay/ThreeDayPullback)
  ├── Layer 1: Technical consensus (log-odds voting)
  ├── Layer 2: Fundamental alignment (FILTER/REDUCE/IGNORE)
  ├── Layer 3: Environment adaptation (CRISIS skips all)
  ├── Layer 4: Dow confirmation (CSI300 vs 上证)
  ├── EV > 0 + RRR >= min_rrr check
  └── Mark as enterable
Step 3.5: Risk allocation (sort by EV×boost×confidence, enter in order)
Step 4:   Execute orders (exit > entry, 涨跌停 filter)
Step 5:   Capital management
```

### Data pipeline

```
akshare.stock_zh_a_hist(symbol, adjust="qfq")  → 前复权日线
akshare.stock_zh_index_daily("sh000300")         → CSI300
akshare macro functions                          → M2/PMI/Shibor

Quality gates:
  - min 252 bars, NaN < 5%, no 20-day flatline (停牌)
  - 佣金 万三 bilateral + 印花税 千一 sell-only + 滑点 0.1%
  - Macro data shifted by 1 month (publication lag)
```

### Key constants (A-share specific)

```python
RISK_PCT = 0.02              # Per-trade max risk
TOTAL_RISK_BUDGET = 0.15     # Total portfolio risk cap
CN_BULL_MEAN_MONTHS = 14     # CSI300 bull market mean
CN_BEAR_MEAN_MONTHS = 7      # CSI300 bear market mean
COMMISSION_RATE = 0.0003     # 万三
STAMP_TAX_RATE = 0.001       # 千一, sell only
```

## Module Interface Contracts

| File | Exports | Input → Output |
|------|---------|---------------|
| `config.py` | Constants, probability table, ENV_ADAPTATION table | — (pure config) |
| `data/providers.py` | `fetch_watchlist()`, `fetch_index()`, `validate_stock_data()`, `resample_to_weekly()` | tickers × dates → dict[OHLCV DataFrame] |
| `core/trend.py` | `SwingDetector`, `TrendAge`, `RetracementLocator`, `MarketPhase` | OHLC series → UP/DOWN/RANGE state |
| `core/signals.py` | `Criterion123`, `Criterion2B`, `FourDayRule`, `ThreeDayPullback` | OHLC arrays → `Signal(direction,confidence,stop,target)` or None |
| `core/probability.py` | `EVCalculator`, `KellyFraction` | p_win, reward, risk → float |
| `core/fundamental_regime.py` | `FundamentalRegime` | M2/PMI/Shibor → BULLISH/NEUTRAL/BEARISH |
| `core/consensus.py` | `ConsensusEngine`, `DowConfirmation` | signals + regime + env → weighted consensus |
| `core/capital.py` | `CapitalManager`, `TieredPositionSizer` | portfolio value → tier level, position size |
| `core/risk.py` | `RiskRewardFilter`, `StopManager`, `TimeStop`, `ConsecutiveLossPause` | prices + position → HOLD/STOP/TAKE_PROFIT/TIME_EXIT |
| `core/market_env.py` | `MarketEnvClassifier` + `ENV_ADAPTATION` | CSI300 daily+weekly → environment string + params |
| `portfolio/mgr.py` | `PortfolioMgr` | risk check, entry/exit accounting, state serialization |
| `strategies/vic_strategy.py` | `TraderVicStrategy.next()` | bar_data + csi300 → list[Order] |
| `reports/backtest.py` | `run_backtest()`, metrics, plotting | strategy + data → HTML report |
| `reports/daily_html.py` | `generate_daily_report()` | strategy + latest data → HTML |

## Critical Design Decisions

1. **Custom backtest engine (not backtrader)**: Multi-stock portfolio management is simpler in a custom loop.
2. **State machine (not vectorized)**: SwingDetector processes bar-by-bar. No look-ahead bias.
3. **Weekly bars resampled from daily in real-time**: Only `df.loc[:current_date]` data used per bar.
4. **Fundamental regime is mandatory Phase 1**: Simple M2/PMI/Shibor scoring, not deferred to Phase 2.
5. **Risk-driven position count**: No fixed MAX_POSITIONS. Market determines via risk cap.
6. **Multi-timeframe is core**: Weekly SwingDetector sets direction, daily detects entries.
7. **Macro data shifted 1 month**: T-1 data to avoid publication look-ahead bias.

## Key References

- **Implementation plan**: `C:\Users\MOSS\.claude\plans\abstract-mapping-sky.md`
- **Technical spec**: `SPEC.md`
- **Skill (book content)**: `~/.claude/skills/trader-vic/` (chapters, cheatsheet, patterns)
- **Data source**: akshare (stock_zh_a_hist with qfq)

## A-Share Specific Constraints

- 涨跌停 ±10%: buys blocked at limit-up, sells blocked at limit-down
- T+1 settlement: sell proceeds available for same-day re-buy
- 前复权 (qfq) for all OHLCV data
- CN_STATS for TrendAge: bull mean 14mo, bear mean 7mo (not US 28/13)

## Commands

```bash
# Data fetch
python fetch.py

# Backtest
python backtest.py          # generates output/backtest_result.html

# Daily report
python daily_report.py      # generates output/daily_report_YYYY-MM-DD.html

# Unit tests
python -m pytest tests/ -v
python -m pytest tests/test_trend.py -v
python -m pytest tests/test_integration.py -v
```

## 8 Design Principles (applied)

1. **Occam's Razor** — simplest solution that works. No premature abstractions.
2. **No Free Lunch** — choose methods by context, no universal solver.
3. **Hume's Causality** — correlation ≠ causation. Validate with controlled tests.
4. **MDL** — among similar fits, prefer fewer parameters.
5. **Murphy's Law** — design for data gaps, strategy errors, input anomalies.
6. **Pareto** — nail common-case quality; don't chase 100% edge-case perfection.
7. **Kidlin's Law** — define the business problem in one sentence before designing.
8. **Transparency** — output should be explainable. Know capability boundaries.

## 3-Tier Review

| Change Type | Execute | Review |
|-------------|---------|--------|
| Simple (constants, docs, routine commits) | Flash | None |
| Regular (param tweaks, test fixes) | Flash Agent | Flash Agent (self-review) |
| Important (new mechanisms, grid search, multi-variable) | Flash Agent | Opus Agent (high-level guidance) |

## Memory

User's auto-memory at `C:\Users\MOSS\.claude\projects\C--Users-MOSS-Desktop-book-to-skill\memory\MEMORY.md` — contains behavioral principles, division of labor, and 8 design principles. Check this before making design decisions.
