"""Hardening utilities: backoff, jitter, failure capture, and blindness detection.
"""

from __future__ import annotations

import logging
import random
import shutil
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("hw_bot")

BACKOFF_SCHEDULE = [60, 120, 300, 900]  # 1 min, 2 min, 5 min, 15 min
MAX_CAPTURE_DIRS = 20
MIN_INTERVAL_FLOOR = 20
BLIND_AFTER_SECONDS = 3600


def is_possibly_blind(last_identity_ok_ts: float, now: float,
                      window: float = BLIND_AFTER_SECONDS) -> bool:
    """True when the product-identity assertion has not passed for too long.

    Guards the quietest failure mode: a selector drifts, every check still
    returns a tidy OUT_OF_STOCK, and the restock is missed in silence.
    """
    return (now - last_identity_ok_ts) >= window


def ping_healthcheck(url: str) -> bool:
    """Ping an external dead-man switch. Never raises: a dead monitor must not kill the bot."""
    if not url.strip():
        return False
    try:
        requests.get(url, timeout=5)
        return True
    except Exception as exc:  # noqa: BLE001 - monitoring must never be fatal
        logger.debug("Healthcheck ping failed: %s", exc)
        return False


def next_delay(consecutive_errors: int) -> int:
    """Calculate exponential backoff delay based on consecutive error count."""
    if consecutive_errors <= 0:
        return 0
    idx = min(consecutive_errors - 1, len(BACKOFF_SCHEDULE) - 1)
    return BACKOFF_SCHEDULE[idx]


def calculate_interval(base_interval: int, jitter: int, min_floor: int = MIN_INTERVAL_FLOOR) -> float:
    """Calculate sleep interval with uniform random jitter, respecting the minimum floor."""
    low = max(0, base_interval - jitter)
    high = base_interval + jitter
    val = random.uniform(low, high)
    return max(float(min_floor), val)


def save_failure_capture(
    page: Any,
    error_kind: str,
    base_dir: Path | str = "logs/capture",
) -> Path | None:
    """Dump HTML and full-page screenshot on unexpected errors, capping history at 20."""
    try:
        p_base = Path(base_dir)
        p_base.mkdir(parents=True, exist_ok=True)

        ts = int(time.time())
        target_dir = p_base / f"{ts}_{error_kind}"
        target_dir.mkdir(parents=True, exist_ok=True)

        # Dump HTML
        html = page.content() if hasattr(page, "content") else ""
        (target_dir / "page.html").write_text(html, encoding="utf-8")

        # Capture screenshot if supported
        if hasattr(page, "screenshot"):
            try:
                page.screenshot(path=str(target_dir / "screenshot.png"), full_page=True)
            except Exception as e:
                logger.warning("Could not capture screenshot: %s", e)

        # Prune older capture directories to prevent filling disk
        all_dirs = sorted(
            [d for d in p_base.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if len(all_dirs) > MAX_CAPTURE_DIRS:
            for old_dir in all_dirs[MAX_CAPTURE_DIRS:]:
                try:
                    shutil.rmtree(old_dir)
                except OSError:
                    pass

        return target_dir

    except Exception as exc:
        logger.warning("Failed to save failure capture: %s", exc)
        return None
