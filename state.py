"""Persistent bot state. The single-order locks live here.

One process, one writer, so no locking is needed — but every write must be
atomic, because a crash mid-write that left a corrupt file would either stop
the bot from starting or (far worse) look like a cleared lock.

Each watch target gets its own entry under ``orders``, keyed by Blinkit prid.
``payment_attempt_started`` is global and holds the prid currently being paid
for: only one checkout may ever be in flight.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_PATH = "state.json"

DEFAULTS: dict[str, Any] = {
    "orders": {},                     # prid -> {"order_id": str, "spent": float, "ts": int}
    "payment_attempt_started": None,  # prid mid-payment, else None
    "total_spent": 0.0,
    "last_status": None,
    "last_check_ts": 0,
    "last_alert_ts": {},              # prid -> unix ts (Mode A mute window)
    "last_identity_ok_ts": 0,
    "telegram_offset": 0,
    "paused": False,
    "mode": None,
    "consecutive_errors": 0,
}


def load(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read state from disk, filling in defaults for anything absent.

    A missing file is a normal first run. A corrupt file is NOT reset to
    defaults: that would silently clear the locks. It is quarantined instead
    and the returned state carries ``corrupt=True``, which blocks ordering
    until a human looks.
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

    data = _migrate(data)
    # Additive: unknown keys are preserved, absent keys take their default.
    return {**DEFAULTS, **data}


def save(state: dict[str, Any], path: str | os.PathLike[str] | None = None,
         **changes: Any) -> dict[str, Any]:
    """Apply ``changes`` and write atomically. Returns the new state.

    Durability matters more than speed here: ``fsync`` before ``os.replace``
    is what makes "lock written before the pay click" a real guarantee rather
    than a hope about OS buffering.
    """
    new = {**state, **changes}
    p = Path(path if path is not None else DEFAULT_PATH)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
    return new


def is_bought(state: dict[str, Any], prid: str) -> bool:
    """True when this specific target has already been ordered."""
    return str(prid) in (state.get("orders") or {})


def all_bought(state: dict[str, Any], total_targets: int) -> bool:
    """True when every watch target has been ordered."""
    return len(state.get("orders") or {}) >= total_targets


def needs_manual_check(state: dict[str, Any]) -> bool:
    """True when a payment was started but never confirmed.

    This is the uncertain state after a crash mid-checkout. Money may or may
    not have moved, so the bot must never decide on its own — and it blocks
    ordering of EVERY target, not just the one that was in flight.
    """
    return state.get("payment_attempt_started") is not None


def record_order(state: dict[str, Any], prid: str, order_id: str | None,
                 amount: float, path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Mark a target bought and clear the in-flight flag, in one atomic write."""
    orders = dict(state.get("orders") or {})
    orders[str(prid)] = {"order_id": order_id, "spent": float(amount), "ts": int(time.time())}
    return save(
        state, path,
        orders=orders,
        total_spent=round(float(state.get("total_spent", 0.0)) + float(amount), 2),
        payment_attempt_started=None,
    )


def can_order(state: dict[str, Any], prid: str, max_orders_total: int = 1,
              max_total_spend_inr: float = 0.0,
              order_total: float = 0.0) -> tuple[bool, str]:
    """Whether this target may be ordered right now, and why not if it isn't."""
    if state.get("corrupt"):
        return False, "state file was corrupt and quarantined; refusing to order"
    if needs_manual_check(state):
        return False, (
            f"a payment for product {state.get('payment_attempt_started')} was never confirmed; "
            "check Blinkit order history before allowing any further order"
        )
    if is_bought(state, prid):
        return False, f"product {prid} was already ordered (single-order lock)"
    if max_orders_total < 1:
        return False, "max_orders_total is below 1"
    if all_bought(state, max_orders_total):
        return False, f"all {max_orders_total} targets have already been ordered"
    if max_total_spend_inr > 0 and order_total > 0:
        projected = float(state.get("total_spent", 0.0)) + order_total
        if projected > max_total_spend_inr:
            return False, (
                f"this order (Rs {order_total:.0f}) would take total spend to "
                f"Rs {projected:.0f}, above the Rs {max_total_spend_inr:.0f} ceiling"
            )
    return True, ""


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a pre-multi-product state file in memory.

    The old format had a single ``order_placed`` boolean with no product id. If
    it was True we cannot know which target it referred to, so the file is
    flagged for human review rather than guessed at.
    """
    if "orders" in data:
        return data
    data = dict(data)
    legacy_placed = data.pop("order_placed", False)
    legacy_id = data.pop("order_id", None)
    data["orders"] = {}
    if legacy_placed:
        data["corrupt"] = True
        data["corrupt_reason"] = (
            f"legacy state recorded an order ({legacy_id}) with no product id; "
            "cannot tell which target was bought"
        )
    if not isinstance(data.get("payment_attempt_started"), (str, type(None))):
        # Legacy boolean flag: True meant "something was in flight".
        data["payment_attempt_started"] = "unknown" if data["payment_attempt_started"] else None
    if not isinstance(data.get("last_alert_ts"), dict):
        data["last_alert_ts"] = {}
    return data


def _quarantine(p: Path) -> str | None:
    """Move a corrupt state file aside, preserving it for inspection."""
    target = p.with_name(f"{p.stem}.corrupt.{time.time_ns()}")
    try:
        p.rename(target)
    except OSError:
        return None  # keep going: the corrupt flag alone already blocks ordering
    return str(target)
