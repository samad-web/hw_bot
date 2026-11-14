import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import main
import state


def test_parse_args_defaults():
    args = main.parse_args([])
    assert args.config == "config.yaml"
    assert args.env == ".env"
    assert args.state == state.DEFAULT_PATH
    assert args.mode is None
    assert args.dry_run is False
    assert args.login is False
    assert args.capture is False


def test_parse_args_overrides():
    args = main.parse_args(["--mode", "C", "--dry-run", "--config", "custom.yaml", "--state", "custom.json"])
    assert args.mode == "C"
    assert args.dry_run is True
    assert args.config == "custom.yaml"
    assert args.state == "custom.json"


def test_main_exits_if_uncertain_state(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "products: [{id: '1', name: 'Test', max_price_inr: 100}]\n"
        "delivery: {label: 'Home'}\n"
        "mode: 'A'\n"
        "polling: {interval_seconds: 30}\n"
        "safety: {max_orders_total: 1}\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_CHAT_ID=12345\n", encoding="utf-8"
    )
    # Uncertain state on disk
    state_file = tmp_path / "state.json"
    state.save(state.DEFAULTS, state_file, payment_attempt_started="1")

    with patch("notifier.send") as mock_send:
        rc = main.main([
            "--config", str(cfg_file),
            "--env", str(tmp_path / ".env"),
            "--state", str(state_file),
        ])
        assert rc == 1
        assert mock_send.called
        assert "Uncertain state" in mock_send.call_args[0][0]


def _write_mode_a_project(tmp_path: Path) -> Path:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "products: [{id: '1', name: 'Hot Wheels GTR', url: 'https://blinkit.com/prn/x/prid/1', max_price_inr: 100}]\n"
        "delivery: {label: 'Home', pincode: '400001'}\n"
        "mode: 'A'\n"
        "polling: {interval_seconds: 30, jitter_seconds: 0}\n"
        "safety: {max_orders_total: 1}\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_CHAT_ID=12345\n", encoding="utf-8"
    )
    return cfg_file


def test_loop_refetches_the_page_every_iteration(tmp_path: Path, monkeypatch):
    """Regression: the loop used to skip goto() once page.url matched the target,
    so it re-read a stale DOM forever and could never see a restock."""
    from checker import CheckResult, CheckResultKind

    cfg_file = _write_mode_a_project(tmp_path)
    state_file = tmp_path / "state.json"

    page = MagicMock()
    page.url = "https://blinkit.com/prn/x/prid/1"  # already on target after first goto
    ctx = MagicMock()
    ctx.new_page.return_value = page
    pw = MagicMock()
    pw.chromium.launch_persistent_context.return_value = ctx
    pw_cm = MagicMock()
    pw_cm.__enter__.return_value = pw

    sleeps = {"n": 0}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= 3:
            raise SystemExit  # break out after a few iterations

    monkeypatch.setattr(main, "sync_playwright", lambda: pw_cm)
    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    monkeypatch.setattr(main.notifier, "send", MagicMock())
    monkeypatch.setattr(main.notifier, "poll_commands", lambda cfg, st, sp=None: (st, False))
    monkeypatch.setattr(
        main.checker, "check",
        lambda p, c, prod: CheckResult(CheckResultKind.OUT_OF_STOCK, product_title="Hot Wheels GTR"),
    )

    with pytest.raises(SystemExit):
        main.main(["--config", str(cfg_file), "--env", str(tmp_path / ".env"),
                   "--state", str(state_file)])

    assert page.goto.call_count >= 3, "page must be re-fetched on every loop iteration"


def test_loop_writes_state_to_the_path_given_by_state_flag(tmp_path: Path, monkeypatch):
    """Regression: saves ignored --state and always wrote ./state.json, so in Docker
    the single-order lock was read from one file and written to another."""
    from checker import CheckResult, CheckResultKind

    cfg_file = _write_mode_a_project(tmp_path)
    state_file = tmp_path / "custom_state.json"

    page = MagicMock()
    ctx = MagicMock()
    ctx.new_page.return_value = page
    pw = MagicMock()
    pw.chromium.launch_persistent_context.return_value = ctx
    pw_cm = MagicMock()
    pw_cm.__enter__.return_value = pw

    def fake_sleep(_seconds):
        raise SystemExit

    monkeypatch.setattr(main, "sync_playwright", lambda: pw_cm)
    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    monkeypatch.setattr(main.notifier, "send", MagicMock())
    monkeypatch.setattr(main.notifier, "poll_commands", lambda cfg, st, sp=None: (st, False))
    monkeypatch.setattr(
        main.checker, "check",
        lambda p, c, prod: CheckResult(CheckResultKind.OUT_OF_STOCK, product_title="Hot Wheels GTR"),
    )

    with pytest.raises(SystemExit):
        main.main(["--config", str(cfg_file), "--env", str(tmp_path / ".env"),
                   "--state", str(state_file)])

    assert state_file.exists(), "--state path must receive the writes"
    assert not (Path.cwd() / "state.json.tmp").exists()


