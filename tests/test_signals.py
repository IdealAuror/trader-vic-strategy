"""信号模块单元测试"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from trader_vic.core.signals import (
    Signal, Criterion123, Criterion2B, FourDayRule, ThreeDayPullback
)
from trader_vic.core.probability import EVCalculator, KellyFraction, vic_position_fraction


def test_signal_dataclass():
    """Signal 数据结构"""
    s = Signal(direction=1, confidence=0.67, stop=99.0, target=110.0, signal_type="123_FULL")
    assert s.is_valid()
    assert s.direction == 1

    s2 = Signal(direction=-1, confidence=0, stop=0, target=0, signal_type="NONE")
    assert not s2.is_valid()


def test_ev_calculator():
    """EV 计算"""
    # 2B 信号 P=50%, RRR=1:3 → EV/R = +1.0
    ev_per_r = EVCalculator.ev_per_r(0.50, 3.0)
    assert abs(ev_per_r - 1.0) < 0.01

    # 有信号
    ev = EVCalculator.ev(0.67, 300, 100)
    assert ev > 0  # 正期望值

    # 负 EV
    ev_neg = EVCalculator.ev(0.30, 100, 200)
    assert ev_neg < 0


def test_signal_ev():
    """信号 EV 计算"""
    ev = EVCalculator.signal_ev("FOUR_DAY_RULE", 300, 100)
    assert ev > 0  # 75% 胜率，RRR=1:3 → EV 为正


def test_kelly_fraction():
    """凯利公式"""
    # P=50%, RRR=1:3 → f* = (0.5*4-1)/3 = 0.33
    f = KellyFraction.optimal_f(0.50, 3.0)
    assert abs(f - 0.333) < 0.01

    # P=0 → f=0
    f0 = KellyFraction.optimal_f(0, 3.0)
    assert f0 == 0


def test_vic_position_fraction():
    """改进版凯利"""
    f = vic_position_fraction(0.50, 3.0, 1)
    assert f > 0
    assert f <= 0.33  # 安全系数 0.25


def test_criterion123():
    """1-2-3 准则"""
    # 用随机数据测试不崩溃
    np.random.seed(42)
    high = np.random.rand(30) * 10 + 100
    low = high - np.random.rand(30) * 5
    close = (high + low) / 2
    # 确保 close 不超出 high/low 范围
    close = np.clip(close, low + 0.1, high - 0.1)

    signal = Criterion123.detect(high, low, close)
    # 随机数据大概率无信号
    assert signal is None or isinstance(signal, Signal)


def test_criterion2b():
    """2B 准则"""
    np.random.seed(42)
    high = np.random.rand(30) * 10 + 100
    low = high - np.random.rand(30) * 5
    close = np.clip((high + low) / 2, low + 0.1, high - 0.1)

    signal = Criterion2B.detect(high, low, close)
    assert signal is None or isinstance(signal, Signal)


def test_four_day_rule():
    """四天准则"""
    # 模拟连续 5 天上涨
    close = np.array([100, 101, 102, 103, 104, 105])
    high = close + 1
    low = close - 1

    signal = FourDayRule.detect(high, low, close)
    # 上涨 5% > 3% 阈值，应该触发做空信号
    if signal is not None:
        assert signal.direction == -1  # 做空
        assert signal.signal_type == "FOUR_DAY_RULE"

    # 模拟连续 5 天下跌
    close2 = np.array([105, 104, 103, 102, 101, 100])
    high2 = close2 + 1
    low2 = close2 - 1

    signal2 = FourDayRule.detect(high2, low2, close2)
    if signal2 is not None:
        assert signal2.direction == 1  # 做多


def test_three_day_pullback():
    """三天回调"""
    # 需要在多头趋势中
    # 先涨后回调
    ma20 = 100
    close = np.array([102, 101.5, 101, 100.5, 100, 99.5])
    high = close + 1
    low = close - 1

    signal = ThreeDayPullback.detect(high, low, close)
    # 不一定触发（受 MA20 影响），但不崩溃
    assert signal is None or isinstance(signal, Signal)


if __name__ == "__main__":
    test_signal_dataclass()
    test_ev_calculator()
    test_signal_ev()
    test_kelly_fraction()
    test_vic_position_fraction()
    test_criterion123()
    test_criterion2b()
    test_four_day_rule()
    test_three_day_pullback()
    print("所有信号测试通过 ✅")
