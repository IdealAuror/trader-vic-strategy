"""概率/期望值引擎 — EV 计算, 凯利公式, 头寸规模

核心逻辑（ch03, ch11, ch26）：
- 每个信号携带先验概率 P(win)
- EV = P(win) × reward - (1-P(win)) × risk
- 凯利公式：f* = (P × (R+1) - 1) / R（外部扩展，标注非书中内容）
- 头寸规模公式（书中）：仓位 = (资本 × 风险%) / |入场 - 止损|
"""

from trader_vic.config import SIGNAL_PROBABILITIES, KELLY_SAFETY


class EVCalculator:
    """期望值计算引擎

    EV = P(win) × reward - (1-P(win)) × risk
    EV_per_R = EV / risk = P(win) × RRR - (1-P(win))
    """

    @staticmethod
    def ev(p_win: float, reward: float, risk: float) -> float:
        """计算期望值

        Args:
            p_win: 获胜概率 0~1
            reward: 潜在收益（绝对金额）
            risk: 潜在亏损（绝对金额）

        Returns:
            期望值（正数 = 有利可图）
        """
        if risk <= 0:
            return 0.0
        return p_win * reward - (1 - p_win) * risk

    @staticmethod
    def ev_per_r(p_win: float, rr_ratio: float) -> float:
        """归一化到 R 单位的期望值

        EV_per_R = P(win) × RRR - (1-P(win))
        RRR = reward / risk

        例: 2B 信号 P=50%, RRR=1:3 → EV/R = 0.5×3 - 0.5 = +1.0R
        """
        return p_win * rr_ratio - (1 - p_win)

    @staticmethod
    def signal_ev(signal_type: str, reward: float, risk: float) -> float:
        """使用预定义信号概率计算 EV

        Args:
            signal_type: 信号类型，需在 SIGNAL_PROBABILITIES 中
            reward: 潜在收益
            risk: 潜在亏损

        Returns:
            期望值
        """
        p_win = SIGNAL_PROBABILITIES.get(signal_type, 0.33)
        return EVCalculator.ev(p_win, reward, risk)

    @staticmethod
    def meets_minimum(p_win: float, rr_ratio: float, min_ev_per_r: float = 0.32) -> bool:
        """是否满足最低可接受 EV

        ch18 暗示：纯趋势跟踪 P=33%, RRR=1:3 → EV/R = +0.32R
        低于此值不值得做
        """
        return EVCalculator.ev_per_r(p_win, rr_ratio) >= min_ev_per_r


class KellyFraction:
    """凯利公式计算最优下注比例

    ⚠️ 外部扩展 — 非书中内容。书中使用固定比例法。
    斯波朗迪的原始公式：仓位 = (资本 × 固定风险%) ÷ |入场 - 止损|
    """

    @staticmethod
    def optimal_f(p_win: float, rr_ratio: float) -> float:
        """凯利公式

        f* = (P × (R+1) - 1) / R
        其中 R = reward / risk

        Args:
            p_win: 获胜概率
            rr_ratio: 盈亏比 (reward/risk)

        Returns:
            最优下注比例 (0~1)
        """
        if rr_ratio <= 0:
            return 0.0
        f = (p_win * (rr_ratio + 1) - 1) / rr_ratio
        return max(0.0, f)


def vic_position_fraction(p_win: float, rr_ratio: float, capital_level: int) -> float:
    """Trader Vic 改进版凯利

    凯利 × 安全系数 × 资本层级（设计者扩展 — 非书中内容）。

    Args:
        p_win: 获胜概率
        rr_ratio: 盈亏比
        capital_level: 资金管理层级 (1/2/3)

    Returns:
        最终风险比例 (被 2% 硬上限截断)
    """
    kelly = KellyFraction.optimal_f(p_win, rr_ratio)
    safety = KELLY_SAFETY.get(capital_level, KELLY_SAFETY[1])
    return kelly * safety
