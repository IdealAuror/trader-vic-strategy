"""趋势分析模块 — SwingDetector, TrendAge, RetracementLocator, MarketPhase

核心概念（ch04, ch05）:
- 上升趋势 = HH + HL（更高高点 + 更高低点）
- 下降趋势 = LH + LL（更低高点 + 更低低点）
- 三种时间框架：长期（周线）、中期（日线）、短期（小时线）
- 市场四阶段：承接→上升→出货→下降
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
from scipy.stats import norm

from trader_vic.config import CN_BULL_MEAN_MONTHS, CN_BULL_STD_MONTHS
from trader_vic.config import CN_BEAR_MEAN_MONTHS, CN_BEAR_STD_MONTHS


class TrendDirection(Enum):
    UP = "UP"
    DOWN = "DOWN"
    RANGE = "RANGE"
    UNDEFINED = "UNDEFINED"


class MarketPhaseType(Enum):
    ACCUMULATION = "ACCUMULATION"   # 承接
    MARKUP = "MARKUP"               # 上升
    DISTRIBUTION = "DISTRIBUTION"   # 出货
    MARKDOWN = "MARKDOWN"           # 下降


@dataclass
class SwingPoint:
    """摆动点"""
    index: int
    price: float
    is_high: bool  # True = 高点, False = 低点


class SwingDetector:
    """HH/HL/LH/LL 状态机

    时间框架无关（周线/日线均可使用同一实例）。
    逐K线增量处理，无前瞻偏差。

    用法:
        detector = SwingDetector(lookback=10)
        state = detector.update(high, low, close)  # UP/DOWN/RANGE
    """

    def __init__(self, lookback: int = 10):
        self.lookback = lookback
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._swing_highs: list[SwingPoint] = []
        self._swing_lows: list[SwingPoint] = []
        self._state: TrendDirection = TrendDirection.UNDEFINED

    def _find_pivot_highs(self) -> list[SwingPoint]:
        """在最近 lookback*2 根 K 线中找摆动高点

        摆动高点定义：当前 high 是左右各 lookback 根 K 线中的最高值。
        """
        pivots = []
        n = len(self._highs)
        if n < self.lookback * 2 + 1:
            return pivots
        start = max(0, n - self.lookback * 4)
        for i in range(start + self.lookback, n - self.lookback):
            window = self._highs[i - self.lookback : i + self.lookback + 1]
            if self._highs[i] == max(window):
                # 避免同一区域重复标记
                if not pivots or i - pivots[-1].index >= self.lookback:
                    pivots.append(SwingPoint(i, self._highs[i], True))
        return pivots

    def _find_pivot_lows(self) -> list[SwingPoint]:
        """找摆动低点"""
        pivots = []
        n = len(self._lows)
        if n < self.lookback * 2 + 1:
            return pivots
        start = max(0, n - self.lookback * 4)
        for i in range(start + self.lookback, n - self.lookback):
            window = self._lows[i - self.lookback : i + self.lookback + 1]
            if self._lows[i] == min(window):
                if not pivots or i - pivots[-1].index >= self.lookback:
                    pivots.append(SwingPoint(i, self._lows[i], False))
        return pivots

    def _determine_state(self) -> TrendDirection:
        """根据最近摆动点判断趋势方向

        主方法：使用 HH/HL 摆动点判定。
        回退方法（摆动点不足时）：使用 SMA 斜率比较。
        """
        high_pivots = self._find_pivot_highs()
        low_pivots = self._find_pivot_lows()

        # 主方法：有足够的摆动点
        if len(high_pivots) >= 2 and len(low_pivots) >= 2:
            recent_highs = high_pivots[-3:]
            recent_lows = low_pivots[-3:]

            hh = len(recent_highs) >= 2 and recent_highs[-1].price > recent_highs[-2].price
            hl = len(recent_lows) >= 2 and recent_lows[-1].price > recent_lows[-2].price
            lh = len(recent_highs) >= 2 and recent_highs[-1].price < recent_highs[-2].price
            ll = len(recent_lows) >= 2 and recent_lows[-1].price < recent_lows[-2].price

            if hh and hl:
                return TrendDirection.UP
            elif lh and ll:
                return TrendDirection.DOWN
            elif hh and ll:
                return TrendDirection.RANGE
            else:
                return TrendDirection.RANGE

        # 回退方法：摆动点不足，使用 SMA 斜率
        return self._fallback_trend()

    def _fallback_trend(self) -> TrendDirection:
        """SMA 斜率回退趋势检测

        当摆动点不足时使用。对短数据也能工作。
        """
        if len(self._closes) < 5:
            return TrendDirection.UNDEFINED

        close = np.array(self._closes)
        n = len(close)

        # 自适应长期窗口：最多 20，最少 5
        long_period = min(20, n)
        sma_short = np.mean(close[-5:])
        sma_long = np.mean(close[-long_period:])

        # 比较 SMA
        if sma_short > sma_long * 1.01:
            return TrendDirection.UP
        elif sma_short < sma_long * 0.99:
            return TrendDirection.DOWN
        else:
            return TrendDirection.RANGE

    def update(self, high: float, low: float, close: float) -> TrendDirection:
        """输入一根新 K 线，返回当前趋势方向"""
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)

        # 只保留最近 200 根
        max_len = max(self.lookback * 20, 200)
        if len(self._highs) > max_len:
            self._highs = self._highs[-max_len:]
            self._lows = self._lows[-max_len:]
            self._closes = self._closes[-max_len:]

        if len(self._highs) >= self.lookback * 2 + 1:
            self._state = self._determine_state()

        return self._state

    def get_swing_points(self) -> tuple[list[SwingPoint], list[SwingPoint]]:
        """获取当前摆动高点和低点列表"""
        return self._find_pivot_highs(), self._find_pivot_lows()

    @property
    def state(self) -> TrendDirection:
        return self._state

    @property
    def last_high(self) -> float | None:
        return self._highs[-1] if self._highs else None

    @property
    def last_low(self) -> float | None:
        return self._lows[-1] if self._lows else None


class TrendAge:
    """趋势历史统计定位（ch04, ch11）

    用 z-score 正态 CDF 计算当前趋势在历史分布中的百分位。
    使用 A 股统计参数（沪深300：牛市均值 14 月，熊市均值 7 月）。
    """

    def __init__(self):
        self._start_date: pd.Timestamp | None = None
        self._direction: TrendDirection = TrendDirection.UNDEFINED

    def start_trend(self, date: pd.Timestamp, direction: TrendDirection) -> None:
        """记录趋势开始"""
        self._start_date = date
        self._direction = direction

    def percentile(self, current_date: pd.Timestamp, direction: TrendDirection) -> float:
        """计算趋势年龄在历史分布中的百分位

        Returns:
            0~1 的百分位值，>0.50 = 超过历史均值，>0.84 = 超过 1 个标准差
        """
        if self._start_date is None:
            return 0.0

        elapsed_months = (current_date - self._start_date).days / 30.44

        if direction in (TrendDirection.UP,):
            mean = CN_BULL_MEAN_MONTHS
            std = CN_BULL_STD_MONTHS
        elif direction in (TrendDirection.DOWN,):
            mean = CN_BEAR_MEAN_MONTHS
            std = CN_BEAR_STD_MONTHS
        else:
            return 0.5

        if std <= 0:
            return 0.5

        z = (elapsed_months - mean) / std
        return float(norm.cdf(z))


class RetracementLocator:
    """次级折返定位（道氏定理五）

    折返幅度 = 前一波段的 1/3 ~ 2/3
    折返持续 = 3 周 ~ 3 个月
    """

    @staticmethod
    def retracement_ratio(
        swing_high: float, swing_low: float, current_price: float
    ) -> float:
        """计算当前价格在波段中的折返比例

        返回 0~1 之间的比例：
        - < 0.33: 可能还不是折返末端
        - 0.33~0.66: 次级折返合理范围
        - > 0.66: 可能不是折返而是反转
        """
        if swing_high == swing_low:
            return 0.5
        range_size = swing_high - swing_low
        if range_size == 0:
            return 0.5
        retrace = (current_price - swing_low) / range_size
        return float(np.clip(retrace, 0, 1))

    @staticmethod
    def is_healthy_retracement(retrace_ratio: float) -> bool:
        """判断折返是否处于健康范围（1/3 ~ 2/3）"""
        return 0.33 <= retrace_ratio <= 0.66

    @staticmethod
    def bars_since_start(bars_held: int) -> bool:
        """判断持续天数是否在折返合理范围（3 周 ~ 3 个月）"""
        return 15 <= bars_held <= 66  # ~ 交易日


class MarketPhase:
    """市场四阶段（ch05）

    承接(ACCUMULATION) → 上升(MARKUP) → 出货(DISTRIBUTION) → 下降(MARKDOWN)
    """

    @staticmethod
    def phase(
        swing_state: TrendDirection,
        volume_trend: str | None = None,
        price_vs_ma: float | None = None,
    ) -> MarketPhaseType:
        """判断当前市场阶段

        Args:
            swing_state: SwingDetector 的输出
            volume_trend: "INCREASING" | "DECREASING" | "FLAT" | None
            price_vs_ma: 价格 / MA200，>1 表示在均线上方

        Returns:
            当前市场阶段
        """
        if swing_state == TrendDirection.UP:
            if volume_trend == "INCREASING" or price_vs_ma is None:
                return MarketPhaseType.MARKUP
            elif volume_trend == "DECREASING":
                # 上涨但量缩 — 可能接近出货
                return MarketPhaseType.DISTRIBUTION
            else:
                return MarketPhaseType.MARKUP

        elif swing_state == TrendDirection.DOWN:
            if price_vs_ma is not None and price_vs_ma < 0.85:
                return MarketPhaseType.MARKDOWN
            elif volume_trend == "INCREASING":
                # 下跌放量 — 恐慌出清，可能接近承接
                return MarketPhaseType.ACCUMULATION
            else:
                return MarketPhaseType.MARKDOWN

        else:  # RANGE or UNDEFINED
            if price_vs_ma is not None and price_vs_ma > 0.95:
                return MarketPhaseType.DISTRIBUTION
            elif price_vs_ma is not None and price_vs_ma < 0.85:
                return MarketPhaseType.ACCUMULATION
            else:
                return MarketPhaseType.ACCUMULATION
