# Blinkit Hot Wheels Bot — Functional Specification

## 1. Purpose

Watch a specific Hot Wheels product on Blinkit that is currently **out of stock / "Notify Me"**, run **continuously** until it comes back, then **order it to a fixed delivery location** (or alert the owner to confirm), and report the outcome.

**Primary goal:** never miss the restock window. Restocked collectibles on quick-commerce apps often sell out within minutes.

---

## 2. Key Requirements

| # | Requirement |
|---|---|
| R1 | Run 24/7 without stopping, restarting itself after any crash |
| R2 | Detect the moment the product switches from *Out of stock / Notify Me* to *Add* |
| R3 | Deliver to one configured address (the specific location) |
| R4 | Alert the owner instantly on every important event (restock, order placed, failure) |
| R5 | Never double-order |
| R6 | Safe-by-default: stop and alert if anything looks unexpected (price jump, wrong item, wrong address) |

---

## 3. Operating Modes

Choose one in config. Start with Mode A and graduate to B or C once the flow is proven.

| Mode | Behaviour | Risk |
|---|---|---|
| **A. Notify only** | Detect restock, send alert with link. Owner orders manually. | Lowest |
| **B. Cart + confirm** | Detect restock, add to cart at correct address, alert owner to tap "Pay". | Low |
| **C. Full auto-order** | Detect restock, add to cart, checkout, pay (COD or pre-saved method), alert. | Highest |

---

## 4. Inputs / Configuration

Keep all values in a `config.yaml` or `.env` file. Never hard-code secrets.

```yaml
product:
  name: "Hot Wheels <exact model name>"
  url: "<Blinkit product URL, if available>"
  search_keywords: ["hot wheels", "<model code>"]
  max_price_inr: 0          # abort if price exceeds this
  quantity: 1

delivery:
  label: "Home"             # saved address label on the account
  lat: 0.0
  lng: 0.0
  pincode: "000000"

mode: "A"                   # A | B | C

polling:
  interval_seconds: 45      # base interval
  jitter_seconds: 15        # random +/- to avoid a fixed pattern
  fast_interval_seconds: 20 # optional, used near an expected restock time

notifications:
  telegram_bot_token: "..."
  telegram_chat_id: "..."
  # optional: email / WhatsApp / push (ntfy, Pushover)

payment:
  # tried in order; see Section 16 for what each can and cannot automate
  priority: ["blinkit_wallet", "cod", "saved_card_otp_relay"]
  max_order_value_inr: 0    # hard ceiling on total payable, incl. fees
  otp_relay_timeout_seconds: 120

safety:
  max_orders_total: 1
  stop_after_success: true
```

---

## 5. High-Level Architecture

```
                 +--------------------+
                 |  Process Manager   |  (systemd / Docker restart / PM2)
                 +---------+----------+
                           |
                 +---------v----------+
                 |   Scheduler Loop   |  polls every N sec (+ jitter)
                 +---------+----------+
                           |
          +----------------v-----------------+
          |  Availability Checker            |
          |  (browser automation or API)     |
          +----------------+-----------------+
                           |
              in stock?    |
          no <-------------+-------------> yes
          |                                 |
     sleep + repeat                +--------v---------+
                                   |  Order Executor  |
                                   |  (per mode A/B/C)|
                                   +--------+---------+
                                            |
                          +-----------------v----------------+
                          |  Notifier + State Store + Logger |
                          +----------------------------------+
```

### Components

1. **Process Manager** — keeps the bot alive forever (auto-restart on crash/reboot).
2. **Scheduler Loop** — the heartbeat; runs checks at a randomised interval.
3. **Availability Checker** — determines stock status for the target product at the target location.
4. **Order Executor** — adds to cart, verifies, checks out (depending on mode).
5. **Notifier** — pushes alerts to your phone.
6. **State Store** — small SQLite/JSON file remembering `order_placed`, last status, timestamps (prevents duplicate orders after restart).
7. **Logger** — rotating log files for debugging.

---

## 6. Core Flow (Step by Step)

### 6.1 Startup
1. Load config and validate (all required fields present).
2. Load state from disk. If `order_placed = true` and `stop_after_success`, exit cleanly.
3. Launch the automation session (see Section 7).
4. Log in (or restore saved session/cookies).
5. **Set the delivery location** to the configured address. Verify the address shown in the app matches config. Abort and alert if it doesn't.
6. Send a "Bot started" notification.

### 6.2 Main Loop
```
while True:
    status = check_availability()

    if status == IN_STOCK:
        handle_restock()
    elif status == OUT_OF_STOCK:
        log("still out of stock")
    elif status == ERROR:
        handle_error()

    sleep(interval + random_jitter)
```

