"""Trader Vic 主策略 — 每 K 线调度所有模块的完整流程

10 步流程：
Step 0:  基本面方向更新（月频）
Step 1:  组合市值 + 风险敞口会计
Step 1.3: 多周期趋势判定（CSI300 周线）
Step 1.5: 市场环境分类
Step 1.8: 个股多周期趋势判定
Step 2:  检查持仓 → 出场判断
Step 3:  遍历候选池 → 信号检测 → 多层确认漏斗
Step 3.5: 风险分配（按 EV×boost×置信度 降序）
Step 4:  执行订单（出场优先于入场）
Step 5:  资本管理更新
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from trader_vic.config import WATCHLIST, SHORT_ALLOWED, A_SHARE_DUAL_TF_REQUIRED, A_SHARE_MIN_VOL_RATIO, ANTI_CHASE_MAX_INTRADAY, ANTI_CHASE_MAX_GAP, LIMIT_UP_DOWN_PROXIMITY, VOL_SURGE_MULTIPLIER, VOL_SURGE_LOOKBACK, VOL_SURGE_CONFIDENCE_BOOST
import trader_vic.config as cfg
from trader_vic.core.trend import SwingDetector, TrendAge, TrendDirection, MarketPhase, MarketPhaseType, RetracementLocator
from trader_vic.core.signals import Criterion123, Criterion2B, FourDayRule, ThreeDayPullback, ABCCorrection, NarrowRangeBreakout, Signal
from trader_vic.core.probability import EVCalculator
from trader_vic.core.fundamental_regime import FundamentalRegime
from trader_vic.core.consensus import ConsensusEngine, DowConfirmation
from trader_vic.core.risk import TimeStop, ConsecutiveLossPause
from trader_vic.core.capital import CapitalManager, TieredPositionSizer
from trader_vic.core.market_env import MarketEnvClassifier
from trader_vic.core.alpha_factors import FactorRanker
from trader_vic.core.divergence import RSIDivergence
from trader_vic.portfolio.mgr import PortfolioMgr, Position
import logging

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """订单"""
    ticker: str
    action: str  # BUY / SELL
    shares: int
    price: float
    stop: float
    target: float
    signal_type: str = ""
    reason: str = ""


@dataclass
class CandidateEntry:
    """候选入场记录"""
    ticker: str
    signal: Signal
    ev: float
    rr_ratio: float
    shares: int
    entry_score: float


class TraderVicStrategy:
    """斯波朗迪主策略

    每根 K 线调用 next()，传入当日所有股票数据 + 沪深300数据。
    """

    def __init__(self, initial_capital: float = 1_000_000):
        # 模块实例
        self.pm = PortfolioMgr(initial_capital)
        self.capital_mgr = CapitalManager(initial_capital)
        self.fundamental = FundamentalRegime()
        self.consensus = ConsensusEngine()
        self.env_classifier = MarketEnvClassifier()
        self.loss_pause = ConsecutiveLossPause()
        self.trend_age = TrendAge()
        self.factor_ranker = FactorRanker()
        self._last_trend_dir: Optional[TrendDirection] = None
        self._market_phase = MarketPhaseType.ACCUMULATION

        # 多周期 SwingDetector（CSI300 级别）
        self.csi300_weekly_detector = SwingDetector(lookback=8)
        self.csi300_daily_detector = SwingDetector(lookback=10)
        self._csi300_initialized = False  # 防重复初始化
        self._sh_weekly_detector = SwingDetector(lookback=8)
        self._sh_weekly_initialized = False
        self._last_weekly_date = None  # 周线增量更新缓存

        # 个股 SwingDetectors
        self._stock_detectors: dict[str, SwingDetector] = {}

        # 个股历史数据缓存（backtest 时注入）
        self._stock_data: dict[str, pd.DataFrame] = {}

        # 交易统计
        self.trades_today: list = []
        self.equity_curve: list[dict] = []
        self._current_date: Optional[datetime] = None
        self._monthly_update_done = False

    def _get_stock_detector(self, ticker: str) -> SwingDetector:
        if ticker not in self._stock_detectors:
            self._stock_detectors[ticker] = SwingDetector(lookback=10)
        return self._stock_detectors[ticker]

    def next(
        self,
        bar_data: dict[str, pd.Series],
        csi300_bar: pd.Series,
        csi300_history: pd.DataFrame,
        sh_index_bar: Optional[pd.Series] = None,
        sh_index_history: Optional[pd.DataFrame] = None,
        current_date: Optional[datetime] = None,
    ) -> list[Order]:
        """每根 K 线的策略调度

        Args:
            bar_data: {ticker: OHLCV Series} 当日所有股票数据
            csi300_bar: 当日沪深 300 数据
            csi300_history: 沪深 300 历史日线数据（截至当日）
            sh_index_bar: 当日上证指数数据（可选）
            sh_index_history: 上证指数历史数据（可选）

        Returns:
            订单列表
        """
        if current_date is None:
            current_date = datetime.now()
        self._current_date = current_date

        orders: list[Order] = []

        # ── Step 0: 基本面方向更新（月频） ──
        if not self._monthly_update_done or current_date.day <= 5:
            if not self._monthly_update_done:
                vol_trend = MarketEnvClassifier.volume_trend(csi300_history)
                self.fundamental.update(current_date, volume_trend=vol_trend)
                self._monthly_update_done = True
        if current_date.day > 20:
            self._monthly_update_done = False

        # ── Step 1: 组合市值 + 风险敞口会计 ──
        prices = {t: s.get("close", 0) for t, s in bar_data.items()}
        portfolio_value = self.pm.mark_to_market(prices)
        self.capital_mgr.update(portfolio_value)
        self.equity_curve.append({
            "date": current_date,
            "value": portfolio_value,
        })

        # ── Step 1.3: 多周期趋势判定 ──
        self._update_csi300_trend(csi300_history)
        csi300_weekly_trend = self.csi300_weekly_detector.state

        # ── Step 1.5: 市场环境分类 ──
        weekly_df = self._resample_index_to_weekly(csi300_history)
        env = self.env_classifier.classify(
            csi300_history, weekly_df,
            daily_trend=self.csi300_daily_detector.state,
            weekly_trend=csi300_weekly_trend,
        )
        env_adapt = self.env_classifier.get_env_adapt(env)
        self.pm.set_position_cap(env_adapt.get("position_cap", 1.0))
        self.consensus.set_environment(env_adapt)
        self.consensus.set_fundamental(self.fundamental.get_regime())

        # ── 宏观定仓位中枢，技术调边界 ──
        # 基本面风险预算 = 仓位中枢 (0.30~1.00)
        # 技术环境在此基础上收窄 (±20% 调整)
        risk_budget = self.fundamental.get_risk_budget()
        tech_cap = env_adapt.get("position_cap", 1.0)
        env_adapt["position_cap"] = min(risk_budget * max(tech_cap, 0.5), 1.0)
        self.pm.set_position_cap(env_adapt["position_cap"])

        # 趋势年龄追踪
        if csi300_weekly_trend and csi300_weekly_trend not in (TrendDirection.RANGE, TrendDirection.UNDEFINED):
            if self._last_trend_dir != csi300_weekly_trend:
                self.trend_age.start_trend(pd.Timestamp(current_date), csi300_weekly_trend)
                self._last_trend_dir = csi300_weekly_trend
        age_pct = self.trend_age.percentile(pd.Timestamp(current_date), csi300_weekly_trend) if csi300_weekly_trend else 0.0
        if age_pct > 0.80 and "AGING" not in env:
            env_adapt["signal_boost"] = env_adapt.get("signal_boost", 1.0) * 0.8
            env_adapt["position_cap"] = env_adapt.get("position_cap", 1.0) * 0.7
            self.pm.set_position_cap(env_adapt["position_cap"])

        # 市场四阶段
        price_vs_ma = None
        if len(csi300_history) >= 200:
            ma200 = csi300_history["close"].iloc[-200:].mean()
            price_vs_ma = float(csi300_history["close"].iloc[-1]) / ma200
        self._market_phase = MarketPhase.phase(csi300_weekly_trend, price_vs_ma=price_vs_ma)
        if self._market_phase == MarketPhaseType.DISTRIBUTION or self._market_phase == MarketPhaseType.MARKDOWN:
            env_adapt["position_cap"] = min(env_adapt.get("position_cap", 1.0), 0.5)
            self.pm.set_position_cap(env_adapt["position_cap"])

        # 道氏确认
        dow_dir = None
        if sh_index_history is not None:
            sh_weekly = self._resample_index_to_weekly(sh_index_history)
            if not self._sh_weekly_initialized:
                for i in range(len(sh_weekly)):
                    row = sh_weekly.iloc[i]
                    self._sh_weekly_detector.update(float(row["high"]), float(row["low"]), float(row["close"]))
                self._sh_weekly_initialized = True
            elif len(sh_weekly) > 0:
                last_row = sh_weekly.iloc[-1]
                self._sh_weekly_detector.update(float(last_row["high"]), float(last_row["low"]), float(last_row["close"]))
            dow_dir = DowConfirmation.check(
                csi300_weekly_trend.value if csi300_weekly_trend else "RANGE",
                self._sh_weekly_detector.state.value if self._sh_weekly_detector.state else None,
            )
            if dow_dir is not None:
                self.consensus.set_dow_confirmation(dow_dir)

        # ── Step 1.8: 个股多周期趋势 ──
        for ticker, bar in bar_data.items():
            high_v = float(bar.get("high", 0))
            low_v = float(bar.get("low", 0))
            close_v = float(bar.get("close", 0))
            if high_v == 0 or low_v == 0:
                continue
            det = self._get_stock_detector(ticker)
            det.update(high_v, low_v, close_v)

        # ── Step 2: 检查持仓 → 出场 ──
        for ticker in list(self.pm.positions.keys()):
            if ticker not in bar_data:
                continue

            pos = self.pm.positions[ticker]
            bar = bar_data[ticker]
            high = float(bar.get("high", 0))
            low = float(bar.get("low", 0))
            close = float(bar.get("close", 0))

            if high == 0 or low == 0:
                continue

            # 更新止损
            if pos.stop_manager:
                action = pos.stop_manager.update(high, low)
                pos.stop = pos.stop_manager.stop

                retrace_ratio = RetracementLocator.retracement_ratio(
                    pos.stop_manager.highest_price, pos.entry_price, close
                )
                if not RetracementLocator.is_healthy_retracement(retrace_ratio):
                    pos.stop = max(pos.stop, close * 0.97)

                if action == "STOP_HIT":
                    rec = self.pm.exit(ticker, low, "STOP_HIT")
                    if rec:
                        self._record_exit(rec)
                        orders.append(Order(ticker, "SELL", pos.shares, low, 0, 0, "", "鳄鱼原则止损"))
                    continue

            # 时间止损
            if TimeStop.check(pos.bars_held):
                rec = self.pm.exit(ticker, close, "TIME_EXIT")
                if rec:
                    self._record_exit(rec)
                    orders.append(Order(ticker, "SELL", pos.shares, close, 0, 0, "", "时间止损"))
                continue

            # 止盈检查
            if pos.stop_manager:
                tp_action = pos.stop_manager.check_take_profit(close, pos.target)
                pos.stop = pos.stop_manager.stop
                if tp_action == "TAKE_PROFIT":
                    if pos.shares > 1:
                        half_shares = pos.shares // 2
                        rec = self.pm.partial_exit(ticker, close, half_shares, "TAKE_PROFIT")
                        if rec:
                            self._record_exit(rec)
                            orders.append(Order(ticker, "SELL", half_shares, close, 0, 0, "", "止盈50%"))
                    elif pos.shares == 1:
                        rec = self.pm.exit(ticker, close, "TAKE_PROFIT")
                        if rec:
                            self._record_exit(rec)
                            orders.append(Order(ticker, "SELL", pos.shares, close, 0, 0, "", "止盈（全部）"))

        # ── Step 3: 遍历候选池 → 入场信号检测 ──
        candidates: list[CandidateEntry] = []
        if not self.loss_pause.can_trade():
            return orders

# A股适配：双重时间框架确认 — 日线必须是上升趋势
        csi300_daily_trend = self.csi300_daily_detector.state
        if A_SHARE_DUAL_TF_REQUIRED:
            if csi300_weekly_trend != TrendDirection.UP or csi300_daily_trend != TrendDirection.UP:
                self.pm.clear_trades_today()
                self.pm.increment_bars_held()
                return orders

        # A股适配：现金保留 — 熊市/震荡市强制保留现金比例
        cash_ratio = env_adapt.get("cash_ratio", 0.0)
        if cash_ratio > 0:
            min_cash = self.pm.initial_capital * cash_ratio
            if self.pm.cash < min_cash:
                self.pm.clear_trades_today()
                self.pm.increment_bars_held()
                return orders

        # 日频量能确认 — 全市场缩量日跳过入场
        csi300_vol_today = float(csi300_bar.get("volume", 0))
        if csi300_vol_today > 0 and len(csi300_history) >= 21 and "volume" in csi300_history.columns:
            csi300_vol_20d = csi300_history["volume"].iloc[-21:-1].mean()
            if csi300_vol_20d > 0 and csi300_vol_today < csi300_vol_20d * 0.50:
                self.pm.clear_trades_today()
                self.pm.increment_bars_held()
                return orders

        for ticker, bar in bar_data.items():
            if ticker in self.pm.positions:
                continue  # 已持仓

            close = bar.get("close")

            if pd.isna(close) or close == 0:
                continue

            # A股适配：防追涨 + 涨跌停过滤
            open_p = float(bar.get("open", 0))
            yesterday_close = None
            stock_df = None
            if ticker in self._stock_data:
                stock_df = self._stock_data[ticker]
                if self._current_date is not None:
                    stock_df = stock_df[stock_df.index <= self._current_date]
                if len(stock_df) >= 2:
                    yesterday_close = float(stock_df["close"].iloc[-2])

            if open_p > 0 and yesterday_close is not None and yesterday_close > 0:
                # 当日涨幅 >3% 不追
                if (float(close) - open_p) / open_p > ANTI_CHASE_MAX_INTRADAY:
                    continue
                # 跳空高开 >5% 不追
                if (open_p - yesterday_close) / yesterday_close > ANTI_CHASE_MAX_GAP:
                    continue

            # 涨跌停附近不交易
            if yesterday_close is not None and yesterday_close > 0 and LIMIT_UP_DOWN_PROXIMITY > 0:
                limit_up = yesterday_close * 1.10
                limit_down = yesterday_close * 0.90
                if float(close) >= limit_up * (1 - LIMIT_UP_DOWN_PROXIMITY / 10):
                    continue
                if float(close) <= limit_down * (1 + LIMIT_UP_DOWN_PROXIMITY / 10):
                    continue

            # A股适配：成交量过滤 — 无量上涨不可靠
            if A_SHARE_MIN_VOL_RATIO > 0:
                vol = bar.get("volume")
                if vol is not None and stock_df is not None and len(stock_df) >= 6 and "volume" in stock_df.columns:
                    avg_vol5 = stock_df["volume"].iloc[-6:-1].mean()
                    if avg_vol5 > 0 and float(vol) < avg_vol5 * A_SHARE_MIN_VOL_RATIO:
                        continue

            # 构建 numpy 数组用于信号检测
            hist = self._get_stock_history(ticker, bar_data)
            if hist is None:
                continue

            # 信号检测
            signals = self._detect_signals(hist)
            if not SHORT_ALLOWED:
                signals = [s for s in signals if s.direction > 0]

            rsi_div_mult = RSIDivergence.confirm(hist["close"], hist["high"], hist["low"], 1)
            for s in signals:
                s.confidence = min(s.confidence * rsi_div_mult, 0.95)

            if not signals:
                continue

            # 多层确认
            weekly_trend = csi300_weekly_trend.value if csi300_weekly_trend else "RANGE"
            final_signal = self.consensus.resolve(signals, weekly_trend)
            if final_signal is None or not final_signal.is_valid():
                continue

            # Alpha 因子过滤：低因子得分 = 信号噪声，跳过
            factor_score = self.factor_ranker.rank(ticker, self._stock_data.get(ticker))
            if factor_score < -0.3:
                continue
            if factor_score > 0.3:
                final_signal.confidence = min(final_signal.confidence * 1.15, 0.95)

            # EV / RRR 检查
            entry_price = float(close)
            risk = abs(entry_price - final_signal.stop)
            reward = abs(final_signal.target - entry_price)
            if risk <= 0:
                continue
            rr_ratio = reward / risk
            ev = EVCalculator.ev(final_signal.confidence, reward, risk)
            min_rrr = env_adapt.get("min_rrr", 3.0)
            # 基本面弱时要求更高盈亏比
            if risk_budget < 0.6:
                min_rrr = max(min_rrr, 5.0)
            elif risk_budget < 0.8:
                min_rrr = max(min_rrr, 4.0)
            if rr_ratio < min_rrr or ev <= 0:
                continue

            # 计算头寸
            capital_level = self.capital_mgr.level
            risk_pct = cfg.RISK_PCT
            shares = TieredPositionSizer.size(
                self.capital_mgr.available_risk_base,
                risk_pct,
                float(close),
                final_signal.stop,
            )
            if shares <= 0:
                continue

            # 入场评分用于排序
            entry_score = ev * env_adapt.get("signal_boost", 1.0) * final_signal.confidence
            candidates.append(CandidateEntry(
                ticker=ticker,
                signal=final_signal,
                ev=ev,
                rr_ratio=rr_ratio,
                shares=shares,
                entry_score=entry_score,
            ))

        # ── Step 3.5: 风险分配 ──
        candidates.sort(key=lambda c: c.entry_score, reverse=True)

        for c in candidates:
            if c.ticker in self.pm.positions:
                continue

            close = float(bar_data[c.ticker].get("close", 0))
            if close <= 0:
                continue

            if self.pm.can_enter(c.ticker, c.shares, close, c.signal.stop):
                self.pm.enter(c.ticker, c.shares, close, c.signal.stop, c.signal.target)
                orders.append(Order(
                    ticker=c.ticker,
                    action="BUY",
                    shares=c.shares,
                    price=close,
                    stop=c.signal.stop,
                    target=c.signal.target,
                    signal_type=c.signal.signal_type,
                    reason=f"EV={c.ev:.2f} RRR={c.rr_ratio:.1f}:1",
                ))

        # ── Step 4: 执行订单（出场优先于入场已在上面实现）──
        # ── Step 5: 资本管理 ──
        self.pm.increment_bars_held()
        self.pm.clear_trades_today()

        self._current_date = current_date
        return orders

    def _update_csi300_trend(self, history: pd.DataFrame) -> None:
        """更新沪深 300 多周期趋势（仅初始化一次，然后增量更新）"""
        if history.empty:
            return
        if not self._csi300_initialized:
            for _, row in history.iterrows():
                self.csi300_daily_detector.update(
                    float(row["high"]), float(row["low"]), float(row["close"])
                )
            weekly = self._resample_index_to_weekly(history)
            for _, row in weekly.iterrows():
                self.csi300_weekly_detector.update(
                    float(row["high"]), float(row["low"]), float(row["close"])
                )
            if len(weekly) > 0:
                self._last_weekly_date = weekly.index[-1]
            self._csi300_initialized = True
        else:
            last = history.iloc[-1]
            self.csi300_daily_detector.update(
                float(last["high"]), float(last["low"]), float(last["close"])
            )
            weekly = self._resample_index_to_weekly(history)
            if len(weekly) > 0:
                latest_weekly_date = weekly.index[-1]
                if self._last_weekly_date is None or latest_weekly_date > self._last_weekly_date:
                    last_week_row = weekly.iloc[-1]
                    self.csi300_weekly_detector.update(
                        float(last_week_row["high"]), float(last_week_row["low"]), float(last_week_row["close"])
                    )
                    self._last_weekly_date = latest_weekly_date

    @staticmethod
    def _resample_index_to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
        """将指数日线 resample 为周线"""
        if daily.empty:
            return pd.DataFrame()
        weekly = daily.resample("W-FRI", label="right").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        })
        return weekly.dropna()

    def _get_stock_history(self, ticker: str, bar_data: dict) -> Optional[dict]:
        """获取单只股票历史数据用于信号检测

        从 _stock_data（backtest 注入的完整历史）中取数据，
        只使用截至 current_date 的数据以防前瞻偏差。
        """
        if ticker in self._stock_data:
            df = self._stock_data[ticker]
            if self._current_date is not None:
                df = df[df.index <= self._current_date]
            n = len(df)
            if n >= 5:
                result = {
                    "high": df["high"].values.astype(float),
                    "low": df["low"].values.astype(float),
                    "close": df["close"].values.astype(float),
                    "volume": df["volume"].values.astype(float) if "volume" in df.columns else None,
                }
                return result
        # 回退：只有当日数据
        bar = bar_data.get(ticker)
        if bar is None:
            return None
        return {
            "high": np.array([float(bar.get("high", 0))]),
            "low": np.array([float(bar.get("low", 0))]),
            "close": np.array([float(bar.get("close", 0))]),
            "volume": None,
        }

    def _detect_signals(self, hist: dict) -> list[Signal]:
        signals = []
        high = hist["high"]
        low = hist["low"]
        close = hist["close"]
        volume = hist.get("volume")

        if len(close) < 5:
            return signals

        vol_arr = volume if volume is not None and len(volume) >= 15 else None

        for detector in [
            (Criterion123.detect, True),
            (Criterion2B.detect, True),
            (FourDayRule.detect, True),
            (ThreeDayPullback.detect, True),
            (ABCCorrection.detect, True),
            (NarrowRangeBreakout.detect, True),
        ]:
            try:
                sig = detector[0](high, low, close, vol_arr)
                if sig is not None:
                    signals.append(sig)
            except Exception:
                logger.debug("信号检测异常", exc_info=True)

        return signals

    def _record_exit(self, rec) -> None:
        is_win = rec.pnl > 0
        self.loss_pause.record_result(is_win)
        if is_win:
            self.capital_mgr.lock_profit(rec.pnl)

    def get_summary(self) -> dict:
        """获取策略摘要"""
        return {
            "cash": self.pm.cash,
            "positions": len(self.pm.positions),
            "capital_level": self.capital_mgr.level,
            "trades_total": len(self.pm.trades),
            "regime": self.fundamental.get_regime(),
        }
