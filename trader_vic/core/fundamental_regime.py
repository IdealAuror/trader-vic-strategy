"""多维基本面评分引擎

四个维度，月频更新，加权综合输出风险预算：
- 宏观流动性 (35%): M2 + PMI + Shibor
- 市场杠杆 (25%): 融资余额趋势
- 估值分位 (25%): 沪深300 PE分位
- 量能确认 (15%): 市场成交量趋势

所有数据源按回测日期过滤，无前视偏差。
首次拉取缓存全量历史，后续按日期查找。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from trader_vic.data.providers import fetch_macro_data, fetch_pe_history, fetch_margin_history


@dataclass
class DimensionScore:
    name: str
    label: str
    weight: float
    score: int = 0
    raw_data: dict = field(default_factory=dict)


class FundamentalRegime:
    """多维基本面评分引擎

    月度更新，各维度独立评分后加权综合。
    任一数据源失败时该维度自动中性化，系统降级不崩溃。
    历史数据首次拉取后缓存，按 current_date 查找对应时点数据。
    """

    DIMENSIONS = [
        ("liquidity", "宏观流动性", 0.35),
        ("leverage", "市场杠杆", 0.25),
        ("valuation", "估值分位", 0.25),
        ("volume_trend", "量能确认", 0.15),
    ]

    RISK_BUDGET_MAP = [
        (0.40, 1.00),
        (0.00, 0.75),
        (-0.40, 0.50),
        (-2.00, 0.30),
    ]

    def __init__(self):
        self._dims: dict[str, DimensionScore] = {}
        for key, label, weight in self.DIMENSIONS:
            self._dims[key] = DimensionScore(name=key, label=label, weight=weight)

        self._composite: float = 0.0
        self._risk_budget: float = 0.75
        self._regime: str = "NEUTRAL"
        self._last_update: Optional[datetime] = None
        self._valid: bool = False

        self._pe_history: Optional[pd.DataFrame] = None
        self._margin_sh: Optional[pd.DataFrame] = None
        self._margin_sz: Optional[pd.DataFrame] = None

    # ── 月频更新入口 ──

    def update(self, current_date: Optional[datetime] = None, volume_trend: Optional[int] = None) -> None:
        """月度更新全部维度

        Args:
            current_date: 当前回测日期（用于过滤历史数据）
            volume_trend: 成交量趋势 +1放量/0中性/-1缩量
        """
        if current_date is None:
            current_date = datetime.now()

        if self._last_update is not None:
            days_since = (current_date - self._last_update).days
            if days_since < 20:
                return

        self._ensure_history_loaded()

        macro = fetch_macro_data()
        pe_data = self._get_pe_as_of(current_date)
        margin_data = self._get_margin_as_of(current_date)

        self._score_liquidity(macro)
        self._score_leverage(margin_data)
        self._score_valuation(pe_data)
        self._score_volume_trend(volume_trend)

        self._composite = sum(d.score * d.weight for d in self._dims.values())
        self._risk_budget = self._composite_to_budget(self._composite)
        self._regime = self._composite_to_regime(self._composite)
        self._valid = True
        self._last_update = current_date

    def _ensure_history_loaded(self) -> None:
        """首次调用时加载全量历史数据并缓存"""
        if self._pe_history is None:
            self._pe_history = fetch_pe_history()
        if self._margin_sh is None:
            self._margin_sh, self._margin_sz = fetch_margin_history()

    def _get_pe_as_of(self, dt: datetime) -> dict:
        """从缓存中查找截至 dt 的最新 PE 数据"""
        if self._pe_history is None or self._pe_history.empty:
            return {"pe_ttm": None, "pe_percentile": None}

        df = self._pe_history
        cutoff = pd.Timestamp(dt)
        mask = df["date"] <= cutoff
        filtered = df.loc[mask]
        if filtered.empty:
            return {"pe_ttm": None, "pe_percentile": None}

        row = filtered.iloc[-1]
        return {
            "pe_ttm": float(row["pe_ttm"]) if not pd.isna(row["pe_ttm"]) else None,
            "pe_percentile": float(row["pe_percentile"]) if not pd.isna(row["pe_percentile"]) else None,
        }

    def _get_margin_as_of(self, dt: datetime) -> dict:
        """从缓存中查找截至 dt 的最新融资余额及 20 日变化"""
        if self._margin_sh is None or self._margin_sh.empty:
            return {"margin_balance": None, "margin_20d_change_pct": None}
        if self._margin_sz is None or self._margin_sz.empty:
            return {"margin_balance": None, "margin_20d_change_pct": None}

        cutoff = pd.Timestamp(dt)
        sh_f = self._margin_sh[self._margin_sh["date"] <= cutoff]
        sz_f = self._margin_sz[self._margin_sz["date"] <= cutoff]

        if sh_f.empty or sz_f.empty or len(sh_f) < 21:
            return {"margin_balance": None, "margin_20d_change_pct": None}

        sh_latest = float(sh_f.iloc[-1]["margin_balance"])
        sz_latest = float(sz_f.iloc[-1]["margin_balance"])
        total = sh_latest + sz_latest

        sh_20d = float(sh_f.iloc[-21]["margin_balance"])
        sz_20d = float(sz_f.iloc[-21]["margin_balance"])
        total_20d = sh_20d + sz_20d

        change_pct = ((total - total_20d) / total_20d * 100) if total_20d > 0 else None

        return {"margin_balance": total, "margin_20d_change_pct": change_pct}

    # ── 各维度评分（-1 / 0 / +1） ──

    def _score_liquidity(self, macro: dict) -> None:
        dim = self._dims["liquidity"]
        dim.raw_data = dict(macro)
        scores = []

        m2 = macro.get("m2_yoy")
        if m2 is not None:
            if m2 > 12:
                scores.append(1)
            elif m2 < 8:
                scores.append(-1)
            else:
                scores.append(0)

        pmi = macro.get("pmi")
        if pmi is not None:
            scores.append(1 if pmi > 50 else -1)

        shibor = macro.get("shibor_1y")
        if shibor is not None:
            if shibor < 2.5:
                scores.append(1)
            elif shibor > 3.5:
                scores.append(-1)
            else:
                scores.append(0)

        if scores:
            avg = sum(scores) / len(scores)
            if avg > 0.3:
                dim.score = 1
            elif avg < -0.3:
                dim.score = -1
            else:
                dim.score = 0

    def _score_leverage(self, margin: dict) -> None:
        dim = self._dims["leverage"]
        dim.raw_data = dict(margin)

        change_pct = margin.get("margin_20d_change_pct")
        if change_pct is not None:
            if change_pct > 15:
                dim.score = 1
            elif change_pct < -15:
                dim.score = -1
            else:
                dim.score = 0

    def _score_valuation(self, pe: dict) -> None:
        dim = self._dims["valuation"]
        dim.raw_data = dict(pe)

        pe_pct = pe.get("pe_percentile")
        if pe_pct is not None:
            if pe_pct < 25:
                dim.score = 1
            elif pe_pct > 75:
                dim.score = -1
            else:
                dim.score = 0

    def _score_volume_trend(self, trend: Optional[int]) -> None:
        dim = self._dims["volume_trend"]
        if trend is not None:
            dim.score = trend

    # ── 综合 → 风险预算 ──

    @staticmethod
    def _composite_to_budget(composite: float) -> float:
        for threshold, budget in FundamentalRegime.RISK_BUDGET_MAP:
            if composite >= threshold:
                return budget
        return 0.30

    @staticmethod
    def _composite_to_regime(composite: float) -> str:
        if composite >= 0.3:
            return "BULLISH"
        elif composite <= -0.3:
            return "BEARISH"
        return "NEUTRAL"

    # ── 查询接口 ──

    def get_risk_budget(self) -> float:
        return self._risk_budget

    def get_regime(self) -> str:
        return self._regime

    def get_composite(self) -> float:
        return self._composite

    def get_dimensions(self) -> dict[str, DimensionScore]:
        return dict(self._dims)

    def get_summary(self) -> dict:
        return {
            "regime": self._regime,
            "risk_budget": self._risk_budget,
            "composite": round(self._composite, 3),
            "valid": self._valid,
            "dimensions": {
                key: {"label": d.label, "weight": d.weight, "score": d.score}
                for key, d in self._dims.items()
            },
        }

    def get_details(self) -> str:
        lines = [f"基本面方向: {self._regime} (风险预算 {self._risk_budget:.0%})"]
        for key, d in self._dims.items():
            label = {1: "↑", -1: "↓", 0: "→"}.get(d.score, "?")
            lines.append(f"  {d.label} ({d.weight:.0%}): {label} score={d.score:+d}")
        return "\n".join(lines)
