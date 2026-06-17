"""三原则金字塔资金管理（ch03, ch11, ch18）

层级切换：
- Level 1（保障资本）：回撤期或初始状态，保守风险
- Level 2（一致性获利）：盈利期，允许更高风险
- Level 3（卓越报酬）：大盈利后，利用银行利润进取

核心规则:
- 单笔风险 ≤ 可用资本 × 2%（斯波朗迪铁律）
- 50% 利润锁定：每笔盈利一半存入银行
- 亏损自动缩小/盈利放大（资本公式自动实现）
"""

from trader_vic.config import (
    RISK_PCT,
    CAPITAL_LEVEL2_THRESHOLD,
    CAPITAL_LEVEL3_THRESHOLD,
    MAX_DRAWDOWN_LEVEL1,
)


class CapitalManager:
    """三原则金字塔资金管理

    维护资本层级和 50% 利润锁定机制。
    """

    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital
        self.peak_capital = initial_capital
        self.current_capital = initial_capital
        self.locked_profit = 0.0
        self._level = 1
        self._total_profit = 0.0

    def update(self, portfolio_value: float) -> int:
        """根据组合总市值更新资本层级

        每笔交易后调用。

        Args:
            portfolio_value: 当前组合总市值（含现金+持仓市值）

        Returns:
            当前层级 1/2/3
        """
        self.current_capital = portfolio_value
        self.peak_capital = max(self.peak_capital, portfolio_value)

        total_gain = (portfolio_value - self.initial_capital) / self.initial_capital
        self._total_profit = portfolio_value - self.initial_capital

        # 回撤超过 20% 退回 Level 1
        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        if drawdown > MAX_DRAWDOWN_LEVEL1:
            self._level = 1
        # 银行利润翻倍 → Level 3
        elif self.locked_profit >= self.initial_capital * (CAPITAL_LEVEL3_THRESHOLD - 1):
            self._level = 3
        # 盈利 10% 以上 → Level 2
        elif total_gain >= (CAPITAL_LEVEL2_THRESHOLD - 1):
            self._level = 2
        else:
            self._level = 1

        return self._level

    def lock_profit(self, trade_profit: float) -> None:
        """锁定 50% 利润"""
        if trade_profit > 0:
            locked = trade_profit * 0.50
            self.locked_profit += locked

    @property
    def level(self) -> int:
        return self._level

    @property
    def available_risk_base(self) -> float:
        """计算可用风险基础 = 当前资本 + 已解锁的银行利润再投资部分"""
        return self.current_capital

    @property
    def max_single_risk(self) -> float:
        """单笔最大风险 = 可用资本 × 2%"""
        return self.available_risk_base * RISK_PCT


class TieredPositionSizer:
    """层级头寸计算器

    头寸 = (可用资本 × 风险比例) ÷ |入场 - 止损|
    """

    @staticmethod
    def size(
        capital: float,
        risk_pct: float,
        entry: float,
        stop: float,
        price_step: float = 100,  # A 股 1 手 = 100 股
    ) -> int:
        """计算买入股数（取整到 100 的整数倍）

        Args:
            capital: 可用资本
            risk_pct: 风险比例（如 0.02 = 2%）
            entry: 入场价
            stop: 止损价
            price_step: 最小交易单位（A 股为 100 股）

        Returns:
            股数（100 的整数倍）
        """
        risk_per_share = abs(entry - stop)
        if risk_per_share <= 0:
            return 0

        total_risk = capital * risk_pct
        shares = total_risk / risk_per_share

        # 取整到 100 的整数倍
        shares = int(shares / price_step) * price_step
        return max(shares, 0)

    @staticmethod
    def position_value(shares: int, entry: float) -> float:
        """计算头寸价值"""
        return shares * entry
