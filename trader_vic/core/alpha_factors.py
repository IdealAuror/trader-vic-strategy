"""Alpha 因子计算 — A股量价因子子集

从 Qlib Alpha158 中选取最有效的 20 个因子，基于 OHLCV 直接计算。
每个因子在截面上做排名，输出复合 z-score 用于信号过滤。

因子分组：
- 动量 (momentum): 短期/中期/长期收益率
- 反转 (reversal): 短期反转效应
- 波动 (volatility): 波动率指标
- 量价 (volume): 成交量相关
- 趋势 (trend): 均线偏离、趋势强度
"""

import numpy as np
import pandas as pd


class AlphaFactors:
    """A股量价 Alpha 因子计算器

    输入单只股票的 OHLCV DataFrame，输出因子值字典。
    截面排名由 FactorRanker 统一处理。
    """

    @staticmethod
    def momentum_5d(close: np.ndarray) -> float:
        if len(close) < 6:
            return 0.0
        return float(close[-1] / close[-6] - 1)

    @staticmethod
    def momentum_10d(close: np.ndarray) -> float:
        if len(close) < 11:
            return 0.0
        return float(close[-1] / close[-11] - 1)

    @staticmethod
    def momentum_20d(close: np.ndarray) -> float:
        if len(close) < 21:
            return 0.0
        return float(close[-1] / close[-21] - 1)

    @staticmethod
    def momentum_60d(close: np.ndarray) -> float:
        if len(close) < 61:
            return 0.0
        return float(close[-1] / close[-61] - 1)

    @staticmethod
    def reversal_5d(close: np.ndarray) -> float:
        """5日反转：近期跌则预期反弹（负相关）"""
        if len(close) < 6:
            return 0.0
        return -float(close[-1] / close[-6] - 1)

    @staticmethod
    def volatility_20d(close: np.ndarray) -> float:
        if len(close) < 22:
            return 0.0
        rets = np.diff(close[-22:]) / close[-22:-1]
        return float(np.std(rets))

    @staticmethod
    def atr_ratio_14d(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> float:
        n = min(15, len(close))
        if n < 3:
            return 0.0
        trs = []
        for i in range(-(n-1), 0):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
            trs.append(tr)
        atr = np.mean(trs)
        return float(atr / close[-1]) if close[-1] > 0 else 0.0

    @staticmethod
    def volume_ratio_5_20(volume: np.ndarray) -> float:
        if len(volume) < 21:
            return 1.0
        v5 = np.mean(volume[-5:])
        v20 = np.mean(volume[-20:])
        return float(v5 / v20) if v20 > 0 else 1.0

    @staticmethod
    def volume_trend_10d(volume: np.ndarray) -> float:
        """10日量能趋势：放量=+，缩量=-"""
        if len(volume) < 11:
            return 0.0
        recent = np.mean(volume[-5:])
        prior = np.mean(volume[-10:-5])
        return float((recent - prior) / prior) if prior > 0 else 0.0

    @staticmethod
    def volume_price_corr_10d(close: np.ndarray, volume: np.ndarray) -> float:
        """量价相关性：正=量价配合，负=背离"""
        n = min(11, len(close), len(volume))
        if n < 6:
            return 0.0
        c = close[-n:]
        v = volume[-n:]
        if np.std(c) == 0 or np.std(v) == 0:
            return 0.0
        return float(np.corrcoef(c, v)[0, 1])

    @staticmethod
    def turnover_stability_20d(turnover: np.ndarray) -> float:
        """换手率稳定性：CV 越低越稳定"""
        if len(turnover) < 21:
            return 0.0
        t = turnover[-20:]
        if np.mean(t) <= 0:
            return 0.0
        return -float(np.std(t) / np.mean(t))

    @staticmethod
    def ma_deviation_20d(close: np.ndarray) -> float:
        """价格偏离 20 日均线"""
        if len(close) < 21:
            return 0.0
        ma20 = np.mean(close[-20:])
        if ma20 <= 0:
            return 0.0
        return float(close[-1] / ma20 - 1)

    @staticmethod
    def ma_deviation_60d(close: np.ndarray) -> float:
        if len(close) < 61:
            return 0.0
        ma60 = np.mean(close[-60:])
        if ma60 <= 0:
            return 0.0
        return float(close[-1] / ma60 - 1)

    @staticmethod
    def max_drawdown_20d(close: np.ndarray) -> float:
        if len(close) < 21:
            return 0.0
        c = close[-20:]
        peak = np.maximum.accumulate(c)
        dd = (c - peak) / peak
        return -float(np.min(dd))

    @staticmethod
    def up_days_ratio_20d(close: np.ndarray) -> float:
        """20 日中上涨天数占比"""
        if len(close) < 21:
            return 0.5
        rets = np.diff(close[-21:])
        return float(np.mean(rets > 0))

    @staticmethod
    def amplitude_20d(high: np.ndarray, low: np.ndarray) -> float:
        """20 日平均振幅"""
        n = min(21, len(high), len(low))
        if n < 2:
            return 0.0
        amps = (high[-n:] - low[-n:]) / low[-n:]
        return float(np.mean(amps[np.isfinite(amps)]))

    @staticmethod
    def rsi_14d(close: np.ndarray) -> float:
        if len(close) < 16:
            return 50.0
        deltas = np.diff(close[-15:])
        gains = np.sum(deltas[deltas > 0]) if np.any(deltas > 0) else 0
        losses = -np.sum(deltas[deltas < 0]) if np.any(deltas < 0) else 0
        if losses == 0:
            return 100.0
        rs = gains / losses
        return float(100 - 100 / (1 + rs))

    @staticmethod
    def close_position_20d(close: np.ndarray) -> float:
        """收盘价在 20 日范围内位置：高=近高点，低=近低点"""
        if len(close) < 21:
            return 0.5
        h = np.max(close[-20:])
        l = np.min(close[-20:])
        if h == l:
            return 0.5
        return float((close[-1] - l) / (h - l))


FACTOR_LIST = [
    ("momentum_5d",             AlphaFactors.momentum_5d,             ["close"]),
    ("momentum_10d",            AlphaFactors.momentum_10d,            ["close"]),
    ("momentum_20d",            AlphaFactors.momentum_20d,            ["close"]),
    ("momentum_60d",            AlphaFactors.momentum_60d,            ["close"]),
    ("reversal_5d",             AlphaFactors.reversal_5d,             ["close"]),
    ("volatility_20d",          AlphaFactors.volatility_20d,          ["close"]),
    ("atr_ratio_14d",           AlphaFactors.atr_ratio_14d,           ["high", "low", "close"]),
    ("volume_ratio_5_20",       AlphaFactors.volume_ratio_5_20,       ["volume"]),
    ("volume_trend_10d",        AlphaFactors.volume_trend_10d,        ["volume"]),
    ("volume_price_corr_10d",   AlphaFactors.volume_price_corr_10d,   ["close", "volume"]),
    ("ma_deviation_20d",        AlphaFactors.ma_deviation_20d,        ["close"]),
    ("ma_deviation_60d",        AlphaFactors.ma_deviation_60d,        ["close"]),
    ("max_drawdown_20d",        AlphaFactors.max_drawdown_20d,        ["close"]),
    ("up_days_ratio_20d",       AlphaFactors.up_days_ratio_20d,       ["close"]),
    ("amplitude_20d",           AlphaFactors.amplitude_20d,           ["high", "low"]),
    ("close_position_20d",      AlphaFactors.close_position_20d,      ["close"]),
]


FACTOR_NORMS = {
    "momentum_5d":             (0.0, 0.08),
    "momentum_10d":            (0.0, 0.12),
    "momentum_20d":            (0.0, 0.18),
    "momentum_60d":            (0.0, 0.35),
    "reversal_5d":             (0.0, 0.08),
    "volatility_20d":          (0.02, 0.02),
    "atr_ratio_14d":           (0.02, 0.02),
    "volume_ratio_5_20":       (1.0, 0.5),
    "volume_trend_10d":        (0.0, 0.3),
    "volume_price_corr_10d":   (0.0, 0.5),
    "ma_deviation_20d":        (0.0, 0.15),
    "ma_deviation_60d":        (0.0, 0.25),
    "max_drawdown_20d":        (0.05, 0.06),
    "up_days_ratio_20d":       (0.5, 0.2),
    "amplitude_20d":           (0.03, 0.02),
    "close_position_20d":      (0.5, 0.3),
}


def _normalize_factor(name: str, value: float) -> float:
    """将因子值归一化到近似 N(0,1)"""
    if name not in FACTOR_NORMS:
        return 0.0
    center, scale = FACTOR_NORMS[name]
    if scale <= 0:
        return 0.0
    return (value - center) / scale


class FactorRanker:
    """截面因子排名器

    每根K线对所有候选股票计算因子值，输出每个股票的复合 z-score。
    信号过滤层用此 score 决定是否放行。
    """

    def __init__(self):
        self._history: dict[str, dict] = {}

    def rank(self, ticker: str, df: pd.DataFrame) -> float:
        """计算单只股票的综合因子 z-score

        Returns:
            -1 ~ +1 之间的综合得分，>0 表示因子优于截面均值
        """
        if df is None or df.empty or len(df) < 61:
            return 0.0

        close = df["close"].values.astype(float)
        high = df["high"].values.astype(float) if "high" in df.columns else close
        low = df["low"].values.astype(float) if "low" in df.columns else close
        volume = df["volume"].values.astype(float) if "volume" in df.columns else np.ones_like(close)

        scores = []
        for name, func, cols in FACTOR_LIST:
            try:
                args = []
                for col in cols:
                    if col == "close":
                        args.append(close)
                    elif col == "high":
                        args.append(high)
                    elif col == "low":
                        args.append(low)
                    elif col == "volume":
                        args.append(volume)
                val = func(*args)
                if np.isfinite(val):
                    z = _normalize_factor(name, val)
                    scores.append(z)
            except Exception:
                pass

        if not scores:
            return 0.0

        return float(np.clip(np.mean(scores), -2, 2))

    def cross_sectional_score(self, factor_values: dict[str, dict[str, float]]) -> dict[str, float]:
        """截面标准化：所有股票同一因子做 z-score 标准化后取均值

        Args:
            factor_values: {ticker: {factor_name: value}}

        Returns:
            {ticker: composite_zscore}
        """
        tickers = list(factor_values.keys())
        if len(tickers) < 3:
            return {t: 0.0 for t in tickers}

        factor_names = list(next(iter(factor_values.values())).keys())
        z_scores = {t: [] for t in tickers}

        for fname in factor_names:
            vals = []
            for t in tickers:
                v = factor_values[t].get(fname, 0.0)
                vals.append(v if np.isfinite(v) else 0.0)

            vals = np.array(vals, dtype=float)
            mean = np.mean(vals)
            std = np.std(vals)
            if std == 0:
                continue

            z = (vals - mean) / std
            for i, t in enumerate(tickers):
                z_scores[t].append(float(z[i]))

        result = {}
        for t in tickers:
            z_list = z_scores[t]
            if z_list:
                avg = np.clip(np.mean(z_list), -2, 2)
                result[t] = float(avg)
            else:
                result[t] = 0.0

        return result


def compute_all_factors(ticker: str, df: pd.DataFrame) -> dict[str, float]:
    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float) if "high" in df.columns else close
    low = df["low"].values.astype(float) if "low" in df.columns else close
    volume = df["volume"].values.astype(float) if "volume" in df.columns else np.ones_like(close)

    result = {}
    for name, func, cols in FACTOR_LIST:
        try:
            args = []
            for col in cols:
                if col == "close":
                    args.append(close)
                elif col == "high":
                    args.append(high)
                elif col == "low":
                    args.append(low)
                elif col == "volume":
                    args.append(volume)
            val = func(*args)
            if np.isfinite(val):
                result[name] = float(val)
            else:
                result[name] = 0.0
        except Exception:
            result[name] = 0.0

    return result
