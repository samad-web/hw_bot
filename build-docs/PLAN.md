# PLAN — Blinkit Hot Wheels Restock Bot

Source of truth: `../blinkit-hotwheels-bot.md` (Sections 1–16). This plan refines it; where they differ, this file wins and the reason is in `MEMORY.md`.

## 1. Goal and scope

**Goal.** Watch one out-of-stock Hot Wheels product on Blinkit at one fixed delivery location, 24/7. The moment it flips to "Add", alert instantly and place the order unattended, paying from a pre-loaded Blinkit Money wallet. Never order twice, never order the wrong thing.

**In scope**
- Single product, single account, single delivery address, quantity 1.
- Modes A (notify) / B (cart + confirm) / C (full auto-order), selected by config. Default A + `--dry-run`.
- Telegram alerts and remote commands.
- Docker deployment on an India-region VPS with auto-restart.

**Out of scope**
- Multiple products or accounts, price tracking/history, UPI PIN automation, SMS/OTP interception, captcha solving, stealth/evasion tooling, any form of parallel or multi-IP hammering.

## 2. Decisions taken (2026-11-07)

| # | Decision | Note |
|---|---|---|
| D1 | Host on India-region cloud VPS | User's choice over my recommendation of a home machine. Risk accepted, mitigated by D2. |
| D2 | Session bootstrap: log in **headful on the user's PC**, copy the Playwright profile dir to the VPS | The VPS never does an interactive login; OTP happens once, locally. |
| D3 | Build through Mode C | Payment = Blinkit Money wallet only for first real run. |
| D4 | State in an atomically-written JSON file, not SQLite | ~6 keys, single writer. `os.replace` gives the same crash safety in ~20 lines. Spec Section 11 permits with justification. |
| D5 | Telegram via plain `requests` + `getUpdates` long-poll, not `python-telegram-bot` | Avoids an async framework for ~6 commands and 7 message types. |
| D6 | Every Blinkit selector starts as a TODO, resolved from real captured HTML | I cannot log into Blinkit. `main.py --capture` saves page HTML/screenshot to `logs/capture/` so selectors come from fact, not guesswork. |
| D7 | Dependencies: `playwright`, `pyyaml`, `requests`. Nothing else. | |
| D8 | WhatsApp via Evolution API added as a second **outbound** alert channel; Telegram keeps all inbound commands | User request, 2026-11-07. Inbound WhatsApp would need a public webhook server on the VPS — disproportionate for 6 commands. Base URL, instance id and destination number unverified (probe blocked). |
| D9 | **Payment = Cash on Delivery via blinkit.com** (replaces D3 wallet) | 2026-11-11. Web has no Blinkit Money. Wallet would need app control over wireless ADB, which Android resets on every reboot (a human step). User chose COD. |
| D10 | **Host = VPS, Blinkit traffic relayed through the user's old Android 16 phone (Tailscale exit node)** | VPS IP gets 403. The user's own home IP, not a rented proxy pool. No laptop. |
| D11 | **Headful Chromium under Xvfb** on the VPS | `/checkout` Turnstile blocks headless; a plain headful browser passes. No challenge solving or spoofing. |
| D12 | Keep watching the other car while one order is out for delivery | Restocks are short. The lock already serialises payments. |
| D13 | F9 (Appium app-buyer) shelved | Superseded by F11. |

## 3. Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| Datacenter IP flagged / geo-fenced (D1) | Bot blind, or wrong dark-store stock | Explicit block + location-drift detection each loop; alert and back off, never hammer. Fall back to home host if it trips repeatedly. |
| Selectors wrong on day one (D6) | False OUT_OF_STOCK forever — the silent failure that loses the item | Positive-control check: identity assertion must pass, else ERROR not OUT_OF_STOCK. Heartbeat reports last successful identity match. |
| Blinkit UI change mid-watch | Same as above | Unknown-layout path saves HTML + screenshot and alerts. |
| Automating a consumer app conflicts with Blinkit ToS | Account action | One account, one session, ≥20 s floor between checks, no evasion tooling. User accepts. |
| Wallet balance short at checkout | Missed order | Pre-checkout balance read vs total payable; alert "pay manually NOW" rather than failing silently. |

## 4. Features, in build order

Each has a doc in `features/`. Sequenced by dependency.

| # | Feature | Doc | Spec phase |
|---|---|---|---|
| F1 | Config, state and single-order lock | `01-config-state.md` | — |
| F2 | Watcher (session, location, availability) | `02-watcher.md` | Phase 1 |
| F3 | Notifier (alerts, heartbeat, commands) | `03-notifier.md` | Phase 2 |
| F4 | Deployment (Docker, restart, bootstrap) | `04-deployment.md` | Phase 3 |
| F5 | Cart automation (Mode B) | `05-cart.md` | Phase 4 |
| F6 | Checkout and payment (Mode C) | `06-checkout.md` | Phase 5 |
| F7 | Hardening (backoff, capture, recovery) | `07-hardening.md` | Phase 6 |

| F8 | Multi-product | `08-multi-product.md` | — |
| F9 | Appium app-buyer (SHELVED, D13) | `09-appium-app-buyer.md` | — |
| F10 | Home relay + VPS headful deploy | `10-home-relay-vps.md` | — |
| F11 | Web checkout, Cash on Delivery | `11-web-cod-checkout.md` | Phase 5 |
| F12 | Delivery tracking | `12-delivery-tracking.md` | — |

**2026-11-11 build order:** F10 gate test (VPS reaches `/checkout` through the phone) → F11 (dry run, then one supervised cheap COD order) → F12 → new Evolution GO id wired in → cut over: stop the laptop watcher, VPS live in Mode C. If the F10 gate fails, stop and report; nothing else gets built on it.

F1 before everything (the lock must exist before any code can order). F3 before F5/F6 so failures are visible. F7 last, it tightens what exists.

## 5. Files

```
build-docs/            PLAN ARCHITECTURE MEMORY TESTING CHANGELOG features/
config.yaml            product, delivery, polling, mode, safety, selectors
.env.example           TELEGRAM_*, EVOLUTION_BASE_URL/INSTANCE/APIKEY/TO_NUMBER, HEALTHCHECK_URL
main.py                entry point, arg parsing, scheduler loop, signal handling
checker.py             availability detection + identity assertion
executor.py            cart, pre-checkout validation, payment
notifier.py            Telegram send + command poll, Evolution API WhatsApp send
state.py               atomic JSON state, single-order lock
logger.py              rotating file log (stdlib handler, ~15 lines)
Dockerfile docker-compose.yml requirements.txt README.md
tests/                 pytest, HTML fixtures from --capture
logs/                  bot.log, capture/
```

## 6. Definition of done

`docker compose up` runs the bot; it survives `kill -9` and reboot; heartbeat and alerts arrive; it reports OUT_OF_STOCK correctly for the target product; all tests pass; `--dry-run` never presses pay; Section 13 checklist and the requirement→code map are complete in `TESTING.md`.

## 7. Open — needs your input before F2 can be finished

1. Exact Hot Wheels product and its Blinkit URL (or search keyword).
2. Delivery address: saved label on the account, plus lat/lng and pincode.
3. `max_price_inr` and `max_order_value_inr`.
4. Telegram bot token + your chat id (into `.env`, never the repo).
5. Git: no repo exists here. Create one and push to GitHub? Which remote?
6. Evolution API: confirm the API base URL, the instance identifier the route accepts (name vs the UUID), and the destination WhatsApp number in E.164. Also whether you want me to probe the instance (needs permission to send the token to that host).
