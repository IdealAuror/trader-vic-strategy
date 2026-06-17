"""风险管理 — RRR 过滤, 止损管理, 时间止损, 连续亏损暂停

核心原则（ch02, ch12, ch18）：
- 鳄鱼原则：触及止损立即离场，不等待不摊平
- RRR ≥ 1:3 硬性筛选门槛
- 多头止损只上移不下移
"""

import trader_vic.config as cfg


class RiskRewardFilter:
    """风险回报比过滤器

    RRR = 潜在收益 / 潜在风险
    """

    @staticmethod
    def check(entry: float, stop: float, target: float, min_rrr: float = 3.0) -> bool:
        """检查 RRR 是否达标

        Args:
            entry: 入场价
            stop: 止损价
            target: 目标价
            min_rrr: 最低 RRR 要求

        Returns:
            True 如果 RRR >= min_rrr
        """
        risk = abs(entry - stop)
        if risk <= 0:
            return False
        reward = abs(target - entry)
        rr_ratio = reward / risk
        return rr_ratio >= min_rrr

    @staticmethod
    def rr_ratio(entry: float, stop: float, target: float) -> float:
        """计算实际 RRR"""
        risk = abs(entry - stop)
        if risk <= 0:
            return 0.0
        reward = abs(target - entry)
        return reward / risk


class StopManager:
    """止损管理

    管理每笔持仓的止损位，多头止损只上移不下移。
    """

    def __init__(self, entry_price: float, initial_stop: float):
        self.entry_price = entry_price
        self._stop = initial_stop
        self._highest_price = entry_price
        self._lowest_price = entry_price
        self._take_profit_triggered = False
        self._is_long = entry_price > initial_stop  # 多：止损在入场下方

    @property
    def stop(self) -> float:
        return self._stop

    @property
    def highest_price(self) -> float:
        return self._highest_price

    def update(self, high: float, low: float) -> str:
        """更新止损并检查是否触发

        Args:
            high: 当前 K 线最高价
            low: 当前 K 线最低价

        Returns:
            HOLD / STOP_HIT / TAKE_PROFIT
        """
        self._highest_price = max(self._highest_price, high)
        self._lowest_price = min(self._lowest_price, low)

        # 多头：止损只上移不下移
        if self._is_long:
            new_stop = max(self._stop, self._highest_price * 0.95)
            self._stop = min(new_stop, self.entry_price * 1.5)  # 上限防漂移

            if low <= self._stop:
                return "STOP_HIT"

        # 空头：止损只下移不上移
        else:
            new_stop = min(self._stop, self._lowest_price * 1.05)
            self._stop = max(new_stop, self.entry_price * 0.5)

            if high >= self._stop:
                return "STOP_HIT"

        return "HOLD"

    def check_take_profit(self, current_price: float, target: float) -> str:
        """检查止盈是否触发

        达目标平 50% + 移止损至保本 + 剩余追踪。
        """
        if self._take_profit_triggered:
            return "HOLD"

        is_long = self.entry_price < target

        if is_long and current_price >= target:
            self._take_profit_triggered = True
            # 移止损至保本
            self._stop = max(self._stop, self.entry_price)
            return "TAKE_PROFIT"

        elif not is_long and current_price <= target:
            self._take_profit_triggered = True
            self._stop = min(self._stop, self.entry_price)
            return "TAKE_PROFIT"

        return "HOLD"

    @property
    def take_profit_triggered(self) -> bool:
        return self._take_profit_triggered


class TimeStop:
    """时间止损（ch12）

    入场后 N 根 K 线未朝预期方向运行 → 离场。
    默认 10 根 K 线（约 2 周交易时间）。
    """

    @staticmethod
    def check(bars_held: int, max_bars: int = cfg.TIME_STOP_MAX_BARS) -> bool:
        """检查时间止损

        Args:
            bars_held: 已持有的 K 线数量
            max_bars: 最大持有上限

        Returns:
            True 表示触发时间止损
        """
        return bars_held >= max_bars


class ConsecutiveLossPause:
    """连续亏损暂停（ch12 情绪保护）

    连续亏损 N 笔后自动暂停，防止报复交易。
    """

    def __init__(self, threshold: int = cfg.CONSECUTIVE_LOSS_PAUSE, pause_bars: int = cfg.CONSECUTIVE_LOSS_BAR):
        self.threshold = threshold
        self.pause_bars = pause_bars
        self._loss_streak = 0
        self._bars_remaining = 0

    def record_result(self, is_win: bool) -> None:
        """记录一笔交易结果"""
        if is_win:
            self._loss_streak = 0
        else:
            self._loss_streak += 1
            if self._loss_streak >= self.threshold:
                self._bars_remaining = self.pause_bars

    def can_trade(self) -> bool:
        """是否允许交易"""
        if self._bars_remaining > 0:
            self._bars_remaining -= 1
            return False
        return True

    @property
    def loss_streak(self) -> int:
        return self._loss_streak

    @property
    def bars_remaining(self) -> int:
        return self._bars_remaining
