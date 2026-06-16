"""市场环境分类器（沪深300）

每一根 K 线分类当前市场环境，输出环境名称和对应的适配参数字典。

7 种环境：
TRENDING_BULL / AGING_BULL / TRENDING_BEAR / RANGE_BOUND /
HIGH_VOL / LOW_VOL / CRISIS
"""

import numpy as np
import pandas as pd

from trader_vic.config import ENV_ADAPTATION, CN_BULL_MEAN_MONTHS
from trader_vic.core.trend import SwingDetector, TrendDirection


class MarketEnvClassifier:
    """沪深 300 环境分类器

    使用沪深 300 指数的日线 + 周线数据判定当前市场环境。
    """

    def __init__(self):
        self._last_classification: str = "RANGE_BOUND"

    @staticmethod
    def _build_swing_state(close, high, low, lookback=10) -> TrendDirection:
        """用给定数据创建临时 SwingDetector 并返回趋势状态"""
        det = SwingDetector(lookback=lookback)
        for i in range(len(close)):
            det.update(float(high[i]), float(low[i]), float(close[i]))
        return det.state

    def classify(
        self,
        csi300_daily: pd.DataFrame,
        csi300_weekly: pd.DataFrame,
    ) -> str:
        """分类当前市场环境

        Args:
            csi300_daily: 沪深 300 日线 DataFrame
            csi300_weekly: 沪深 300 周线 DataFrame

        Returns:
            环境名称
        """
        if csi300_daily.empty:
            return "RANGE_BOUND"

        close = csi300_daily["close"].values
        high = csi300_daily["high"].values
        low = csi300_daily["low"].values
        volume = csi300_daily["volume"].values if "volume" in csi300_daily else None

        # 用完整数据构建 SwingDetector 获取趋势状态（无状态累积）
        daily_state = self._build_swing_state(close, high, low, lookback=10)

        weekly_state = TrendDirection.RANGE
        weekly_close = None
        if csi300_weekly is not None and not csi300_weekly.empty:
            weekly_close = csi300_weekly["close"].values
            wh = csi300_weekly["high"].values
            wl = csi300_weekly["low"].values
            weekly_state = self._build_swing_state(weekly_close, wh, wl, lookback=8)
        current_price = float(close[-1])

        # 1. CRISIS: 三日累计跌幅 > 8%
        if len(close) >= 3:
            three_day_return = (close[-1] - close[-4]) / close[-4] if len(close) >= 4 else 0
            if three_day_return < -0.08:
                self._last_classification = "CRISIS"
                return "CRISIS"

        # 2. 计算均线
        ma120 = float(np.mean(close[-120:])) if len(close) >= 120 else float(np.mean(close))
        ma20 = float(np.mean(close[-20:])) if len(close) >= 20 else current_price
        price_vs_ma120 = current_price / ma120

        # 3. 计算波动率
        atr = self._calc_atr(high, low, close, 20)
        atr_ratio = atr / current_price if current_price > 0 else 0

        # 4. 判断趋势状态
        if weekly_state == TrendDirection.UP or daily_state == TrendDirection.UP:
            # 检查是否为 aging bull
            if weekly_state == TrendDirection.UP and weekly_close is not None:
                trend_age = self._estimate_trend_age(weekly_close)
                if trend_age > CN_BULL_MEAN_MONTHS * 0.8:
                    self._last_classification = "AGING_BULL"
                    return "AGING_BULL"

            if price_vs_ma120 > 0.95:
                # 检查波动率
                if atr_ratio > 0.03:
                    self._last_classification = "HIGH_VOL"
                    return "HIGH_VOL"
                elif price_vs_ma120 > 1.0:
                    self._last_classification = "TRENDING_BULL"
                    return "TRENDING_BULL"
                else:
                    self._last_classification = "LOW_VOL"
                    return "LOW_VOL"

        if weekly_state == TrendDirection.DOWN or daily_state == TrendDirection.DOWN:
            if price_vs_ma120 < 0.95 or daily_state == TrendDirection.DOWN:
                self._last_classification = "TRENDING_BEAR"
                return "TRENDING_BEAR"

        # 5. 波动率特殊判定
        if atr_ratio > 0.035:
            self._last_classification = "HIGH_VOL"
            return "HIGH_VOL"

        if atr_ratio < 0.01:
            self._last_classification = "LOW_VOL"
            return "LOW_VOL"

        self._last_classification = "RANGE_BOUND"
        return "RANGE_BOUND"

    @staticmethod
    def _calc_atr(high, low, close, period=20):
        """计算平均真实波幅"""
        if len(close) < period + 1:
            return 0.0
        tr_values = []
        for i in range(-period, 0):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
            tr_values.append(tr)
        return float(np.mean(tr_values))

    @staticmethod
    def _estimate_trend_age(weekly_close) -> float:
        """粗略估算趋势持续月数（找到最近一次主要折返）"""
        if len(weekly_close) < 10:
            return 0
        # 从最新数据往前找近期低点
        recent = weekly_close[-10:]
        min_idx = int(np.argmin(recent))
        # 趋势持续月数 ≈ 从最低点到现在的周数 / 4.3
        weeks_since = len(recent) - min_idx - 1
        return weeks_since / 4.3

    def get_env_adapt(self, env: str) -> dict:
        """获取环境对应的适配参数"""
        return dict(ENV_ADAPTATION.get(env, ENV_ADAPTATION["RANGE_BOUND"]))
