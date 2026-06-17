"""多层确认引擎 — 技术共识 + 基本面方向 + 道氏确认 + 环境适配

斯波朗迪筛选漏斗法（ch07）：层层过滤，全部通过才入场。
每层都可以独立关闭或调整严格度。
"""

import math
from typing import Optional

from trader_vic.config import MACRO_CONFLICT_MODE
from trader_vic.core.signals import Signal


class ConsensusEngine:
    """多层确认引擎

    Layer 1: 技术共识 — log-odds 加权投票
    Layer 2: 基本面方向对齐 — MACRO_CONFLICT_MODE
    Layer 3: 环境适配 — 震荡市跳过趋势信号
    Layer 4: 道氏确认 — 沪深300 vs 上证指数

    输出: Signal(direction, confidence, layers_passed) 或 None
    """

    def __init__(self):
        self._fundamental_regime: str = "NEUTRAL"
        self._env_adapt: dict = {}
        self._dow_confirmed: Optional[int] = None

    def set_fundamental(self, regime: str) -> None:
        self._fundamental_regime = regime

    def set_environment(self, env_adapt: dict) -> None:
        self._env_adapt = env_adapt

    def set_dow_confirmation(self, confirmed: Optional[int]) -> None:
        self._dow_confirmed = confirmed

    def resolve(
        self,
        active_signals: list[Signal],
        trend_direction: str,
    ) -> Optional[Signal]:
        """多层确认筛选

        Args:
            active_signals: 当前触发的全部信号列表
            trend_direction: 周线趋势方向 UP/DOWN/RANGE

        Returns:
            通过所有层的最终信号，或 None
        """
        if not active_signals:
            return None

        # 技术共识（Layer 1）
        consensus = self._tech_consensus(active_signals)
        if consensus is None:
            return None

        # 基本面方向对齐（Layer 2）
        consensus = self._align_fundamental(consensus)
        if consensus is None:
            return None

        # 环境适配（Layer 3）
        consensus = self._apply_environment(consensus)
        if consensus is None:
            return None

        # 道氏确认（Layer 4）
        consensus = self._apply_dow(consensus)
        if consensus is None:
            return None

        return consensus

    def _tech_consensus(self, signals: list[Signal]) -> Optional[Signal]:
        """Layer 1: 技术共识 — log-odds 加权投票

        权重 = log(P/(1-P))，即证据权重。
        同一方向加权求和后归一化。
        """
        if not signals:
            return None

        long_weight = 0.0
        short_weight = 0.0
        total_weight = 0.0

        best_long: Optional[Signal] = None
        best_short: Optional[Signal] = None

        for sig in signals:
            odds = sig.confidence / max(1 - sig.confidence, 0.01)
            weight = math.log(odds)
            weight = max(weight, 0.01)  # 最低权重

            if sig.direction > 0:
                long_weight += weight
                if best_long is None or sig.confidence > best_long.confidence:
                    best_long = sig
            else:
                short_weight += weight
                if best_short is None or sig.confidence > best_short.confidence:
                    best_short = sig

            total_weight += weight

        if total_weight < 0.1:
            return None  # 信号太弱

        # 选择主导方向
        if long_weight > short_weight * 1.5 and best_long is not None:
            confidence = long_weight / total_weight
            return Signal(
                direction=1,
                confidence=min(confidence, 0.95),
                stop=best_long.stop,
                target=best_long.target,
                signal_type=best_long.signal_type,
            )
        elif short_weight > long_weight * 1.5 and best_short is not None:
            confidence = short_weight / total_weight
            return Signal(
                direction=-1,
                confidence=min(confidence, 0.95),
                stop=best_short.stop,
                target=best_short.target,
                signal_type=best_short.signal_type,
            )

        return None  # 方向不够明确

    def _align_fundamental(self, signal: Signal) -> Optional[Signal]:
        """Layer 2: 基本面方向对齐

        MACRO_CONFLICT_MODE:
            FILTER — 方向冲突则跳过
            REDUCE — 冲突时降权 50%
            IGNORE — 忽略基本面
        """
        if self._fundamental_regime == "NEUTRAL" or MACRO_CONFLICT_MODE == "IGNORE":
            return signal

        conflict = (
            (signal.direction > 0 and self._fundamental_regime == "BEARISH")
            or (signal.direction < 0 and self._fundamental_regime == "BULLISH")
        )

        if not conflict:
            return signal

        if MACRO_CONFLICT_MODE == "FILTER":
            return None  # 冲突 → 跳过
        elif MACRO_CONFLICT_MODE == "REDUCE":
            return Signal(
                direction=signal.direction,
                confidence=signal.confidence * 0.5,
                stop=signal.stop,
                target=signal.target,
                signal_type=signal.signal_type,
            )
        return signal

    def _apply_environment(self, signal: Signal) -> Optional[Signal]:
        """Layer 3: 环境适配

        根据当前市场环境调整信号：
        - CRISIS 环境全部跳过
        - 震荡市跳过趋势信号
        - preferred_signals 白名单
        """
        if not self._env_adapt:
            return signal

        # CRISIS: 全部跳过
        if self._env_adapt.get("force_cash") or self._env_adapt.get("signal_boost", 1) <= 0:
            return None

        # preferred_signals 白名单
        preferred = self._env_adapt.get("preferred_signals", [])
        if preferred and signal.signal_type not in preferred:
            return None

        # 震荡市跳过趋势信号
        if self._env_adapt.get("skip_trend_signals"):
            trend_signals = {"123_FULL", "123_CONFIRMING", "2B_MEDIUM", "2B_LONG"}
            if signal.signal_type in trend_signals:
                return None

        # 应用 signal_boost
        boost = self._env_adapt.get("signal_boost", 1.0)
        if boost != 1.0:
            return Signal(
                direction=signal.direction,
                confidence=min(signal.confidence * boost, 0.95),
                stop=signal.stop,
                target=signal.target,
                signal_type=signal.signal_type,
            )

        return signal

    def _apply_dow(self, signal: Signal) -> Optional[Signal]:
        """Layer 4: 道氏确认

        两个指数方向不一致 → 降低置信度 0.7x
        只有一个指数（数据不可用）→ 跳过道氏层
        """
        if self._dow_confirmed is None:
            return signal  # 无数据，跳过

        if self._dow_confirmed != signal.direction:
            # 方向不一致 → 降权
            return Signal(
                direction=signal.direction,
                confidence=signal.confidence * 0.7,
                stop=signal.stop,
                target=signal.target,
                signal_type=signal.signal_type,
            )
        return signal


class DowConfirmation:
    """道氏指数相互确认（ch04）

    沪深300 和上证指数必须同向才确认。
    """

    @staticmethod
    def check(csi300_trend: str, sh_index_trend: Optional[str]) -> Optional[int]:
        """检查道氏确认

        Args:
            csi300_trend: 沪深300 趋势方向
            sh_index_trend: 上证指数趋势方向（可能为 None）

        Returns:
            1 做多确认 / -1 做空确认 / None 无确认
        """
        if sh_index_trend is None:
            return None  # 数据不可用，跳过

        if csi300_trend == "UP" and sh_index_trend == "UP":
            return 1
        elif csi300_trend == "DOWN" and sh_index_trend == "DOWN":
            return -1
        return None  # 不一致或无明确趋势
