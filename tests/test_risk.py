import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trader_vic.core.risk import RiskRewardFilter, StopManager, TimeStop, ConsecutiveLossPause


def test_rrr_filter():
    assert RiskRewardFilter.check(100, 99, 106, 3.0)
    assert not RiskRewardFilter.check(100, 99, 102, 3.0)


def test_rrr_ratio():
    r = RiskRewardFilter.rr_ratio(100, 99, 106)
    assert abs(r - 6.0) < 0.01


def test_stop_manager_long():
    sm = StopManager(100, 99)
    assert sm.stop == 99
    assert sm.update(103, 100) == "HOLD"
    assert sm.stop >= 99


def test_stop_manager_stop_hit():
    sm = StopManager(100, 99)
    assert sm.update(100, 98) == "STOP_HIT"


def test_stop_manager_take_profit():
    sm = StopManager(100, 99)
    assert sm.check_take_profit(115, 110) == "TAKE_PROFIT"
    assert sm.take_profit_triggered


def test_time_stop():
    assert not TimeStop.check(5, 10)
    assert TimeStop.check(10, 10)


def test_consecutive_loss_pause():
    cp = ConsecutiveLossPause(3, 5)
    assert cp.can_trade()
    cp.record_result(False)
    cp.record_result(False)
    assert cp.can_trade()
    cp.record_result(False)
    assert not cp.can_trade()


def test_consecutive_loss_reset():
    cp = ConsecutiveLossPause(3, 5)
    cp.record_result(False)
    cp.record_result(True)
    assert cp.loss_streak == 0


if __name__ == "__main__":
    test_rrr_filter()
    test_rrr_ratio()
    test_stop_manager_long()
    test_stop_manager_stop_hit()
    test_stop_manager_take_profit()
    test_time_stop()
    test_consecutive_loss_pause()
    test_consecutive_loss_reset()
    print("所有 risk 测试通过 ✅")
