"""基本面方向过滤 — M2/PMI/Shibor 月频评分

宏观数据滞后 1 月处理（M2 次月 10-15 日发布，PMI 次月 1 日发布）。
回测中使用 T-1 月数据做交易决策，防止前视偏差。
"""

from datetime import datetime, timedelta
from typing import Optional

from trader_vic.data.providers import fetch_macro_data


class FundamentalRegime:
    """基本面方向判断引擎

    用 M2 同比 + PMI + Shibor 三个维度评分：
    - M2 方向 (±1): 同比增速上升/下降
    - PMI 方向 (±1): 在 50 上方/下方
    - Shibor 趋势 (±1): 利率下降/上升

    总分 ≥ +2 → BULLISH, ≤ -2 → BEARISH, 其余 → NEUTRAL
    """

    def __init__(self):
        self._score: int = 0
        self._regime: str = "NEUTRAL"
        self._last_update: Optional[datetime] = None
        self._data: dict = {
            "m2_yoy": None,
            "pmi": None,
            "shibor_1y": None,
            "m2_trend": 0,
            "pmi_signal": 0,
            "shibor_trend": 0,
        }

    def update(self, current_date: Optional[datetime] = None) -> None:
        """更新基本面方向（月频）

        每个月第一个交易日调用一次。
        宏观数据已内置 1 月滞后处理。
        """
        if current_date is None:
            current_date = datetime.now()

        # 月频更新：一个月只拉一次
        if self._last_update is not None:
            days_since = (current_date - self._last_update).days
            if days_since < 20:  # 月频数据，20 天内不重复拉取
                return

        raw = fetch_macro_data()
        self._data["m2_yoy"] = raw.get("m2_yoy")
        self._data["pmi"] = raw.get("pmi")
        self._data["shibor_1y"] = raw.get("shibor_1y")

        # M2 方向：同比增速 > 上次 → +1, < 上次 → -1
        if self._data["m2_yoy"] is not None:
            # 简化：假设 M2 在 8-12% 区间为中性，>12% 偏宽松，<8% 偏紧缩
            m2 = self._data["m2_yoy"]
            if m2 > 12:
                self._data["m2_trend"] = 1   # 宽松 → 利好股市
            elif m2 < 8:
                self._data["m2_trend"] = -1  # 紧缩 → 利空股市
            else:
                self._data["m2_trend"] = 0   # 中性

        # PMI 方向：>50 扩张 → +1, <50 收缩 → -1
        if self._data["pmi"] is not None:
            self._data["pmi_signal"] = 1 if self._data["pmi"] > 50 else -1

        # Shibor 趋势：利率 < 3% → +1（宽松）, > 4% → -1（紧缩）
        if self._data["shibor_1y"] is not None:
            shibor = self._data["shibor_1y"]
            if shibor < 3.0:
                self._data["shibor_trend"] = 1
            elif shibor > 4.0:
                self._data["shibor_trend"] = -1
            else:
                self._data["shibor_trend"] = 0

        # 总分 -3 ~ +3
        self._score = (
            self._data["m2_trend"]
            + self._data["pmi_signal"]
            + self._data["shibor_trend"]
        )

        # 映射到方向
        if self._score >= 2:
            self._regime = "BULLISH"
        elif self._score <= -2:
            self._regime = "BEARISH"
        else:
            self._regime = "NEUTRAL"

        self._last_update = current_date

    def get_regime(self) -> str:
        return self._regime

    def get_score(self) -> int:
        return self._score

    def get_data(self) -> dict:
        return dict(self._data)
