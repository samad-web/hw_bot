# Blinkit Hot Wheels Restock Bot

An automated restock monitor and single-item purchaser for Hot Wheels on Blinkit. Runs 24/7, alerts instantly on restock, and can automatically cart and purchase from pre-loaded Blinkit Money wallet without double-ordering.

---

## Features

- **24/7 Autonomous Watcher**: Monitored via Playwright persistent sessions with location & product identity assertions.
- **Fail-Safe Single-Order Lock**: Atomic write + `fsync` before any payment click guarantees the bot never orders twice or re-orders after a crash.
- **Three Operating Modes**:
  - `Mode A`: Outbound restock alerts only (Telegram + WhatsApp).
  - `Mode B`: Restock alert + automatically adds item to cart at your delivery address.
  - `Mode C`: Full unattended auto-checkout paying from pre-loaded Blinkit Money wallet with strict price ceiling checks.
- **Remote Commands**: Control the bot on the fly via Telegram (`/status`, `/pause`, `/resume`, `/mode`, `/otp`, `/stop`).
- **Dual Outbound Alerts**: Telegram Bot API and Evolution API (WhatsApp).

---

## Project Structure

```text
├── config.yaml          # Non-secret settings (product name, ceilings, intervals, CSS selectors)
├── .env                 # Secrets (Telegram bot token, Evolution API credentials)
├── state.json           # Atomic persistent state & single-order lock
├── main.py              # CLI entry point and main scheduler loop
├── checker.py           # Stock check, identity assertion, and location verification
├── executor.py          # Cart additions, pre-checkout validation, and lock execution
├── notifier.py          # Telegram commands & WhatsApp alerts
├── hardening.py         # Jitter, backoff schedule, failure dumps, blindness guards
├── logger.py            # Rotating file logging (5 MB x 3)
├── Dockerfile           # Python 3.13 + Playwright Chromium container
├── docker-compose.yml   # Volume mounts for profile, state, and logs
└── tests/               # Comprehensive pytest test suite
```

---

## Quick Start

### 1. Prerequisites

- Python 3.13+
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```

### 2. Configure Credentials & Targets

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Fill in your Telegram and Evolution API details.

2. Edit `config.yaml` to specify:
   - Target product name and URL
   - Delivery address label and pincode
   - Price ceilings (`max_price_inr`, `max_order_value_inr`)

### 3. Session Bootstrap (Login locally)

Run the headful login helper once on your machine:
```bash
python main.py --login
```
Log into Blinkit via OTP and verify your delivery address is selected. The persistent profile is saved to `./profile/`.

### 4. Capture CSS Selectors

Capture real page HTML and screenshot to inspect selectors:
```bash
python main.py --capture
```
Update the `selectors:` block in `config.yaml` with the accurate classes/IDs.

### 5. Run the Bot

**Dry Run Test:**
```bash
python main.py --dry-run
```

**Run in Mode A (Notify only):**
```bash
python main.py --mode A
```

**Run via Docker:**
```bash
docker compose up -d
docker compose logs -f
```

---

## Telegram Remote Commands

| Command | Action |
|---|---|
| `/status` | View bot status, current mode, lock state, error counts, channel health |
| `/pause` | Suspend polling checks |
| `/resume` | Resume polling checks |
| `/mode <A\|B\|C>` | Change operating mode dynamically |
| `/otp <code>` | Relay SMS/bank OTP for card checkout if required |
| `/stop` | Gracefully shut down the bot |
