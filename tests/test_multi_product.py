"""F8 acceptance: several targets, bought one at a time."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import main
import state
from checker import CheckResult, CheckResultKind
from conftest import K5, RAM

TWO_TARGET_YAML = (
    "products:\n"
    "  - {id: '799027', name: 'Hot Wheels 1985 Chevrolet K5 Blazer Die Cast Car',"
    " url: 'https://blinkit.com/prn/x/prid/799027', max_price_inr: 659}\n"
    "  - {id: '1416802', name: 'Hot Wheels 23 Ram 1500 Die Cast Car',"
    " url: 'https://blinkit.com/prn/x/prid/1416802', max_price_inr: 215}\n"
    "delivery: {label: 'Home', pincode: '400001'}\n"
    "mode: 'A'\n"
    "polling: {interval_seconds: 40, jitter_seconds: 0}\n"
    "safety: {max_orders_total: 2, max_total_spend_inr: 800}\n"
)


def _project(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(TWO_TARGET_YAML, encoding="utf-8")
    (tmp_path / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_CHAT_ID=12345\n", encoding="utf-8"
    )
    return cfg


def _run_one_cycle(tmp_path, monkeypatch, state_file, check_impl):
    """Drive main() through a single cycle, then bail out of the sleep."""
    page = MagicMock()
    ctx = MagicMock()
    ctx.new_page.return_value = page
    pw = MagicMock()
    pw.chromium.launch_persistent_context.return_value = ctx
    pw_cm = MagicMock()
    pw_cm.__enter__.return_value = pw

    calls = {"sleep": 0}

    def fake_sleep(_s):
        calls["sleep"] += 1
        if calls["sleep"] >= 2:
            raise SystemExit

    monkeypatch.setattr(main, "sync_playwright", lambda: pw_cm)
    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    monkeypatch.setattr(main.notifier, "send", MagicMock())
    monkeypatch.setattr(main.notifier, "poll_commands", lambda cfg, st, sp=None: (st, False))
    monkeypatch.setattr(main.checker, "check", check_impl)

    with pytest.raises(SystemExit):
        main.main(["--config", str(_project(tmp_path)), "--env", str(tmp_path / ".env"),
                   "--state", str(state_file)])
    return page


def test_ac1_cycle_visits_every_outstanding_target(tmp_path: Path, monkeypatch):
    state_file = tmp_path / "state.json"
    page = _run_one_cycle(
        tmp_path, monkeypatch, state_file,
        lambda p, c, prod: CheckResult(CheckResultKind.OUT_OF_STOCK, product_title=prod.name),
    )
    visited = {c.args[0] for c in page.goto.call_args_list}
    assert K5.url in visited
    assert RAM.url in visited


def test_ac1_a_bought_target_is_dropped_from_the_watch_list(tmp_path: Path, monkeypatch):
    """Once a car is bought the bot must stop fetching its page."""
    state_file = tmp_path / "state.json"
    state.save(dict(state.DEFAULTS), state_file,
               orders={"799027": {"order_id": "ORD-1", "spent": 549.0, "ts": 0}},
               total_spent=549.0)

    page = _run_one_cycle(
        tmp_path, monkeypatch, state_file,
        lambda p, c, prod: CheckResult(CheckResultKind.OUT_OF_STOCK, product_title=prod.name),
    )
    visited = {c.args[0] for c in page.goto.call_args_list}
    assert RAM.url in visited
    assert K5.url not in visited, "an already-bought target must not be polled again"


def test_ac2_bot_exits_once_every_target_is_bought(tmp_path: Path, monkeypatch):
    state_file = tmp_path / "state.json"
    state.save(dict(state.DEFAULTS), state_file, orders={
        "799027": {"order_id": "ORD-1", "spent": 549.0, "ts": 0},
        "1416802": {"order_id": "ORD-2", "spent": 179.0, "ts": 0},
    }, total_spent=728.0)

    monkeypatch.setattr(main.notifier, "send", MagicMock())
    rc = main.main(["--config", str(_project(tmp_path)), "--env", str(tmp_path / ".env"),
                    "--state", str(state_file)])
    assert rc == 0  # exits without launching a browser at all


def test_ac4_in_flight_payment_blocks_every_target(tmp_path: Path, monkeypatch):
    """A payment of unknown outcome stops the whole bot, not just that car."""
    state_file = tmp_path / "state.json"
    state.save(dict(state.DEFAULTS), state_file, payment_attempt_started="1416802")

    sent = MagicMock()
    monkeypatch.setattr(main.notifier, "send", sent)
    rc = main.main(["--config", str(_project(tmp_path)), "--env", str(tmp_path / ".env"),
                    "--state", str(state_file)])
    assert rc == 1
    assert sent.called
    assert "Uncertain state" in sent.call_args[0][0]


def test_mode_a_mute_is_per_product_and_survives_restart(tmp_path: Path, monkeypatch):
    """Alerting for one car must not mute the other."""
    import argparse

    cfg_file = _project(tmp_path)
    state_file = tmp_path / "state.json"
    import config as config_mod
    cfg = config_mod.load_config(cfg_file, env_path=tmp_path / ".env")

    sent = MagicMock()
    monkeypatch.setattr(main.notifier, "send", sent)
    args = argparse.Namespace(dry_run=False)
    s = state.load(state_file)

    s, bought = main.handle_restock(MagicMock(), cfg, K5, s, args, str(state_file))
    assert bought is False and sent.call_count == 1

    # Same car again inside the window: muted.
    s, _ = main.handle_restock(MagicMock(), cfg, K5, s, args, str(state_file))
    assert sent.call_count == 1

    # Different car: still alerts.
    s, _ = main.handle_restock(MagicMock(), cfg, RAM, s, args, str(state_file))
    assert sent.call_count == 2

    # The mute window is persisted, not held in memory.
    assert set(state.load(state_file)["last_alert_ts"]) == {K5.id, RAM.id}
