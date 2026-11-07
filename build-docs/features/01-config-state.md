# F1 — Config, state and single-order lock

## Purpose
Give every other module a validated config object, and the one piece of state that prevents the only unrecoverable failure in this project: ordering twice, or ordering after a crash left the outcome unknown.

## Architecture
- Config loader (in `main.py` while it stays under ~40 lines): reads `config.yaml`, overlays `.env` secrets, validates into a frozen dataclass. Validation is fail-fast at startup — a missing address or a zero price ceiling exits with a clear message, it does not silently default.
- `state.py`: `load() -> dict`, `save(**changes)`. Write path = `json.dump` to `state.json.tmp` → `flush` → `os.fsync` → `os.replace`. Single writer, so no locking.
- Lock helpers: `can_order(state) -> (bool, reason)` and the uncertain-state detector `needs_manual_check(state)` = `payment_attempt_started and not order_placed`.

## Data model
See ARCHITECTURE.md. Keys are additive-only: an unknown key in an existing file is preserved, a missing key takes its default.

## Impact map
| Touches | What breaks if F1 is wrong |
|---|---|
| every module | all of them read Config |
| `main.py` startup | a bad validator either blocks a correct start or admits a half-configured run |
| `executor.py` pay path | **a broken lock means a double charge** — highest-severity failure in the project |
| `state.json` on disk | a non-atomic write plus a crash = corrupt JSON = bot refuses to start |
| Docker volume | state must live on a mounted volume, or a container rebuild silently resets the lock |

## Edge cases and failure modes
- `state.json` missing → first run, use defaults, do not crash.
- `state.json` truncated or corrupt → **do not** reset to defaults; that would clear the lock. Rename to `state.corrupt.<ts>`, refuse to order, alert.
- Clock jumps backwards → timestamps are advisory only; the lock is never gated on time.
- `mode: C` with `max_order_value_inr: 0` → reject at startup. Zero means unset, not unlimited.
- `polling.interval_seconds < 20` → clamp to 20 and log it (hard floor).
- Secrets found in `config.yaml` instead of `.env` → warn loudly, never log the value.

## Acceptance criteria
1. Missing required config field → exit non-zero naming the field, before any browser launches.
2. `interval_seconds: 5` → bot runs at 20 s and logs the clamp.
3. `save()` killed between tmp write and replace → previous `state.json` is intact and parseable.
4. `order_placed: true` + `stop_after_success: true` → clean exit at startup, no browser launched.
5. `payment_attempt_started: true, order_placed: false` → `can_order()` is False and startup alerts "manual check needed".
6. Corrupt `state.json` → bot refuses to order, alerts, and the corrupt file is preserved on disk.
