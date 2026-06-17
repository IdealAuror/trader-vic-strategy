import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trader_vic.portfolio.mgr import PortfolioMgr, Position, TradeRecord
from trader_vic.core.risk import StopManager


def test_init():
    pm = PortfolioMgr(1_000_000)
    assert pm.cash == 1_000_000
    assert len(pm.positions) == 0


def test_enter():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    assert "000001" in pm.positions
    assert pm.positions["000001"].shares == 1000
    assert pm.positions["000001"].entry_price == 100


def test_can_enter():
    pm = PortfolioMgr(1_000_000)
    assert pm.can_enter("000001", 1000, 100, 98)
    assert not pm.can_enter("000001", 0, 100, 98)
    assert not pm.can_enter("000001", -1, 100, 98)


def test_can_enter_duplicate():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    assert not pm.can_enter("000001", 1000, 100, 98)


def test_exit():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    rec = pm.exit("000001", 110, "STOP_HIT")
    assert rec is not None
    assert "000001" not in pm.positions
    assert len(pm.trades) == 1
    # 卖出资金进入 _pending_cash（T+1 结算前）
    assert pm.cash + pm._pending_cash > 1_000_000


def test_exit_nonexistent():
    pm = PortfolioMgr(1_000_000)
    assert pm.exit("NONE", 100) is None


def test_partial_exit():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 200, 100, 98, 115)
    rec = pm.partial_exit("000001", 115, 100, "TAKE_PROFIT")
    assert rec is not None
    assert pm.positions["000001"].shares == 100
    assert len(pm.trades) == 1


def test_partial_exit_full():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 200, 100, 98, 115)
    rec = pm.partial_exit("000001", 110, 300, "EXIT")
    assert rec is not None
    assert "000001" not in pm.positions


def test_risk_used():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    risk = pm.risk_used()
    assert risk > 0
    assert risk == abs(100 - 98) * 1000


def test_total_risk_cap():
    pm = PortfolioMgr(1_000_000)
    pm.set_position_cap(0.5)
    cap = pm.total_risk_cap()
    assert cap == 1_000_000 * 0.15 * 0.5


def test_mark_to_market():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    value = pm.mark_to_market({"000001": 110})
    assert value == (1_000_000 - 100_000) + 1000 * 110


def test_increment_bars():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    pm.increment_bars_held()
    assert pm.positions["000001"].bars_held == 1


def test_clear_trades():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    pm.exit("000001", 110, "STOP_HIT")
    assert len(pm.trades_today) == 1
    pm.clear_trades_today()
    assert len(pm.trades_today) == 0


import tempfile


def test_save_load_state():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    path = os.path.join(tempfile.mkdtemp(), "state.json")
    pm.save_state(path)
    assert os.path.exists(path)

    pm2 = PortfolioMgr(1_000_000)
    ok = pm2.load_state(path)
    assert ok
    assert "000001" in pm2.positions
    assert pm2.positions["000001"].shares == 1000


def test_partial_exit_cash_available():
    pm = PortfolioMgr(1_000_000)
    pm.enter("000001", 1000, 100, 98, 115)
    pm.partial_exit("000001", 115, 500, "TAKE_PROFIT")
    # 部分卖出后，可用资金应增加
    assert pm._pending_cash > 0


if __name__ == "__main__":
    import os
    import tempfile
    tmp_path = tempfile.mkdtemp()

    test_init()
    test_enter()
    test_can_enter()
    test_can_enter_duplicate()
    test_exit()
    test_exit_nonexistent()
    test_partial_exit()
    test_partial_exit_full()
    test_risk_used()
    test_total_risk_cap()
    test_mark_to_market()
    test_increment_bars()
    test_clear_trades()
    test_save_load_state()
    test_partial_exit_cash_available()
    print("所有 portfolio 测试通过 ✅")
