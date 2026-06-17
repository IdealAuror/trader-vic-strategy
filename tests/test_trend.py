"""趋势模块单元测试"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from trader_vic.core.trend import (
    SwingDetector, TrendAge, RetracementLocator, MarketPhase, TrendDirection
)


def test_swing_detector_initial_state():
    """SwingDetector 初始状态为 UNDEFINED"""
    d = SwingDetector(lookback=3)
    assert d.state == TrendDirection.UNDEFINED


def test_swing_detector_up_trend():
    """上升趋势检测：HH + HL"""
    d = SwingDetector(lookback=3)
    # 上升趋势需要清晰的摆动点：涨→回调→更高→回调→更高
    # 这样形成 HH(更高高点) 和 HL(更高低点)
    prices = [
        (100, 95, 98),   # 1
        (105, 97, 103),  # 2 ← 第一个高点
        (102, 98, 100),  # 3 回调
        (101, 96, 99),   # 4 继续回调
        (100, 97, 98),   # 5 ← 第一个低点
        (103, 99, 101),  # 6
        (108, 102, 106), # 7
        (112, 105, 110), # 8 ← 第二个高点（>105 = HH）
        (109, 104, 107), # 9 回调
        (107, 101, 105), # 10
        (106, 100, 104), # 11 ← 第二个低点（>97 = HL）
        (110, 103, 108), # 12
        (115, 107, 113), # 13
        (118, 110, 116), # 14 ← 第三个高点（>112 = HH）
        (114, 108, 112), # 15
        (112, 106, 110), # 16 ← 第三个低点（>100 = HL）
    ]
    for h, l, c in prices:
        d.update(h, l, c)
    assert d.state == TrendDirection.UP, f"Expected UP, got {d.state}"


def test_swing_detector_down_trend():
    """下降趋势检测：LH + LL"""
    d = SwingDetector(lookback=3)
    prices = [
        (200, 195, 198), # 1
        (195, 190, 193), # 2 ← 第一个低点
        (197, 192, 195), # 3 反弹
        (196, 193, 194), # 4
        (198, 194, 196), # 5 ← 第一个高点
        (193, 188, 191), # 6
        (190, 185, 188), # 7
        (187, 182, 185), # 8 ← 第二个低点（<190 = LL）
        (189, 184, 187), # 9 反弹
        (188, 185, 186), # 10
        (191, 186, 189), # 11 ← 第二个高点（<198 = LH）
        (185, 180, 183), # 12
        (182, 177, 180), # 13
        (180, 175, 178), # 14 ← 第三个低点（<182 = LL）
        (183, 178, 181), # 15
        (184, 179, 182), # 16 ← 第三个高点（<189 = LH）
    ]
    for h, l, c in prices:
        d.update(h, l, c)
    assert d.state == TrendDirection.DOWN, f"Expected DOWN, got {d.state}"


def test_retracement_locator():
    """次级折返定位"""
    # 波段高点 100，低点 80，当前 90 → 折返 50%
    ratio = RetracementLocator.retracement_ratio(100, 80, 90)
    assert abs(ratio - 0.50) < 0.01

    assert RetracementLocator.is_healthy_retracement(0.5) is True
    assert RetracementLocator.is_healthy_retracement(0.2) is False
    assert RetracementLocator.is_healthy_retracement(0.8) is False


def test_market_phase():
    """市场四阶段"""
    phase = MarketPhase.phase(TrendDirection.UP, "INCREASING")
    assert phase.value == "MARKUP"

    phase = MarketPhase.phase(TrendDirection.DOWN, None, 0.8)
    assert phase.value == "MARKDOWN"


def test_trend_age():
    """趋势年龄百分位"""
    age = TrendAge()
    # 未设置开始日期 → 0
    pct = age.percentile(None, TrendDirection.UP)
    assert pct == 0.0


if __name__ == "__main__":
    test_swing_detector_initial_state()
    test_swing_detector_up_trend()
    test_swing_detector_down_trend()
    test_retracement_locator()
    test_market_phase()
    test_trend_age()
    print("所有趋势测试通过 ✅")
