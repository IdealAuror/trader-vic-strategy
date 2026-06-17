"""股票池动态管理

每根K线评估候选池：
- 新上市满 252 根 K 线 → 纳入
- 停牌（连续 10 日价格不变）→ 剔除
- 流动性枯竭（20日均量 < 阈值）→ 剔除
- 退市/长期停牌 → 永久剔除

通过进出机制，保证候选池始终是"可以交易的"股票。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from trader_vic.config import MIN_DATA_BARS, SUSPEND_THRESHOLD


@dataclass
class StockStatus:
    ticker: str
    active: bool = True
    suspended: bool = False
    illiquid: bool = False
    delisted: bool = False
    joined_date: Optional[datetime] = None
    removed_date: Optional[datetime] = None
    reason: str = ""


class StockPool:
    """动态股票池

    每根K线检查所有候选股票的活跃状态。
    停牌、无量的股票自动移出，恢复后重新纳入。
    """

    def __init__(
        self,
        min_volume_20d: float = 100_000,
        suspend_days: int = SUSPEND_THRESHOLD,
    ):
        self._min_volume_20d = min_volume_20d
        self._suspend_days = suspend_days

        self._status: dict[str, StockStatus] = {}
        self._active: set[str] = set()
        self._pending: set[str] = set()

    def register(self, ticker: str) -> None:
        """注册候选股票（初始全部 pending，等数据充足后激活）"""
        if ticker not in self._status:
            self._status[ticker] = StockStatus(ticker=ticker)
            self._pending.add(ticker)

    def evaluate(self, ticker: str, df: pd.DataFrame, current_date: datetime) -> str:
        """评估单只股票当前状态

        Args:
            ticker: 股票代码
            df: 该股票截至 current_date 的全量历史数据
            current_date: 当前日期

        Returns:
            "active" | "pending" | "suspended" | "illiquid" | "delisted"
        """
        status = self._status.get(ticker)
        if status is None:
            status = StockStatus(ticker=ticker)
            self._status[ticker] = status

        if status.delisted:
            return "delisted"

        if df is None or df.empty:
            return "pending"

        if len(df) < MIN_DATA_BARS:
            return "pending"

        recent = df.tail(20)
        if len(recent) < 5:
            return "pending"

        # 停牌检测：最近 N 日高低价完全不变
        if len(df) >= self._suspend_days:
            tail = df.tail(self._suspend_days)
            if "high" in tail.columns and "low" in tail.columns:
                flat = (tail["high"] == tail["low"]).sum()
                if flat >= self._suspend_days:
                    status.suspended = True
                    status.active = False
                    if ticker in self._active:
                        self._active.discard(ticker)
                    return "suspended"

        # 之前停牌的恢复
        if status.suspended:
            recent_5 = df.tail(5)
            if "high" in recent_5.columns and "low" in recent_5.columns:
                if (recent_5["high"] != recent_5["low"]).sum() >= 3:
                    status.suspended = False

        # 流动性检查
        if "volume" in df.columns:
            vol_20d = df["volume"].tail(20).mean()
            if vol_20d < self._min_volume_20d:
                status.illiquid = True
                status.active = False
                if ticker in self._active:
                    self._active.discard(ticker)
                return "illiquid"
            else:
                status.illiquid = False

        # 远低于历史最高价的退市风险（价格跌到 1 元以下）
        if "close" in df.columns:
            close = float(df["close"].iloc[-1])
            if close < 1.0:
                max_price = float(df["close"].max())
                if max_price > 10 and close < 1.0:
                    status.delisted = True
                    status.active = False
                    if ticker in self._active:
                        self._active.discard(ticker)
                    return "delisted"

        # 激活
        if not status.suspended and not status.illiquid and not status.delisted:
            if ticker not in self._active:
                if status.joined_date is None:
                    status.joined_date = current_date
                self._active.add(ticker)
            status.active = True
            return "active"

        return "pending"

    @property
    def active(self) -> set[str]:
        return self._active

    def is_active(self, ticker: str) -> bool:
        return ticker in self._active

    def get_summary(self) -> dict:
        return {
            "active": len(self._active),
            "suspended": sum(1 for s in self._status.values() if s.suspended),
            "illiquid": sum(1 for s in self._status.values() if s.illiquid),
            "delisted": sum(1 for s in self._status.values() if s.delisted),
            "total": len(self._status),
        }