### 6.3 `check_availability()`
- Open the product page (or search by keyword) **with the delivery location set**, since stock is per dark store / pincode.
- Read the button/state:
  - **"Add" / quantity stepper visible** → `IN_STOCK`
  - **"Notify Me" / "Out of stock"** → `OUT_OF_STOCK`
  - Login wall, captcha, blank page, layout change → `ERROR`
- Confirm product identity (title/ID matches config) so a different Hot Wheels listing doesn't trigger an order.

### 6.4 `handle_restock()`
1. **Immediately notify**: "Hot Wheels is IN STOCK on Blinkit. Open now." (include link)
2. Branch by mode:
   - **Mode A:** stop here, keep watching or pause for 10 min to avoid alert spam.
   - **Mode B:** add to cart, open cart, verify details, notify "Cart ready, tap to pay".
   - **Mode C:** continue to checkout below.
3. **Pre-checkout validation** (all must pass):
   - Item name matches
   - Price is at or below `max_price_inr`
   - Quantity equals configured quantity
   - Address equals configured address
   - `order_placed` is false
4. Proceed to payment using the configured method, then confirm the order.
5. Capture the confirmation screen/order ID, save state `order_placed = true`, send success notification with order ID and ETA.
6. If `stop_after_success`, shut down gracefully.

### 6.5 Failure Handling

| Situation | Action |
|---|---|
| Item sold out between detection and checkout | Notify "Missed it", return to watch loop |
| Price above limit | Notify, do **not** order |
| Address mismatch | Stop, notify, require manual fix |
| Payment fails | Retry once, then notify and fall back to Mode B behaviour |
| Login expired | Re-login; if OTP needed, notify owner to supply it |
| Captcha / bot block | Back off (see 8.3), notify, do not hammer |
| Unknown page layout | Save screenshot + HTML, notify, retry later |

---

## 7. Implementation Options (How the Bot Talks to Blinkit)

Blinkit does **not** offer a public API for consumers, so the options are:

| Option | Pros | Cons |
|---|---|---|
| **Browser automation (Playwright)** — recommended | Works like a real user, easiest to maintain, handles location and login | Heavier, breaks if UI changes |
| **Android emulator + Appium** | Mirrors the mobile app exactly | Heavy, slower, complex setup |
| **Unofficial/internal API calls** | Fast, lightweight | Fragile, undocumented, higher chance of blocks, may breach terms |

**Recommendation:** Python + **Playwright** with a **persistent browser profile** (keeps you logged in and keeps the location set), mobile viewport emulation, headless on a server.

Note: automating a consumer app may conflict with Blinkit's terms of service, and accounts can be rate-limited or flagged. Keep the volume low, use your own single account, and treat this as a personal-use tool.

---

## 8. Running Continuously (Reliability)

### 8.1 Hosting
Run on something that is always on:
- A small cloud VM / VPS (cheapest and most reliable), or
- A Raspberry Pi / home server, or
- Docker on any always-on machine

Do **not** rely on a laptop that sleeps.

### 8.2 Keeping It Alive
- **Docker:** `restart: unless-stopped`
- **systemd:** `Restart=always`, `RestartSec=10`
- **PM2:** `pm2 start bot.py --interpreter python3` then `pm2 save && pm2 startup`
- **Watchdog / heartbeat:** the bot sends a "still alive" message every few hours; if you stop receiving it, something is wrong. An external uptime check (e.g., Healthchecks.io ping each loop) alerts you if the bot dies silently.

### 8.3 Being a Good Citizen (Avoiding Blocks)
- Poll every **30 to 60 seconds**, not every second.
- Add random jitter to the interval.
- Exponential backoff on errors: 1 min, 2 min, 5 min, 15 min (cap).
- Reuse one session instead of logging in each loop.
- Restart the browser context every few hours to avoid memory leaks.

### 8.4 Persistence
- Store state in SQLite or a JSON file on disk (not in memory).
- On restart, read state first so the bot never orders twice.

---

## 9. Notifications

Recommended channel: **Telegram bot** (free, instant, reliable). Alternatives: ntfy.sh, Pushover, WhatsApp, email.

| Event | Message |
|---|---|
| Bot started | "Blinkit bot running. Watching: <product>" |
| Heartbeat (every ~6 hrs) | "Still watching. Last check OK." |
| **Restock detected** | "IN STOCK. Open Blinkit now: <link>" |
| Cart ready (Mode B) | "Added to cart. Complete payment." |
| Order placed (Mode C) | "Order placed. ID: <id>, ETA: <time>" |
| Missed / sold out | "Item went out of stock before checkout." |
| Error / blocked | "Bot needs attention: <reason>" |

