"""信号检测模块 — 1-2-3 准则, 2B 准则, 四天准则, 三天回调

所有信号输出统一的 Signal dataclass，供 ConsensusEngine 消费。
信号算法参考 ch07（1-2-3, 2B）、ch27（四天准则）、cheatsheet（三天回调）。
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from trader_vic.config import (
    TRENDLINE_TOUCH_TOLERANCE,
    TWOB_RETRACE_THRESHOLD,
    FOUR_DAY_LOOKBACK,
    FOUR_DAY_REVERSAL_THRESHOLD,
    THREE_DAY_PULLBACK_MIN,
    THREE_DAY_PULLBACK_MAX,
)


@dataclass
class Signal:
    """统一信号数据结构"""
    direction: int         # 1 = 做多, -1 = 做空
    confidence: float      # 0~1 置信度
    stop: float            # 止损价
    target: float          # 目标价
    signal_type: str       # 信号类型标识

    def is_valid(self) -> bool:
        return self.confidence > 0 and self.stop > 0 and self.target > 0


def _linear_regression_slope(y: np.ndarray) -> float:
    """计算线性回归斜率（用于趋势线）"""
    x = np.arange(len(y))
    if len(x) < 2:
        return 0.0
    slope, _ = np.polyfit(x, y, 1)
    return slope


def _find_trendline(prices: np.ndarray, tolerance: float = TRENDLINE_TOUCH_TOLERANCE) -> Optional[float]:
    """找到一条至少接触 3 个点的趋势线

    用线性回归拟合趋势线，返回趋势线在当前最新点的值。
    """
    if len(prices) < 5:
        return None
    recent = prices[-20:] if len(prices) >= 20 else prices
    x = np.arange(len(recent))
    slope, intercept = np.polyfit(x, recent, 1)
    if abs(slope) < 1e-10:
        return None
    # 趋势线在最新点的值 = slope * (n-1) + intercept
    trend_value = slope * (len(recent) - 1) + intercept
    return float(trend_value)


class Criterion123:
    """1-2-3 准则 — 三步趋势反转确认（ch07）

    步骤1: 趋势线被穿越
    步骤2: 价格测试前期极点但未创新高/新低
    步骤3: 价格朝突破方向运行

    仅步骤1+2 = 较低可靠度 (50%)
    三步全满足 = 较高可靠度 (67%)
    """

    @staticmethod
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Optional[Signal]:
        """检测 1-2-3 准则

        Args:
            high: 高点序列（最近至少 30 根）
            low: 低点序列
            close: 收盘价序列

        Returns:
            Signal 或 None
        """
        if len(close) < 20:
            return None

        # 检测上升趋势中的 1-2-3 反转（做空信号）
        # 和下降趋势中的 1-2-3 反转（做多信号）
        for direction in [1, -1]:
            signal = Criterion123._detect_direction(high, low, close, direction)
            if signal is not None:
                return signal
        return None

    @staticmethod
    def _detect_direction(
        high: np.ndarray, low: np.ndarray, close: np.ndarray, direction: int
    ) -> Optional[Signal]:
        """检测特定方向的 1-2-3

        direction=1: 做多（下降趋势反转向上）
        direction=-1: 做空（上升趋势反转向下）
        """
        if direction == 1:
            # 做多：寻找下降趋势被突破
            # 步骤1: 下降趋势线被向上穿越
            recent_lows = low[-20:]
            trend_value = _find_trendline(recent_lows)
            if trend_value is None:
                return None
            step1 = close[-1] > trend_value

            # 步骤2: 价格回测前期低点但未创新低
            recent_min = np.min(low[-10:-1])
            prior_min = np.min(low[-20:-10]) if len(low) >= 20 else recent_min
            step2 = recent_min >= prior_min * (1 - TRENDLINE_TOUCH_TOLERANCE) and not (close[-1] < prior_min)

            # 步骤3: 价格朝突破方向运行
            step3 = close[-1] > close[-5] and close[-1] > close[-3]

        else:
            # 做空：寻找上升趋势被向下跌破
            recent_highs = high[-20:]
            trend_value = _find_trendline(recent_highs)
            if trend_value is None:
                return None
            step1 = close[-1] < trend_value

            recent_max = np.max(high[-10:-1])
            prior_max = np.max(high[-20:-10]) if len(high) >= 20 else recent_max
            step2 = recent_max <= prior_max * (1 + TRENDLINE_TOUCH_TOLERANCE) and not (close[-1] > prior_max)

            step3 = close[-1] < close[-5] and close[-1] < close[-3]

        if not (step1 and step2):
            return None

        # 只有 step1+2: 50% 置信度
        # step1+2+3: 67% 置信度
        confidence = 0.67 if step3 else 0.50
        signal_type = "123_FULL" if step3 else "123_CONFIRMING"

        # 止损和目标
        if direction == 1:
            stop = np.min(low[-10:]) * 0.99
            target = close[-1] + (close[-1] - stop) * 3
        else:
            stop = np.max(high[-10:]) * 1.01
            target = close[-1] - (stop - close[-1]) * 3

        return Signal(
            direction=direction,
            confidence=confidence,
            stop=float(stop),
            target=float(target),
            signal_type=signal_type,
        )


class Criterion2B:
    """2B 准则 — 假突破识别（ch07）

    价格创新高/新低后立即折返，收盘价回到前期极点以内。
    极小止损设在前期极点外侧。
    """

    @staticmethod
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Optional[Signal]:
        """检测 2B 准则

        Returns:
            Signal（空头：假突破向上，做空；多头：假突破向下，做多）或 None
        """
        if len(close) < 15:
            return None

        # 多头 2B：假突破向下（价格创新低后立即回到前低上方）
        if len(low) >= 10:
            prior_low = np.min(low[-10:-1])
            current_low = low[-1]
            # 创新低（假突破）
            if current_low < prior_low * (1 - TWOB_RETRACE_THRESHOLD):
                # 立即回到前低上方
                if close[-1] > prior_low:
                    stop = prior_low * 0.99
                    target = close[-1] + (close[-1] - stop) * 5  # 2B 盈亏比 ≥ 1:5
                    return Signal(
                        direction=1,
                        confidence=0.50,
                        stop=float(stop),
                        target=float(target),
                        signal_type="2B_MEDIUM",
                    )

        # 空头 2B：假突破向上（价格创新高后立即回到前高下方）
        if len(high) >= 10:
            prior_high = np.max(high[-10:-1])
            current_high = high[-1]
            if current_high > prior_high * (1 + TWOB_RETRACE_THRESHOLD):
                if close[-1] < prior_high:
                    stop = prior_high * 1.01
                    target = close[-1] - (stop - close[-1]) * 5
                    return Signal(
                        direction=-1,
                        confidence=0.50,
                        stop=float(stop),
                        target=float(target),
                        signal_type="2B_MEDIUM",
                    )

        return None


class FourDayRule:
    """四天准则（ch27）

    1926-1985 道指统计：75% 在 24 天内反转。
    当价格连续 4 天朝同一方向运行后，在 24 天内反转概率 75%。
    """

    @staticmethod
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Optional[Signal]:
        """检测四天准则

        连续 4 天上涨 → 做空信号
        连续 4 天下跌 → 做多信号
        """
        if len(close) < 6:
            return None

        # 检测连续 4 天上涨
        if len(close) >= 5:
            if all(close[-i] > close[-i-1] for i in range(1, 5)):
                # 已连续涨 4 天
                change_4d = (close[-1] - close[-5]) / close[-5]
                if change_4d >= FOUR_DAY_REVERSAL_THRESHOLD:
                    stop = max(high[-5:]) * 1.02
                    target = close[-1] - change_4d * close[-5] * 0.5
                    return Signal(
                        direction=-1,
                        confidence=0.75,
                        stop=float(stop),
                        target=float(max(target, close[-1] * 0.95)),
                        signal_type="FOUR_DAY_RULE",
                    )

            # 检测连续 4 天下跌
            if all(close[-i] < close[-i-1] for i in range(1, 5)):
                change_4d = (close[-5] - close[-1]) / close[-5]
                if change_4d >= FOUR_DAY_REVERSAL_THRESHOLD:
                    stop = min(low[-5:]) * 0.98
                    target = close[-1] + change_4d * close[-5] * 0.5
                    return Signal(
                        direction=1,
                        confidence=0.75,
                        stop=float(stop),
                        target=float(min(target, close[-1] * 1.05)),
                        signal_type="FOUR_DAY_RULE",
                    )

        return None


class ThreeDayPullback:
    """三天回调买入（cheatsheet）

    多头趋势中的三天回调，胜率 94.4%。
    """

    @staticmethod
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Optional[Signal]:
        """检测三天回调买入信号

        条件：
        1. 处于多头趋势（价格在 MA20 上方）
        2. 连续 3 天回调
        3. 回调幅度在 2%~10% 之间
        """
        if len(close) < 25:
            return None

        # 检查多头趋势：价格在 MA20 上方
        ma20 = np.mean(close[-20:])
        if close[-1] < ma20:
            return None

        # 检查连续 3 天回调
        if len(close) < 4:
            return None
        if not (close[-1] < close[-2] < close[-3]):
            return None

        # 回调幅度
        peak = max(close[-10:-3])
        pullback_pct = (peak - close[-1]) / peak
        if pullback_pct < THREE_DAY_PULLBACK_MIN or pullback_pct > THREE_DAY_PULLBACK_MAX:
            return None

        # 回调出现在 MA20 上方（确认是回调而非反转）
        if close[-1] < ma20 * 0.98:
            return None

        stop = min(low[-5:]) * 0.98
        target = close[-1] + (peak - close[-1]) * 2
        return Signal(
            direction=1,
            confidence=0.944,
            stop=float(stop),
            target=float(target),
            signal_type="THREE_DAY_PULLBACK",
        )
