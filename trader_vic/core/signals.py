"""信号检测模块 — 1-2-3 准则, 2B 准则, 四天准则, 三天回调

所有信号输出统一的 Signal dataclass，供 ConsensusEngine 消费。
信号算法参考 ch07（1-2-3, 2B）、ch27（四天准则）、cheatsheet（三天回调）。
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

import trader_vic.config as cfg


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


def _volume_confirm(volume: Optional[np.ndarray]) -> float:
    """成交量确认：突破日放量 > 5日均量 → 1.15，缩量 < 0.6 × 5日均量 → 0.5

    Returns:
        置信度乘数，< 0.6 表示量能严重不配合
    """
    if volume is None or len(volume) < 6:
        return 1.0
    avg_vol5 = np.mean(volume[-6:-1])
    if avg_vol5 <= 0 or volume[-1] <= 0:
        return 1.0
    ratio = volume[-1] / avg_vol5
    if ratio > 1.5:
        return 1.15
    elif ratio < 0.6:
        return 0.5
    return 1.0


def _find_trendline(prices: np.ndarray, tolerance: float = None) -> Optional[float]:
    if tolerance is None:
        tolerance = cfg.TRENDLINE_TOUCH_TOLERANCE
    if len(prices) < 5:
        return None
    recent = prices[-20:] if len(prices) >= 20 else prices
    n = len(recent)
    x = np.arange(n)
    slope, intercept = np.polyfit(x, recent, 1)
    if abs(slope) < 1e-10:
        return None
    line_vals = slope * x + intercept
    touches = np.sum(np.abs(recent - line_vals) / np.maximum(np.abs(recent), 1e-8) < tolerance)
    if touches < 3:
        return None
    trend_value = slope * (n - 1) + intercept
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
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: Optional[np.ndarray] = None) -> Optional[Signal]:
        if len(close) < 20:
            return None

        for direction in [1, -1]:
            signal = Criterion123._detect_direction(high, low, close, direction, volume)
            if signal is not None:
                return signal
        return None

    @staticmethod
    def _detect_direction(
        high: np.ndarray, low: np.ndarray, close: np.ndarray, direction: int,
        volume: Optional[np.ndarray] = None,
    ) -> Optional[Signal]:
        if direction == 1:
            recent_lows = low[-20:]
            trend_value = _find_trendline(recent_lows)
            if trend_value is None:
                return None
            step1 = close[-1] > trend_value

            recent_min = np.min(low[-10:-1])
            prior_min = np.min(low[-20:-10]) if len(low) >= 20 else recent_min
            step2 = recent_min >= prior_min * (1 - cfg.TRENDLINE_TOUCH_TOLERANCE) and not (close[-1] < prior_min)

            step3 = close[-1] > close[-5] and close[-1] > close[-3]

        else:
            recent_highs = high[-20:]
            trend_value = _find_trendline(recent_highs)
            if trend_value is None:
                return None
            step1 = close[-1] < trend_value

            recent_max = np.max(high[-10:-1])
            prior_max = np.max(high[-20:-10]) if len(high) >= 20 else recent_max
            step2 = recent_max <= prior_max * (1 + cfg.TRENDLINE_TOUCH_TOLERANCE) and not (close[-1] > prior_max)

            step3 = close[-1] < close[-5] and close[-1] < close[-3]

        if not (step1 and step2):
            return None

        vol_confirm = _volume_confirm(volume) if volume is not None and len(volume) >= 6 else 1.0
        if vol_confirm < 0.6:
            return None

        confidence = 0.67 if step3 else 0.50
        confidence = min(confidence * vol_confirm, 0.85)
        signal_type = "123_FULL" if step3 else "123_CONFIRMING"

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
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: Optional[np.ndarray] = None) -> Optional[Signal]:
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
            if current_low < prior_low * (1 - cfg.TWOB_RETRACE_THRESHOLD):
                if close[-1] > prior_low:
                    stop = prior_low * 0.99
                    target = close[-1] + (close[-1] - stop) * 5
                    confidence = min(0.50 * _volume_confirm(volume), 0.70)
                    return Signal(
                        direction=1,
                        confidence=confidence,
                        stop=float(stop),
                        target=float(target),
                        signal_type="2B_MEDIUM",
                    )

        # 空头 2B：假突破向上（价格创新高后立即回到前高下方）
        if len(high) >= 10:
            prior_high = np.max(high[-10:-1])
            current_high = high[-1]
            if current_high > prior_high * (1 + cfg.TWOB_RETRACE_THRESHOLD):
                if close[-1] < prior_high:
                    stop = prior_high * 1.01
                    target = close[-1] - (stop - close[-1]) * 5
                    confidence = min(0.50 * _volume_confirm(volume), 0.70)
                    return Signal(
                        direction=-1,
                        confidence=confidence,
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
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: Optional[np.ndarray] = None) -> Optional[Signal]:
        if len(close) < 6:
            return None

        if len(close) >= 5:
            if all(close[-i] > close[-i-1] for i in range(1, 5)):
                change_4d = (close[-1] - close[-5]) / close[-5]
                if change_4d >= cfg.FOUR_DAY_REVERSAL_THRESHOLD:
                    vol_mult = _volume_confirm(volume)
                    if vol_mult < 0.6:
                        return None
                    stop = max(high[-5:]) * 1.02
                    target = close[-1] - change_4d * close[-5] * 0.5
                    return Signal(
                        direction=-1,
                        confidence=min(0.75 * vol_mult, 0.85),
                        stop=float(stop),
                        target=float(max(target, close[-1] * 0.95)),
                        signal_type="FOUR_DAY_RULE",
                    )

            if all(close[-i] < close[-i-1] for i in range(1, 5)):
                change_4d = (close[-5] - close[-1]) / close[-5]
                if change_4d >= cfg.FOUR_DAY_REVERSAL_THRESHOLD:
                    vol_mult = _volume_confirm(volume)
                    if vol_mult < 0.6:
                        return None
                    stop = min(low[-5:]) * 0.98
                    target = close[-1] + change_4d * close[-5] * 0.5
                    return Signal(
                        direction=1,
                        confidence=min(0.75 * vol_mult, 0.85),
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
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: Optional[np.ndarray] = None) -> Optional[Signal]:
        if len(close) < 25:
            return None

        ma20 = np.mean(close[-20:])
        if close[-1] < ma20:
            return None

        if len(close) < 4:
            return None
        if not (close[-1] < close[-2] < close[-3]):
            return None

        peak = max(close[-10:-3])
        pullback_pct = (peak - close[-1]) / peak
        if pullback_pct < cfg.THREE_DAY_PULLBACK_MIN or pullback_pct > cfg.THREE_DAY_PULLBACK_MAX:
            return None

        if close[-1] < ma20 * 0.98:
            return None

        vol_mult = _volume_confirm(volume)
        if vol_mult < 0.6:
            return None

        stop = min(low[-5:]) * 0.98
        target = close[-1] + (peak - close[-1]) * 2
        return Signal(
            direction=1,
            confidence=min(0.944 * vol_mult, 0.95),
            stop=float(stop),
            target=float(target),
            signal_type="THREE_DAY_PULLBACK",
        )


class ABCCorrection:
    """ABC 三浪修正 C 点入场（ch07）

    上升趋势回调呈 a-b-c 三浪结构，C 点沿主趋势方向建仓。
    a 浪下跌 → b 浪反弹 → c 浪下跌（不破 a 浪底），C 点突破 b 浪高点。
    """

    @staticmethod
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: Optional[np.ndarray] = None) -> Optional[Signal]:
        if len(close) < cfg.ABC_MIN_LOOKBACK:
            return None

        recent_highs = high[-30:]
        a_peak_idx = int(np.argmax(recent_highs))
        a_peak = recent_highs[a_peak_idx]

        post_peak_lows = low[-(30 - a_peak_idx):]
        if len(post_peak_lows) < 5:
            return None
        a_trough = np.min(post_peak_lows[:10])

        a_low_idx = len(close) - len(post_peak_lows) + int(np.argmin(post_peak_lows[:10]))
        if a_low_idx >= len(close) - 3:
            return None
        b_high = np.max(high[a_low_idx:])
        b_retrace = (b_high - a_trough) / (a_peak - a_trough) if a_peak != a_trough else 0

        if not (cfg.ABC_B_RETRACE_MIN < b_retrace < cfg.ABC_B_RETRACE_MAX):
            return None

        c_low = np.min(low[-5:])
        if c_low <= a_trough * 1.01:
            return None

        vol_mult = _volume_confirm(volume)
        if vol_mult < 0.6:
            return None

        if close[-1] > b_high:
            stop = a_trough * 0.98
            target = a_peak + (a_peak - a_trough) * 0.5
            return Signal(
                direction=1,
                confidence=min(0.60 * vol_mult, 0.75),
                stop=float(stop),
                target=float(target),
                signal_type="ABC_C_POINT",
            )

        return None


class NarrowRangeBreakout:
    """窄幅盘整突破（道氏理论 ch04）

    2-3 周窄幅盘整（约 5% 区间），放量突破区间上限 = 承接完成。
    """

    @staticmethod
    def detect(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: Optional[np.ndarray] = None) -> Optional[Signal]:
        if len(close) < cfg.NARROW_RANGE_LOOKBACK:
            return None

        recent_high = np.max(high[-cfg.NARROW_RANGE_LOOKBACK:-1])
        recent_low = np.min(low[-cfg.NARROW_RANGE_LOOKBACK:-1])
        if recent_low <= 0:
            return None

        range_pct = (recent_high - recent_low) / recent_low
        if range_pct > cfg.NARROW_RANGE_MAX_PCT:
            return None

        if close[-1] > recent_high:
            if volume is not None and len(volume) >= cfg.NARROW_RANGE_LOOKBACK:
                recent_vol = np.mean(volume[-cfg.NARROW_RANGE_LOOKBACK:-1])
                today_vol = volume[-1]
                if today_vol > recent_vol * cfg.NARROW_RANGE_VOL_MULT:
                    confidence = 0.70
                else:
                    confidence = 0.55
            else:
                confidence = 0.55

            stop = recent_low * 0.98
            target = close[-1] + (recent_high - recent_low) * 3
            return Signal(
                direction=1,
                confidence=confidence,
                stop=float(stop),
                target=float(target),
                signal_type="NARROW_RANGE_BREAKOUT",
            )

        return None
