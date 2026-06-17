"""组合管理器 — 风险敞口总账、入场检查、持仓会计、状态序列化

核心逻辑：
- 不设 MAX_POSITIONS，风险敞口驱动
- 单只最大风险 = 总资本 × 2%
- 总风险敞口上限 = 总资本 × TOTAL_RISK_BUDGET × env_adapt.position_cap
- 多头止损只上移不下移（鳄鱼原则）
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from trader_vic.config import TOTAL_RISK_BUDGET, RISK_PCT
from trader_vic.core.risk import StopManager


@dataclass
class Position:
    """持仓记录"""
    ticker: str
    shares: int
    entry_price: float
    stop: float
    target: float
    entry_date: str
    bars_held: int = 0
    stop_manager: Optional[StopManager] = None


@dataclass
class TradeRecord:
    """交易记录"""
    ticker: str
    direction: int
    entry_price: float
    exit_price: float
    shares: int
    entry_date: str
    exit_date: str
    pnl: float
    exit_reason: str


class PortfolioMgr:
    """组合管理器

    管理风险敞口、入场检查、持仓会计、状态持久化。
    """

    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[TradeRecord] = []
        self.trades_today: list[TradeRecord] = []
        self._pending_cash = 0.0  # T+1 可用资金
        self._total_risk_used = 0.0
        self._position_cap = 1.0

    def set_position_cap(self, cap: float) -> None:
        self._position_cap = cap

    def total_risk_cap(self) -> float:
        """总风险敞口上限 = 总资本 × TOTAL_RISK_BUDGET × position_cap"""
        total_capital = self.cash + self._position_value()
        return total_capital * TOTAL_RISK_BUDGET * self._position_cap

    def _position_value(self) -> float:
        return sum(
            p.shares * p.entry_price for p in self.positions.values()
        )

    def risk_used(self) -> float:
        """当前已占用风险"""
        total = 0.0
        for p in self.positions.values():
            risk = abs(p.entry_price - p.stop) * p.shares
            total += risk
        return total

    def can_enter(self, ticker: str, shares: int, entry_price: float, stop_price: float) -> bool:
        """检查是否可以入场

        Returns:
            True 允许入场
        """
        if ticker in self.positions:
            return False

        if shares <= 0 or entry_price <= 0:
            return False

        # 资金检查
        cost = shares * entry_price
        if cost > self.cash + self._pending_cash:
            return False

        # 风险检查
        new_risk = abs(entry_price - stop_price) * shares
        if new_risk <= 0:
            return False

        # 单只 2% 风险上限
        if new_risk > self.initial_capital * RISK_PCT:
            return False

        # 总风险敞口检查
        if self.risk_used() + new_risk > self.total_risk_cap():
            return False

        return True

    def enter(self, ticker: str, shares: int, price: float, stop: float, target: float) -> None:
        """执行入场"""
        cost = shares * price

        # 先用 pending_cash，再用 cash
        if self._pending_cash >= cost:
            self._pending_cash -= cost
        else:
            remaining = cost - self._pending_cash
            self._pending_cash = 0
            self.cash -= remaining

        position = Position(
            ticker=ticker,
            shares=shares,
            entry_price=price,
            stop=stop,
            target=target,
            entry_date=datetime.now().strftime("%Y-%m-%d"),
            stop_manager=StopManager(price, stop),
        )
        self.positions[ticker] = position

    def exit(self, ticker: str, price: float, reason: str = "STOP_HIT") -> Optional[TradeRecord]:
        """执行出场（全仓）

        Returns:
            TradeRecord 或 None（持仓不存在）
        """
        pos = self.positions.pop(ticker, None)
        if pos is None:
            return None
        return self._close_position(pos, price, reason)

    def partial_exit(self, ticker: str, price: float, shares: int, reason: str) -> Optional[TradeRecord]:
        """执行部分出场（如止盈平半仓）

        Returns:
            TradeRecord 或 None
        """
        pos = self.positions.get(ticker)
        if pos is None or shares <= 0:
            return None
        if shares >= pos.shares:
            return self.exit(ticker, price, reason)

        # 减少持仓股数
        pos.shares -= shares

        # 从当前持仓克隆出一份 TradeRecord
        pnl, net_proceeds = self._calc_trade_result(pos, price, shares)
        record = TradeRecord(
            ticker=ticker,
            direction=1 if pos.entry_price < price else -1,
            entry_price=pos.entry_price,
            exit_price=price,
            shares=shares,
            entry_date=pos.entry_date,
            exit_date=datetime.now().strftime("%Y-%m-%d"),
            pnl=pnl,
            exit_reason=reason,
        )
        self.trades.append(record)
        self.trades_today.append(record)
        self._settle_cash(net_proceeds)
        return record

    @staticmethod
    def _calc_trade_result(pos: Position, price: float, shares: int) -> tuple[float, float]:
        """计算交易盈亏和净收入"""
        from trader_vic.config import COMMISSION_RATE, STAMP_TAX_RATE, SLIPPAGE
        proceeds = shares * price
        commission = max(proceeds * COMMISSION_RATE, 5.0)
        stamp_tax = proceeds * STAMP_TAX_RATE
        slippage_cost = proceeds * SLIPPAGE
        net_proceeds = proceeds - commission - stamp_tax - slippage_cost
        pnl = net_proceeds - (shares * pos.entry_price)
        return pnl, net_proceeds

    def _close_position(self, pos: Position, price: float, reason: str) -> TradeRecord:
        """关闭持仓并生成交易记录"""
        pnl, net_proceeds = self._calc_trade_result(pos, price, pos.shares)
        self._settle_cash(net_proceeds)
        record = TradeRecord(
            ticker=pos.ticker,
            direction=1 if pos.entry_price < price else -1,
            entry_price=pos.entry_price,
            exit_price=price,
            shares=pos.shares,
            entry_date=pos.entry_date,
            exit_date=datetime.now().strftime("%Y-%m-%d"),
            pnl=pnl,
            exit_reason=reason,
        )
        self.trades.append(record)
        self.trades_today.append(record)
        return record

    def _settle_cash(self, net_proceeds: float) -> None:
        """T+1 资金结算：卖出资金当天可用于再买入"""
        self._pending_cash += net_proceeds

    def mark_to_market(self, prices: dict[str, float]) -> float:
        """按市值计价

        Args:
            prices: {ticker: current_price} 字典

        Returns:
            组合总市值
        """
        position_value = 0.0
        for ticker, pos in self.positions.items():
            current_price = prices.get(ticker, pos.entry_price)
            position_value += pos.shares * current_price

        total_value = self.cash + self._pending_cash + position_value
        return total_value

    def save_state(self, path: str) -> None:
        """序列化组合状态到 JSON"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        state = {
            "cash": self.cash,
            "pending_cash": self._pending_cash,
            "positions": {
                t: {
                    "ticker": p.ticker,
                    "shares": p.shares,
                    "entry_price": p.entry_price,
                    "stop": p.stop,
                    "target": p.target,
                    "entry_date": p.entry_date,
                    "bars_held": p.bars_held,
                }
                for t, p in self.positions.items()
            },
            "position_cap": self._position_cap,
        }
        with open(path, "w") as f:
            json.dump(state, f, indent=2)

    def load_state(self, path: str) -> bool:
        """从 JSON 恢复组合状态"""
        if not os.path.exists(path):
            return False
        with open(path, "r") as f:
            state = json.load(f)

        self.cash = state.get("cash", self.initial_capital)
        self._pending_cash = state.get("pending_cash", 0.0)
        self._position_cap = state.get("position_cap", 1.0)
        self.positions = {}
        for t, pdata in state.get("positions", {}).items():
            pos = Position(
                ticker=pdata["ticker"],
                shares=pdata["shares"],
                entry_price=pdata["entry_price"],
                stop=pdata["stop"],
                target=pdata["target"],
                entry_date=pdata["entry_date"],
                bars_held=pdata.get("bars_held", 0),
            )
            pos.stop_manager = StopManager(pos.entry_price, pos.stop)
            self.positions[t] = pos
        return True

    def increment_bars_held(self) -> None:
        """每根 K 线结束时调用，增加持仓计数"""
        for pos in self.positions.values():
            pos.bars_held += 1

    def clear_trades_today(self) -> None:
        """清空当日交易记录 + 结算 T+1 资金（每日收盘后调用）"""
        self.trades_today = []
        self.cash += self._pending_cash
        self._pending_cash = 0.0
