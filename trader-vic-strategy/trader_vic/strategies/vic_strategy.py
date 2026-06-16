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

from trader_vic.config import WATCHLIST, SIGNAL_PROBABILITIES, RISK_PCT
from trader_vic.core.trend import SwingDetector, TrendAge, TrendDirection
from trader_vic.core.signals import Criterion123, Criterion2B, FourDayRule, ThreeDayPullback, Signal
from trader_vic.core.probability import EVCalculator
from trader_vic.core.fundamental_regime import FundamentalRegime
from trader_vic.core.consensus import ConsensusEngine, DowConfirmation
from trader_vic.core.risk import TimeStop, ConsecutiveLossPause
from trader_vic.core.capital import CapitalManager, TieredPositionSizer
from trader_vic.core.market_env import MarketEnvClassifier
from trader_vic.portfolio.mgr import PortfolioMgr, Position


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

        # 多周期 SwingDetector（CSI300 级别）
        self.csi300_weekly_detector = SwingDetector(lookback=8)
        self.csi300_daily_detector = SwingDetector(lookback=10)
        self._csi300_initialized = False  # 防重复初始化

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
            self.fundamental.update(current_date)
            self._monthly_update_done = True
        if current_date.day > 20:
            self._monthly_update_done = False  # 下个月重置

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
        env = self.env_classifier.classify(csi300_history, weekly_df)
        env_adapt = self.env_classifier.get_env_adapt(env)
        self.pm.set_position_cap(env_adapt.get("position_cap", 1.0))
        self.consensus.set_environment(env_adapt)
        self.consensus.set_fundamental(self.fundamental.get_regime())

        # 道氏确认
        dow_dir = None
        if sh_index_history is not None:
            sh_weekly = self._resample_index_to_weekly(sh_index_history)
            sh_detector = SwingDetector(lookback=8)
            for i in range(len(sh_weekly)):
                row = sh_weekly.iloc[i]
                sh_detector.update(float(row["high"]), float(row["low"]), float(row["close"]))
            dow_dir = DowConfirmation.check(
                csi300_weekly_trend.value if csi300_weekly_trend else "RANGE",
                sh_detector.state.value if sh_detector.state else None,
            )
            if dow_dir is not None:
                self.consensus.set_dow_confirmation(dow_dir)

        # ── Step 1.8: 个股多周期趋势 ──
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
                # 同步更新组合管理器的止损
                pos.stop = pos.stop_manager.stop

                if action == "STOP_HIT":
                    rec = self.pm.exit(ticker, low, "STOP_HIT")
                    if rec:
                        self.loss_pause.record_result(rec.pnl > 0)
                        orders.append(Order(ticker, "SELL", pos.shares, low, 0, 0, "", "鳄鱼原则止损"))
                    continue

            # 时间止损
            if TimeStop.check(pos.bars_held):
                rec = self.pm.exit(ticker, close, "TIME_EXIT")
                if rec:
                    orders.append(Order(ticker, "SELL", pos.shares, close, 0, 0, "", "时间止损"))
                continue

            # 止盈检查
            if pos.stop_manager and hasattr(pos, 'target'):
                tp_action = pos.stop_manager.check_take_profit(close, pos.target)
                if tp_action == "TAKE_PROFIT":
                    half_shares = pos.shares // 2
                    if half_shares > 0:
                        # 平 50%
                        rec = self.pm.exit(ticker, close, "TAKE_PROFIT")
                        if rec:
                            orders.append(Order(ticker, "SELL", half_shares, close, 0, 0, "", "止盈50%"))

        # ── Step 3: 遍历候选池 → 入场信号检测 ──
        candidates: list[CandidateEntry] = []
        if not self.loss_pause.can_trade():
            return orders  # 连续亏损暂停中

        for ticker, bar in bar_data.items():
            if ticker in self.pm.positions:
                continue  # 已持仓

            high = bar.get("high")
            low = bar.get("low")
            close = bar.get("close")

            if pd.isna(close) or close == 0:
                continue

            # 构建 numpy 数组用于信号检测
            hist = self._get_stock_history(ticker, bar_data)
            if hist is None:
                continue

            # 信号检测
            signals = self._detect_signals(hist)

            # 多层确认
            weekly_trend = csi300_weekly_trend.value if csi300_weekly_trend else "RANGE"
            final_signal = self.consensus.resolve(signals, weekly_trend)
            if final_signal is None or not final_signal.is_valid():
                continue

            # EV / RRR 检查
            entry_price = float(close)
            risk = abs(entry_price - final_signal.stop)
            reward = abs(final_signal.target - entry_price)
            if risk <= 0:
                continue
            rr_ratio = reward / risk
            ev = EVCalculator.ev(final_signal.confidence, reward, risk)
            min_rrr = env_adapt.get("min_rrr", 3.0)
            if rr_ratio < min_rrr or ev <= 0:
                continue

            # 计算头寸
            capital_level = self.capital_mgr.level
            risk_pct = RISK_PCT  # 单笔风险比例 2%
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
            # 首次：全量处理
            for _, row in history.iterrows():
                self.csi300_daily_detector.update(
                    float(row["high"]), float(row["low"]), float(row["close"])
                )
            weekly = self._resample_index_to_weekly(history)
            for _, row in weekly.iterrows():
                self.csi300_weekly_detector.update(
                    float(row["high"]), float(row["low"]), float(row["close"])
                )
            self._csi300_initialized = True
        else:
            # 增量：只处理最新的一个日线 bar
            last = history.iloc[-1]
            self.csi300_daily_detector.update(
                float(last["high"]), float(last["low"]), float(last["close"])
            )

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
                return {
                    "high": df["high"].values.astype(float),
                    "low": df["low"].values.astype(float),
                    "close": df["close"].values.astype(float),
                }
        # 回退：只有当日数据
        bar = bar_data.get(ticker)
        if bar is None:
            return None
        return {
            "high": np.array([float(bar.get("high", 0))]),
            "low": np.array([float(bar.get("low", 0))]),
            "close": np.array([float(bar.get("close", 0))]),
        }

    def _detect_signals(self, hist: dict) -> list[Signal]:
        """检测所有信号"""
        signals = []
        high = hist["high"]
        low = hist["low"]
        close = hist["close"]

        if len(close) < 5:
            return signals

        # 每个信号独立检测
        for detector in [
            Criterion123.detect,
            Criterion2B.detect,
            FourDayRule.detect,
            ThreeDayPullback.detect,
        ]:
            try:
                sig = detector(high, low, close)
                if sig is not None:
                    signals.append(sig)
            except Exception:
                pass

        return signals

    def get_summary(self) -> dict:
        """获取策略摘要"""
        return {
            "cash": self.pm.cash,
            "positions": len(self.pm.positions),
            "capital_level": self.capital_mgr.level,
            "trades_total": len(self.pm.trades),
            "regime": self.fundamental.get_regime(),
        }