def _run_loop(tmp_path, monkeypatch, gotos, checks, max_sleeps, step_s=60):
    """Drive main() with a fake clock that advances step_s per sleep. Returns sent texts."""
    cfg_file = _write_mode_a_project(tmp_path)
    page = MagicMock(); page.goto.side_effect = gotos
    ctx = MagicMock(); ctx.new_page.return_value = page
    pw = MagicMock(); pw.chromium.launch_persistent_context.return_value = ctx
    pw_cm = MagicMock(); pw_cm.__enter__.return_value = pw
    clock = {"t": 1_000_000.0, "n": 0}
    def fake_sleep(_s):
        clock["n"] += 1; clock["t"] += step_s
        if clock["n"] >= max_sleeps:
            raise SystemExit
    sent = []
    monkeypatch.setenv("BROWSER_PROXY", "socks5://127.0.0.1:1055")
    monkeypatch.setattr(main, "sync_playwright", lambda: pw_cm)
    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    monkeypatch.setattr(main.time, "time", lambda: clock["t"])
    monkeypatch.setattr(main.notifier, "send", lambda t, c, priority=False: sent.append(t) or {"whatsapp": True})
    monkeypatch.setattr(main.notifier, "poll_commands", lambda cfg, st, sp=None: (st, False))
    monkeypatch.setattr(main.checker, "check", checks)
    with pytest.raises(SystemExit):
        main.main(["--config", str(cfg_file), "--env", str(tmp_path / ".env"),
                   "--state", str(tmp_path / "state.json")])
    return sent


def test_navigation_failure_skips_check_and_alerts_relay_once(tmp_path: Path, monkeypatch):
    """F10: a failed goto (relay offline) must not check the stale previous DOM; User choice
    2026-11-14: the outage itself is log-only; recovery after 5+ min is announced once."""
    from checker import CheckResult, CheckResultKind
    fail = Exception("ERR_SOCKS_CONNECTION_FAILED")
    checks = MagicMock(return_value=CheckResult(CheckResultKind.OUT_OF_STOCK, product_title="x"))
    sent = _run_loop(tmp_path, monkeypatch, [fail] * 7 + [None, None], checks, max_sleeps=9)
    assert checks.call_count == 2, "check runs only for the successful gotos, never the failed"
    assert not any("RELAY OFFLINE" in t for t in sent), "outages are log-only (user choice)"
    assert sum(t.startswith("Connection to Blinkit is back") for t in sent) == 1


def test_short_relay_blip_sends_no_message(tmp_path: Path, monkeypatch):
    """Spam fix: a 2-minute blip (2 failed gotos) is neither an outage nor a recovery."""
    from checker import CheckResult, CheckResultKind
    fail = Exception("ERR_SOCKS_CONNECTION_FAILED")
    checks = MagicMock(return_value=CheckResult(CheckResultKind.OUT_OF_STOCK, product_title="x"))
    sent = _run_loop(tmp_path, monkeypatch, [fail, fail, None, None], checks, max_sleeps=4)
    assert not any("RELAY OFFLINE" in t or "is back" in t for t in sent)


def test_page_error_warns_once_per_streak_not_per_blip(tmp_path: Path, monkeypatch):
    """Spam fix: isolated unknown_layout reads stay silent; a streak of ERROR_ALERT_AFTER warns once."""
    from checker import CheckResult, CheckResultKind
    err = CheckResult(CheckResultKind.ERROR, error_kind="unknown_layout", message="no bar")
    ok = CheckResult(CheckResultKind.OUT_OF_STOCK, product_title="x")
    seq = [err, ok, err, ok] + [err] * 8
    checks = MagicMock(side_effect=seq)
    monkeypatch.setattr(main.hardening, "save_failure_capture", lambda *a, **k: None)
    sent = _run_loop(tmp_path, monkeypatch, [None] * len(seq), checks, max_sleeps=len(seq))
    assert sum(t.startswith("Bot warning") for t in sent) == 1


def test_login_error_warns_immediately_once(tmp_path: Path, monkeypatch):
    """A logged-out session never self-heals, so it alerts on the first failure, but only once."""
    from checker import CheckResult, CheckResultKind
    err = CheckResult(CheckResultKind.ERROR, error_kind="login", message="logged out")
    checks = MagicMock(return_value=err)
    monkeypatch.setattr(main.hardening, "save_failure_capture", lambda *a, **k: None)
    sent = _run_loop(tmp_path, monkeypatch, [None] * 4, checks, max_sleeps=3)
    assert sum(t.startswith("Bot warning") for t in sent) == 1
