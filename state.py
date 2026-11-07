"""Persistent bot state. The single-order lock lives here.

One process, one writer, so no locking is needed — but every write must be
atomic, because a crash mid-write that left a corrupt file would either stop
the bot from starting or (far worse) look like a cleared lock.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_PATH = "state.json"

DEFAULTS: dict[str, Any] = {
    "order_placed": False,
    "payment_attempt_started": False,
    "order_id": None,
    "last_status": None,
    "last_check_ts": 0,
    "last_alert_ts": 0,
    "last_identity_ok_ts": 0,
    "telegram_offset": 0,
    "paused": False,
    "mode": None,
    "consecutive_errors": 0,
}


def load(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read state from disk, filling in defaults for anything absent.

    A missing file is a normal first run. A corrupt file is NOT reset to
    defaults: that would silently clear the single-order lock. It is
    quarantined instead and the returned state carries ``corrupt=True``,
    which blocks ordering until a human looks.
    """
    p = Path(path if path is not None else DEFAULT_PATH)
    if not p.exists():
        return dict(DEFAULTS)

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state file does not contain a JSON object")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError, OSError) as exc:
        return dict(DEFAULTS, corrupt=True, corrupt_reason=str(exc),
                    corrupt_path=_quarantine(p))

    # Additive: unknown keys are preserved, absent keys take their default.
    return {**DEFAULTS, **data}


def save(state: dict[str, Any], path: str | os.PathLike[str] = DEFAULT_PATH,
         **changes: Any) -> dict[str, Any]:
    """Apply ``changes`` and write atomically. Returns the new state.

    Durability matters more than speed here: ``fsync`` before ``os.replace``
    is what makes "lock written before the pay click" a real guarantee rather
    than a hope about OS buffering.
    """
    new = {**state, **changes}
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
    return new


def needs_manual_check(state: dict[str, Any]) -> bool:
    """True when a payment was started but never confirmed.

    This is the uncertain state after a crash mid-checkout. Money may or may
    not have moved, so the bot must never decide on its own.
    """
    return bool(state.get("payment_attempt_started")) and not bool(state.get("order_placed"))


def can_order(state: dict[str, Any], max_orders_total: int = 1) -> tuple[bool, str]:
    """Whether ordering is permitted right now, and why not if it isn't."""
    if state.get("corrupt"):
        return False, "state file was corrupt and quarantined; refusing to order"
    if needs_manual_check(state):
        return False, ("a previous payment attempt was never confirmed; check Blinkit "
                       "order history before allowing another order")
    if state.get("order_placed"):
        return False, "an order was already placed (single-order lock)"
    if max_orders_total < 1:
        return False, "max_orders_total is below 1"
    return True, ""


def _quarantine(p: Path) -> str | None:
    """Move a corrupt state file aside, preserving it for inspection."""
    target = p.with_name(f"{p.stem}.corrupt.{time.time_ns()}")
    try:
        p.rename(target)
    except OSError:
        return None  # keep going: the corrupt flag alone already blocks ordering
    return str(target)