Make the restock alert **loud** (priority/high urgency push) since speed matters.

---

## 10. Safety Rules

1. **Single-order lock:** once `order_placed = true`, the bot will not order again.
2. **Price ceiling:** never order above `max_price_inr`.
3. **Identity check:** product title/ID must match the config.
4. **Address check:** verify before every checkout.
5. **Quantity cap:** exactly the configured quantity.
6. **Kill switch:** a Telegram command (`/stop`, `/pause`, `/resume`, `/status`) to control the bot remotely.
7. **Secrets:** keep tokens and credentials in `.env`, never in the repo or logs.
8. **Start in Mode A or B** for the first run before trusting Mode C.

---

## 11. Suggested Project Structure

```
blinkit-hotwheels-bot/
├── config.yaml
├── .env
├── main.py              # entry point + scheduler loop
├── checker.py           # availability detection
├── executor.py          # cart / checkout logic
├── notifier.py          # Telegram (or other) alerts
├── state.py             # persistent state (SQLite/JSON)
├── logger.py            # rotating logs
├── Dockerfile
├── docker-compose.yml   # restart: unless-stopped
├── requirements.txt
└── logs/
    └── bot.log
```

**Suggested stack:** Python 3.11+, Playwright, `python-telegram-bot` (or plain `requests`), SQLite, Docker.

---

## 12. Build Plan

1. **Phase 1: Watcher.** Playwright opens the product page at the right location, reads stock status, logs it.
2. **Phase 2: Notifier.** Wire in Telegram alerts and heartbeat.
3. **Phase 3: 24/7 hosting.** Dockerise, set auto-restart, add uptime monitoring.
4. **Phase 4: Cart automation (Mode B).** Add to cart at the correct address, verify, alert.
5. **Phase 5: Full checkout (Mode C).** Add safety checks, single-order lock, payment handling.
6. **Phase 6: Hardening.** Error handling, backoff, screenshots on failure, remote commands.

---

## 13. Testing Checklist

- [ ] Detects "Out of stock" correctly for the target location
- [ ] Detects an in-stock product (test with any available item)
- [ ] Address verification works and blocks mismatches
- [ ] Telegram alerts arrive within seconds
- [ ] Bot recovers after `kill -9` and after a server reboot
- [ ] No duplicate order after a restart mid-checkout
- [ ] Price above limit is rejected
- [ ] Captcha / login-wall path alerts instead of looping
- [ ] Heartbeat stops if the bot dies (external monitor fires)

---

## 14. Open Questions to Decide Before Building

1. Exact Hot Wheels model/SKU and its Blinkit link?
2. Delivery location: saved address label or coordinates?
3. Payment: COD, saved UPI, or manual confirm (Mode B)?
4. Hosting: cloud VM, Raspberry Pi, or existing server?
5. Preferred alert channel: Telegram, WhatsApp, or push?
6. Stop after the first successful order, or keep watching?

---

## 15. Build Prompt for the Coding Agent

Copy everything inside the block below and give it to your coding agent (Claude Code, Cursor, etc.) together with this file. Fill in the `<...>` placeholders first. The agent should treat Sections 1 to 14 of this document as the source of truth.

````text
ROLE
You are a senior Python automation engineer. Build the project described in
the attached spec file (blinkit-hotwheels-bot.md) completely. Read the whole
spec before writing any code. Do not skip, merge, or simplify any requirement.

GOAL
A bot that runs 24/7 and watches ONE Hot Wheels product on Blinkit that is
currently out of stock ("Notify Me"). The moment it becomes available at my
delivery location, the bot alerts me instantly and, depending on the
configured mode, adds it to cart or orders it, then reports the result.

MY INPUTS (fill these in before running the agent)
- Product name / model: <exact Hot Wheels model>
- Product URL (if known): <url or "search by keyword">
- Max price (INR): <number>
- Quantity: 1
- Delivery address label on account: <e.g. Home>
- Delivery lat/lng and pincode: <lat, lng, pincode>
- Mode: <A notify only | B cart + confirm | C full auto-order>
- Payment priority (Mode C): <e.g. blinkit_wallet, cod, saved_card_otp_relay>  (see Section 16)
- Notification channel: Telegram (bot token and chat id go in .env)
- Hosting target: <VPS | Raspberry Pi | Docker on home server>

