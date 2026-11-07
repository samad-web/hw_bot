import pytest
from pathlib import Path
from unittest.mock import MagicMock
import hardening


def test_next_delay_schedule():
    assert hardening.next_delay(0) == 0
    assert hardening.next_delay(1) == 60
    assert hardening.next_delay(2) == 120
    assert hardening.next_delay(3) == 300
    assert hardening.next_delay(4) == 900
    assert hardening.next_delay(5) == 900
    assert hardening.next_delay(10) == 900


def test_calculate_interval_floor():
    for _ in range(1000):
        # Base 15, jitter 10 -> would be 5..25 without floor
        delay = hardening.calculate_interval(15, 10, min_floor=20)
        assert delay >= 20.0


def test_save_failure_capture_and_pruning(tmp_path: Path):
    mock_page = MagicMock()
    mock_page.content.return_value = "<html><body>Error page</body></html>"

    capture_base = tmp_path / "capture"

    # Save 25 failure captures
    for i in range(25):
        d = capture_base / f"100{i:02d}_error"
        d.mkdir(parents=True, exist_ok=True)
        (d / "page.html").write_text("dummy")

    # One more through function
    saved = hardening.save_failure_capture(mock_page, "unknown_layout", base_dir=capture_base)
    assert saved is not None
    assert (saved / "page.html").exists()

    # Verify count is pruned to max 20
    remaining_dirs = [d for d in capture_base.iterdir() if d.is_dir()]
    assert len(remaining_dirs) <= 20


def test_is_possibly_blind_only_after_the_window():
    now = 10_000.0
    assert not hardening.is_possibly_blind(now - 60, now)
    assert not hardening.is_possibly_blind(now - 3599, now)
    assert hardening.is_possibly_blind(now - 3600, now)


def test_ping_healthcheck_skips_empty_url():
    assert hardening.ping_healthcheck("") is False
    assert hardening.ping_healthcheck("   ") is False
