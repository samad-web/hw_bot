import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import notifier
import state
from config import Config, ProductConfig, DeliveryConfig, PollingConfig, PaymentConfig, SafetyConfig, ReliabilityConfig, SelectorsConfig, TelegramConfig, EvolutionConfig


def test_command_pause_and_resume(tmp_path: Path, mock_config: Config):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)

    reply, s, stop = notifier.handle_command("/pause", mock_config, s, str(state_file))
    assert "paused" in reply.lower()
    assert s["paused"] is True
    assert stop is False

    reply, s, stop = notifier.handle_command("/resume", mock_config, s, str(state_file))
    assert "resumed" in reply.lower()
    assert s["paused"] is False


def test_command_status(mock_config: Config):
    s = dict(state.DEFAULTS)
    with patch("notifier.get_whatsapp_status", return_value={"configured": True, "connected": True}):
        reply, s, stop = notifier.handle_command("/status", mock_config, s)
        assert "Bot Status" in reply
        assert "Mode: A" in reply
        assert "Bought: 0/1" in reply
        assert "watching Hot Wheels Nissan Skyline GT-R" in reply


def test_command_mode_switch(tmp_path: Path, mock_config: Config):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)

    reply, s, stop = notifier.handle_command("/mode B", mock_config, s, str(state_file))
    assert "Switched to Mode B" in reply
    assert s["mode"] == "B"

    # Invalid mode
    reply, s, _ = notifier.handle_command("/mode Z", mock_config, s, str(state_file))
    assert "Usage: /mode" in reply


def test_command_otp(tmp_path: Path, mock_config: Config):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)

    # Valid OTP
    reply, s, stop = notifier.handle_command("/otp 482910", mock_config, s, str(state_file))
    # An OTP must never reach disk. The relay is not implemented, so the command
    # acknowledges and discards the code.
    assert "not implemented" in reply
    assert "pending_otp" not in s
    if state_file.exists():
        assert "482910" not in state_file.read_text(encoding="utf-8")

    # Malformed OTP (alphanumeric or too short)
    reply, s, _ = notifier.handle_command("/otp 12a", mock_config, s, str(state_file))
    assert "Invalid OTP" in reply


def test_poll_commands_ignores_unauthorized_chat(tmp_path: Path, mock_config: Config):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 101,
                "message": {
                    "chat": {"id": 999999},  # Unauthorized chat
                    "text": "/pause",
                },
            }
        ],
    }

    with patch("requests.get", return_value=mock_resp), patch("notifier.send_telegram") as mock_send:
        s, stop = notifier.poll_commands(mock_config, s, str(state_file))
        assert s.get("paused") is False  # Not paused!
        assert not mock_send.called
        assert s["telegram_offset"] == 102


def test_priority_fires_local_fallback(mock_config, monkeypatch):
    """A restock (priority) must alert locally even when a remote channel 'worked'."""
    monkeypatch.setattr(notifier, "send_telegram", lambda t, c: False)
    monkeypatch.setattr(notifier, "send_whatsapp", lambda t, c: False)
    calls = []
    monkeypatch.setattr(notifier, "notify_local", lambda t: calls.append(t) or True)
    res = notifier.send("RESTOCK", mock_config, priority=True)
    assert res["local"] is True and calls == ["RESTOCK"]


def test_local_fallback_when_all_remote_fail(mock_config, monkeypatch):
    """A non-priority message still fires locally if no remote channel delivered."""
    monkeypatch.setattr(notifier, "send_telegram", lambda t, c: False)
    monkeypatch.setattr(notifier, "send_whatsapp", lambda t, c: False)
    monkeypatch.setattr(notifier, "notify_local", lambda t: True)
    res = notifier.send("hello", mock_config, priority=False)
    assert res.get("local") is True


def test_no_local_when_a_remote_succeeds(mock_config, monkeypatch):
    """Don't nag locally when a remote channel delivered a non-priority message."""
    monkeypatch.setattr(notifier, "send_telegram", lambda t, c: True)
    monkeypatch.setattr(notifier, "send_whatsapp", lambda t, c: False)
    monkeypatch.setattr(notifier, "notify_local", lambda t: True)
    res = notifier.send("hello", mock_config, priority=False)
    assert "local" not in res
