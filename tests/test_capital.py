import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trader_vic.core.capital import CapitalManager, TieredPositionSizer


def test_capital_manager_init():
    cm = CapitalManager(1_000_000)
    assert cm.level == 1
    assert cm.initial_capital == 1_000_000


def test_capital_level2():
    cm = CapitalManager(1_000_000)
    cm.update(1_150_000)
    assert cm.level == 2


def test_capital_level1_drawdown():
    cm = CapitalManager(1_000_000)
    cm.update(1_200_000)
    cm.update(900_000)
    assert cm.level == 1


def test_capital_level3():
    cm = CapitalManager(1_000_000)
    cm.locked_profit = 1_200_000
    cm.update(1_050_000)
    assert cm.level == 3


def test_lock_profit():
    cm = CapitalManager(1_000_000)
    cm.lock_profit(100_000)
    assert cm.locked_profit == 50_000


def test_max_single_risk():
    cm = CapitalManager(1_000_000)
    assert cm.max_single_risk == 15_000


def test_tiered_sizer():
    shares = TieredPositionSizer.size(1_000_000, 0.02, 100, 98)
    assert shares > 0
    assert shares % 100 == 0


def test_tiered_sizer_no_risk():
    shares = TieredPositionSizer.size(1_000_000, 0.02, 100, 100)
    assert shares == 0


def test_position_value():
    v = TieredPositionSizer.position_value(100, 50)
    assert v == 5000


def test_tiered_sizer_price_step():
    shares = TieredPositionSizer.size(1_000_000, 0.02, 50, 49, 100)
    assert shares % 100 == 0
    assert shares > 0


if __name__ == "__main__":
    test_capital_manager_init()
    test_capital_level2()
    test_capital_level1_drawdown()
    test_capital_level3()
    test_lock_profit()
    test_max_single_risk()
    test_tiered_sizer()
    test_tiered_sizer_no_risk()
    test_position_value()
    test_tiered_sizer_price_step()
    print("所有 capital 测试通过 ✅")
