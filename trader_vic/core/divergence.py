"""RSI 背离检测 — 斯波朗迪震荡指标辅助确认（ch08, ch27）

只做背离确认，不独立产生交易信号。
价格创新高/低但 RSI 未确认 → 趋势衰竭警告。
"""

import numpy as np


def _compute_rsi_series(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    if n < period + 1:
        return np.full(n, 50.0)
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.zeros(n)
    avg_loss = np.zeros(n)
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])
    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi[:period] = 50.0
    return rsi


def _find_swing_points(values: np.ndarray, lookback: int = 5) -> tuple[list, list]:
    """在序列中找局部高点和低点"""
    highs = []
    lows = []
    n = len(values)
    if n < lookback * 2 + 1:
        return highs, lows
    for i in range(lookback, n - lookback):
        window = values[i - lookback : i + lookback + 1]
        if values[i] == max(window):
            if not highs or i - highs[-1][0] >= lookback:
                highs.append((i, values[i]))
        if values[i] == min(window):
            if not lows or i - lows[-1][0] >= lookback:
                lows.append((i, values[i]))
    return highs, lows


class RSIDivergence:
    """RSI 背离检测器（ch08 震荡指标辅助确认）

    用法:
        div = RSIDivergence.detect(close, high, low)
        if div == "bullish":  # 底背离 — 价格新低但 RSI 未确认
            ...
    """

    @staticmethod
    def detect(
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        period: int = 14,
        lookback: int = 20,
    ) -> str:
        """检测 RSI 背离

        Returns:
            "bullish"  — 底背离：价格创新低而 RSI 未确认，下跌动能衰竭
            "bearish" — 顶背离：价格创新高而 RSI 未确认，上涨动能衰竭
            "neutral" — 无背离
        """
        n = len(close)
        if n < lookback + period:
            return "neutral"

        rsi = _compute_rsi_series(close, period)
        recent_close = close[-lookback:]
        recent_rsi = rsi[-lookback:]
        recent_high = high[-lookback:]
        recent_low = low[-lookback:]

        price_highs, _ = _find_swing_points(recent_high, lookback=3)
        _, price_lows = _find_swing_points(recent_low, lookback=3)
        rsi_highs, _ = _find_swing_points(recent_rsi, lookback=3)
        _, rsi_lows = _find_swing_points(recent_rsi, lookback=3)

        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            ph2, ph1 = price_highs[-2][1], price_highs[-1][1]
            rh2, rh1 = rsi_highs[-2][1], rsi_highs[-1][1]
            if ph1 > ph2 and rh1 < rh2:
                return "bearish"

        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            pl2, pl1 = price_lows[-2][1], price_lows[-1][1]
            rl2, rl1 = rsi_lows[-2][1], rsi_lows[-1][1]
            if pl1 < pl2 and rl1 > rl2:
                return "bullish"

        return "neutral"

    @staticmethod
    def confirm(
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        signal_direction: int,
    ) -> float:
        """用 RSI 背离确认信号方向

        Args:
            signal_direction: 1 做多, -1 做空

        Returns:
            置信度乘数: 1.0 中性, 1.15 同向确认, 0.6 背离否定
        """
        div = RSIDivergence.detect(close, high, low)

        if div == "neutral":
            return 1.0

        if signal_direction == 1:
            if div == "bullish":
                return 1.15
            elif div == "bearish":
                return 0.6

        elif signal_direction == -1:
            if div == "bearish":
                return 1.15
            elif div == "bullish":
                return 0.6

        return 1.0
