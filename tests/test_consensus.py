import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trader_vic.core.consensus import ConsensusEngine, DowConfirmation
from trader_vic.core.signals import Signal


def test_tech_consensus_single():
    engine = ConsensusEngine()
    sigs = [Signal(1, 0.67, 99, 110, "123_FULL")]
    result = engine._tech_consensus(sigs)
    assert result is not None
    assert result.direction == 1


def test_tech_consensus_empty():
    engine = ConsensusEngine()
    assert engine._tech_consensus([]) is None


def test_tech_consensus_conflict():
    engine = ConsensusEngine()
    sigs = [
        Signal(1, 0.67, 99, 110, "123_FULL"),
        Signal(-1, 0.50, 101, 95, "2B_MEDIUM"),
    ]
    result = engine._tech_consensus(sigs)
    # long 权重 > short 权重 * 1.5
    if result is not None:
        assert result.direction == 1


def test_align_fundamental_neutral():
    engine = ConsensusEngine()
    engine.set_fundamental("NEUTRAL")
    sig = Signal(1, 0.67, 99, 110, "123_FULL")
    result = engine._align_fundamental(sig)
    assert result is not None


def test_align_fundamental_filter():
    import trader_vic.core.consensus as c
    orig = c.MACRO_CONFLICT_MODE
    c.MACRO_CONFLICT_MODE = "FILTER"
    engine = ConsensusEngine()
    engine.set_fundamental("BEARISH")
    sig = Signal(1, 0.67, 99, 110, "123_FULL")
    result = engine._align_fundamental(sig)
    assert result is None
    c.MACRO_CONFLICT_MODE = orig


def test_env_crisis():
    engine = ConsensusEngine()
    engine.set_environment({"force_cash": True, "signal_boost": 0.0})
    sig = Signal(1, 0.67, 99, 110, "123_FULL")
    result = engine._apply_environment(sig)
    assert result is None


def test_dow_no_data():
    engine = ConsensusEngine()
    sig = Signal(1, 0.67, 99, 110, "123_FULL")
    result = engine._apply_dow(sig)
    assert result is sig


def test_dow_mismatch():
    engine = ConsensusEngine()
    engine.set_dow_confirmation(-1)
    sig = Signal(1, 0.67, 99, 110, "123_FULL")
    result = engine._apply_dow(sig)
    assert result is not None
    assert result.confidence < sig.confidence


def test_dow_confirmation():
    assert DowConfirmation.check("UP", "UP") == 1
    assert DowConfirmation.check("DOWN", "DOWN") == -1
    assert DowConfirmation.check("UP", "DOWN") is None
    assert DowConfirmation.check("UP", None) is None


if __name__ == "__main__":
    test_tech_consensus_single()
    test_tech_consensus_empty()
    test_tech_consensus_conflict()
    test_align_fundamental_neutral()
    test_align_fundamental_filter()
    test_env_crisis()
    test_dow_no_data()
    test_dow_mismatch()
    test_dow_confirmation()
    print("所有 consensus 测试通过 ✅")
