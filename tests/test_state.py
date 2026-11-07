import json
import pytest
from pathlib import Path
import state


def test_load_nonexistent_returns_defaults(tmp_path: Path):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)
    assert s["order_placed"] is False
    assert s["payment_attempt_started"] is False
    assert s["consecutive_errors"] == 0
    assert not state_file.exists()


def test_save_and_load_roundtrip(tmp_path: Path):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)
    s2 = state.save(s, state_file, order_id="ORD-1234", last_status="IN_STOCK")
    assert s2["order_id"] == "ORD-1234"
    assert s2["last_status"] == "IN_STOCK"

    loaded = state.load(state_file)
    assert loaded["order_id"] == "ORD-1234"
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

    can, reason = state.can_order(loaded)
    assert can is False
    assert "corrupt" in reason


def test_can_order_rules():
    # Fresh state
    fresh = dict(state.DEFAULTS)
    can, _ = state.can_order(fresh)
    assert can is True

    # Order already placed
    placed = dict(state.DEFAULTS, order_placed=True)
    can, reason = state.can_order(placed)
    assert can is False
    assert "already placed" in reason

    # Uncertain state (payment started, not confirmed)
    uncertain = dict(state.DEFAULTS, payment_attempt_started=True, order_placed=False)
    assert state.needs_manual_check(uncertain) is True
    can, reason = state.can_order(uncertain)
    assert can is False
    assert "manual" in reason or "previous payment" in reason

    # Payment started and order confirmed
    confirmed = dict(state.DEFAULTS, payment_attempt_started=True, order_placed=True)
    assert state.needs_manual_check(confirmed) is False
    can, _ = state.can_order(confirmed)
    assert can is False  # order_placed is True

    # max_orders_total < 1
    can, reason = state.can_order(fresh, max_orders_total=0)
    assert can is False
