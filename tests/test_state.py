import json
import pytest
from pathlib import Path
import state


def test_load_nonexistent_returns_defaults(tmp_path: Path):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)
    assert s["orders"] == {}
    assert s["payment_attempt_started"] is None
    assert s["consecutive_errors"] == 0
    assert not state_file.exists()


def test_save_and_load_roundtrip(tmp_path: Path):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)
    s2 = state.save(s, state_file, total_spent=12.5, last_status="IN_STOCK")
    assert s2["total_spent"] == 12.5
    assert s2["last_status"] == "IN_STOCK"

    loaded = state.load(state_file)
    assert loaded["total_spent"] == 12.5
    assert loaded["last_status"] == "IN_STOCK"


def test_corrupt_state_is_quarantined_and_flagged(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{corrupt json: true", encoding="utf-8")

    loaded = state.load(state_file)
    assert loaded.get("corrupt") is True
    assert "corrupt_path" in loaded
    assert not state_file.exists()  # quarantined

    quarantined = Path(loaded["corrupt_path"])
    assert quarantined.exists()
    assert "corrupt json" in quarantined.read_text(encoding="utf-8")

    can, reason = state.can_order(loaded, "123")
    assert can is False
    assert "corrupt" in reason


def test_can_order_rules():
    fresh = dict(state.DEFAULTS)
    assert state.can_order(fresh, "A", 2)[0] is True

    # This specific target reached its limit (default max_orders=1)
    rec = {"order_id": "ORD-1", "spent": 100.0, "ts": 0}
    bought = dict(state.DEFAULTS, orders={"A": [rec]})
    can, reason = state.can_order(bought, "A", 2)
    assert can is False and "already ordered 1 of 1" in reason
    # ...but a different target is still fair game
    assert state.can_order(bought, "B", 2)[0] is True

    # Every order across targets placed
    all_done = dict(state.DEFAULTS, orders={"A": [rec], "B": [rec]})
    can, reason = state.can_order(all_done, "C", 2)
    assert can is False and "already been placed" in reason

    # Uncertain state blocks EVERY target, not just the one in flight
    uncertain = dict(state.DEFAULTS, payment_attempt_started="A")
    assert state.needs_manual_check(uncertain) is True
    for prid in ("A", "B"):
        can, reason = state.can_order(uncertain, prid, 2)
        assert can is False
        assert "never confirmed" in reason

    # Corrupt state blocks ordering
    can, reason = state.can_order(dict(state.DEFAULTS, corrupt=True), "A", 2)
    assert can is False and "corrupt" in reason

    assert state.can_order(fresh, "A", 0)[0] is False


def test_spend_cap_blocks_the_order_that_would_cross_it():
    s = dict(state.DEFAULTS, total_spent=600.0)
    can, reason = state.can_order(s, "A", 2, max_total_spend_inr=800.0, order_total=150.0)
    assert can is True
    can, reason = state.can_order(s, "A", 2, max_total_spend_inr=800.0, order_total=250.0)
    assert can is False
    assert "ceiling" in reason


def test_record_order_marks_bought_and_clears_the_in_flight_flag(tmp_path):
    f = tmp_path / "state.json"
    s = state.save(dict(state.DEFAULTS), f, payment_attempt_started="799027")
    s = state.record_order(s, "799027", "ORD-9", 549.0, f)
    assert s["payment_attempt_started"] is None
    assert s["total_spent"] == 549.0
    assert state.is_bought(s, "799027") is True
    assert state.needs_manual_check(s) is False
    assert state.load(f)["orders"]["799027"][0]["order_id"] == "ORD-9"


def test_repeat_orders_until_max_orders(tmp_path):
    """D14: the same car may be ordered again, one unit per order, up to max_orders."""
    f = tmp_path / "state.json"
    s = dict(state.DEFAULTS)
    for i in range(3):
        assert state.can_order(s, "1454828", 6, max_orders=3)[0] is True
        s = state.record_order(s, "1454828", f"ORD-{i}", 555.0, f)
    can, reason = state.can_order(s, "1454828", 6, max_orders=3)
    assert can is False and "3 of 3" in reason
    assert state.order_count(state.load(f), "1454828") == 3
    assert state.can_order(s, "1416802", 6, max_orders=3)[0] is True  # Ram unaffected
    assert state.all_bought(s, 6) is False and state.all_bought(s, 3) is True


def test_single_record_state_migrates_to_a_list(tmp_path):
    """A state file written before repeat orders keeps its order, now as a list."""
    import json
    f = tmp_path / "state.json"
    f.write_text(json.dumps({"orders": {"799027": {"order_id": "X", "spent": 1, "ts": 0}}}),
                 encoding="utf-8")
    s = state.load(f)
    assert state.order_count(s, "799027") == 1
    assert state.is_bought(s, "799027") is True


def test_legacy_state_with_an_order_is_flagged_not_guessed(tmp_path):
    """The old format had no product id, so a recorded order cannot be mapped."""
    import json
    f = tmp_path / "state.json"
    f.write_text(json.dumps({"order_placed": True, "order_id": "ORD-OLD"}), encoding="utf-8")
    s = state.load(f)
    assert s.get("corrupt") is True
    assert state.can_order(s, "799027", 2)[0] is False