TECH STACK (use exactly this unless impossible, and tell me why)
- Python 3.11+
- Playwright (Chromium) with a persistent browser profile, mobile viewport
- SQLite for state (or JSON if you justify it)
- Telegram Bot API for notifications and remote commands
- Docker + docker-compose with restart: unless-stopped
- Config in config.yaml, secrets in .env (never hard-coded, never logged)

PROJECT STRUCTURE
Create exactly the structure in Section 11 of the spec: main.py, checker.py,
executor.py, notifier.py, state.py, logger.py, config.yaml, .env.example,
Dockerfile, docker-compose.yml, requirements.txt, README.md, logs/.

FUNCTIONAL REQUIREMENTS (implement ALL of these)
1. Startup: validate config, load state, launch browser with persistent
   profile, log in or restore session, set delivery location, VERIFY the
   address shown matches config, send "Bot started" alert.
2. Main loop: check availability every interval_seconds +/- random jitter.
   Never use a fixed interval. Run forever.
3. check_availability(): returns IN_STOCK, OUT_OF_STOCK, or ERROR. Verify
   product identity (title/ID) before trusting the result. Stock is
   per-location, so the location must be set before every check.
4. On IN_STOCK: send a high-priority alert immediately (before any further
   automation), then branch by mode:
   - Mode A: alert only, then pause alerts for 10 minutes to avoid spam.
   - Mode B: add to cart, verify cart contents, alert "Cart ready, pay now".
   - Mode C: add to cart, run ALL pre-checkout validations, pay, capture the
     order ID and ETA, save state, alert.
5. Pre-checkout validations (all must pass or abort and alert): item name
   matches, price <= max_price_inr, quantity matches, address matches,
   order_placed is false.
6. Single-order lock: persist order_placed in state BEFORE and AFTER payment
   so a crash mid-checkout can never cause a duplicate order. If state is
   uncertain after a crash, do not order; alert me instead.
7. Error handling per the table in Section 6.5 of the spec: sold out during
   checkout, price above limit, address mismatch, payment failure (retry
   once), expired login (re-login, ask me for OTP via Telegram if needed),
   captcha or block (back off, alert, do not hammer), unknown layout (save
   screenshot + HTML to logs/, alert, retry later).
8. Backoff: exponential on errors (1, 2, 5, 15 min cap), reset after success.
9. Reliability: restart browser context every few hours, auto-restart via
   Docker, heartbeat Telegram message every ~6 hours, optional
   Healthchecks.io ping each loop (URL in .env, skip if empty).
10. Telegram commands: /status, /pause, /resume, /stop, /mode <A|B|C>.
    Only respond to my configured chat id.
11. Logging: rotating file logs, no secrets, log every check result with
    timestamp, and screenshots on any failure.
12. Graceful shutdown on SIGTERM/SIGINT; stop_after_success honored.
13. Payment automation exactly as specified in Section 16 of the spec:
    payment-method priority chain, wallet balance check, COD handling,
    Telegram OTP relay for card payments (human supplies OTP, bot never
    reads SMS or bypasses authentication), UPI handled as approve-on-phone
    only, no card numbers/CVV/PIN stored anywhere, and a mandatory
    order-history check before ANY payment retry to prevent double charges.

NON-FUNCTIONAL REQUIREMENTS
- Be a polite client: one session, one account, no parallel hammering, no
  polling faster than 20 seconds under any config.
- Keep selectors and URLs in one place (a selectors section in config or a
  dedicated module) so UI changes are a one-line fix.
- Type hints, docstrings on every public function, small testable functions.
- No silent failures: every except block logs and, where relevant, alerts.
- Do not bypass captchas or use stealth or evasion tooling. If blocked, back
  off and notify me.

DELIVERABLES
1. All source files listed above, complete and runnable.
2. README.md with: one-time login procedure (including how to complete OTP
   once and persist the session), setup, run, Docker deploy, how to switch
   modes, how to read logs, troubleshooting.
3. tests/ with unit tests for: state lock (no duplicate order), price
   ceiling, address mismatch, identity check, backoff logic, and the
   availability parser using saved HTML fixtures.
4. A dry-run flag (--dry-run) that runs the full loop and flow but never
   clicks the final pay/confirm button, sending alerts instead.
5. A short CHANGELOG or build notes listing any assumption you made.

BUILD ORDER (follow the phases in Section 12 of the spec)
Phase 1 watcher, Phase 2 notifier, Phase 3 Docker + 24/7, Phase 4 cart
(Mode B), Phase 5 checkout (Mode C), Phase 6 hardening. After each phase,
run the tests, summarize what works, and then continue.

