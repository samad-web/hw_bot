# CHANGELOG

## [Unreleased] - 2026-11-07

### Added
- **Core State & Lock (`state.py`)**: Atomic file writes with `os.fsync`, single-order lock, quarantine of corrupt state files, uncertain-state detector (`needs_manual_check`).
- **Configuration & Validation (`config.py`)**: Strong YAML + `.env` validation, fail-fast price ceilings in Mode C, 20s polling interval clamp.
- **Watcher (`checker.py`)**: Stock verification, delivery location assertion, product identity assertion, login wall & block detection.
- **Notifier (`notifier.py`)**: Telegram outbound alerts & remote commands (`/status`, `/pause`, `/resume`, `/mode`, `/otp`, `/stop`). WhatsApp outbound alerts via Evolution GO (`/send/text`) and Evolution Node API.
- **Cart & Checkout Automation (`executor.py`)**: Mode B add-to-cart, strict pre-checkout checks (item name, quantity, unit price, total payable, delivery address), atomic lock write *before* pay click, wallet balance check, dry-run safety.
- **Hardening (`hardening.py`, `logger.py`)**: Escalating backoff (60, 120, 300, 900s), jitter floor (>=20s), failure dumps (`logs/capture/` max 20 dirs), rotating file logs (5 MB x 3).
- **CLI & Scheduler (`main.py`)**: Command line flags (`--config`, `--env`, `--state`, `--mode`, `--dry-run`, `--login`, `--capture`), scheduler loop, graceful shutdown on SIGINT/SIGTERM.
- **Deployment (`Dockerfile`, `docker-compose.yml`, `README.md`)**: Container setup with volume mounts for persistent profile, state, and logs.
- **Test Suite (`tests/`)**: 36 comprehensive pytest unit tests covering all features and edge cases.

## 2026-11-07 — fix(build-review)
- Loop now re-fetches the product page every iteration (was reading a stale DOM; the bot could never detect a restock).
- `--state` is threaded through every write; Docker mounts `./data` as a directory because `os.replace` cannot replace a bind-mounted file.
- Pay-button selector validated before the single-order lock is written.
- Config refuses placeholder product name, placeholder pincode and unfilled selectors in modes B/C, and refuses Mode C without checkout selectors. These placeholders previously disabled the identity gate at runtime.
- State re-read from disk after checkout so a failed payment cannot be blindly retried.
- At least one notification channel is now mandatory.
- `/otp` no longer writes the code to disk; the card relay is declared unimplemented.
- Added browser-context recycling, blindness detection, healthcheck ping, persistent Mode A mute, Telegram Markdown with plain-text fallback.
- Tests 36 → 47.

### Known gaps
- Order-history check before a payment retry (F6 AC6/7) — not implemented; the lock fails safe by refusing all retries and alerting.
- Card OTP relay (spec req 13) — not implemented; wallet is the configured method.
- All selectors still empty: they require a real logged-in capture.