RULES FOR YOU, THE AGENT
- Do not skip any numbered requirement above. At the end, print a checklist
  mapping each requirement (1 to 12) and each testing item in Section 13 of
  the spec to the file and function that implements it.
- If something is ambiguous or you cannot verify a Blinkit UI detail
  (selectors, flow), do not guess silently: isolate it behind a clearly
  named function, mark it with a TODO, and list it in your final report.
- Default config to Mode A and --dry-run behavior so nothing is ever bought
  by accident on first run.
- Never place a real order during development or testing.

DEFINITION OF DONE
- docker compose up starts the bot, it survives kill -9 and a reboot, sends
  heartbeat and alerts, correctly reports OUT_OF_STOCK for the target
  product, passes all tests, and the requirement-to-code checklist is
  complete with no unchecked items.
````

### Final Self-Check (agent must confirm before finishing)

- [ ] Every requirement in the prompt above is implemented and mapped to code
- [ ] Single-order lock survives crashes and restarts
- [ ] Mode defaults to A, `--dry-run` never presses the final pay button
- [ ] All testing checklist items in Section 13 pass or are explained
- [ ] No secrets in code, logs, or the repo
- [ ] README lets me deploy it from scratch

---

## 16. Payment Automation

**Goal:** the bot pays on its own so you never need to touch the phone when the item restocks.

### 16.1 What can and cannot be fully automated

| Method | Fully hands-off? | Notes |
|---|---|---|
| **Cash on Delivery (COD)** | **Yes** | No authentication step at checkout. You pay the rider at the door (cash or UPI QR). COD availability depends on the cart, account, and area, so verify it appears at checkout. |
| **Blinkit wallet / balance (if available on your account)** | **Yes** | Pre-load a small balance (just above the item price + fees). Checkout debits it with no OTP. Most reliable "automated payment". |
| **Saved card** | **Mostly no** | Indian card payments normally need CVV and an OTP (3-D Secure) each time. Semi-automated: bot reaches the payment step, messages you, you reply with the OTP, bot enters it. |
| **UPI** | **No** | Every UPI payment needs your PIN approved inside your UPI app. This must stay a human step. The bot can trigger the request and ping you, but should never handle your PIN. |

**Recommended:** use **Blinkit wallet balance or COD** as the primary method. They are the only two that are genuinely unattended. Keep card + OTP relay as a fallback.

### 16.2 Payment priority chain

```
1. Blinkit wallet  -> if balance >= total payable, use it
2. COD             -> if offered at checkout for this cart
3. Saved card      -> pay via OTP relay (you reply with the OTP in Telegram)
4. Nothing works   -> stop, alert "Cart ready, pay manually NOW"
```

The bot tries each in order based on `payment.priority` and what the checkout screen actually offers.

### 16.3 Flow at checkout

1. Read the **total payable** (item + handling/delivery fees). If it exceeds `max_order_value_inr` or `max_price_inr` rules, abort and alert.
2. Select the first available method in the priority chain.
3. **Wallet / COD:** confirm and place the order.
4. **Saved card + OTP relay:**
   - Proceed to the OTP screen.
   - Send Telegram: "OTP needed for Hot Wheels order. Reply `/otp 123456` within 2 minutes."
   - Enter the OTP the moment you reply, then confirm.
   - If no reply within `otp_relay_timeout_seconds`, cancel safely and alert.
5. Wait for the **order confirmation screen**, capture the order ID, save state, notify.

### 16.4 Preventing double charges

- Save `payment_attempt_started` in state **before** pressing pay.
- If anything fails or times out after that point, **do not blindly retry**. First open **Order history** and check whether an order already exists for this item.
  - Order exists: mark `order_placed = true`, notify, stop.
  - No order and no charge: safe to retry once.
  - Unclear: stop and alert you to check manually.
- If you are charged but see no order, alert you and show the last screenshot.

### 16.5 Security rules for payment

- **Never** store card numbers, CVV, UPI PIN, or banking passwords in the bot, config, logs, or repo. Use only what is already saved in the Blinkit account.
- **Do not** read your SMS or intercept OTPs automatically. Authentication stays with you via the Telegram relay.
- Use a **dedicated account** with a **low-limit card** or a small wallet balance, so the worst case is bounded.
- Enforce `max_orders_total = 1` and `max_order_value_inr` as hard limits.
- Mask any payment-related text and order details in logs and screenshots.

### 16.6 Testing the payment path safely

- Develop everything with `--dry-run` (bot stops before the final pay/confirm click).
- Test the OTP relay with a fake prompt first, without a real payment.
- Do the first real run on a low-value, in-stock item on purpose, with Mode C and a tiny wallet balance, so you can watch it work end to end.
