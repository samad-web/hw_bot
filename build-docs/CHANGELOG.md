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

## 2026-11-07 — feat(watcher): real selectors + hydration wait
- Filled `selectors.product_title`, `header_address`, `out_of_stock` from live Blinkit HTML; each verified unique in the DOM.
- Blinkit's out-of-stock marker is `div.tw-text-yellow-700` containing "Coming soon", inside a unique sticky bottom bar.
- Added an 8 s wait for the location bar to hydrate: Blinkit SSRs it as an empty shimmer, which the checker previously read as `""` and reported as false `location_drift` on every cycle.
- Remaining selectors cannot be derived anonymously: with no delivery address Blinkit reports every product "Coming soon", so in-stock markup never renders. They need `--capture` from a logged-in session.
- Tests 47 → 49.

## 2026-11-07 — feat(multi-product): watch several cars, buy each in turn
- `product:` → `products:` list, keyed by Blinkit prid. Configured with the two confirmed targets: K5 Blazer (prid 799027, cap Rs 659) and 23 Ram 1500 (prid 1416802, cap Rs 215).
- State holds a per-product `orders` map; `payment_attempt_started` now stores the prid in flight, so a crash names the car whose outcome is unknown.
- New `safety.max_total_spend_inr` (set to 800, the wallet balance) checked before any lock write.
- Loop iterates outstanding targets, breaks after a purchase so two checkouts can never overlap, and exits when all are bought.
- Polling floor scales: 20 s per request × number of targets.
- `max_orders_total` must equal the product count; duplicate prids rejected.
- `--capture` now captures every target page.
- Tests 49 → 59, plus a shared `tests/conftest.py`.

### Still outstanding
- `add_button` and all cart/checkout selectors: need a capture from a logged-in session with a delivery address.
- Delivery label and pincode are still placeholders, so modes B and C refuse to start.
- Order-history check before retry, and the card OTP relay, remain unimplemented.

## 2026-11-07 — feat(watcher): live-verified selectors and overlay handling
- `add_button` set to the sticky-bar "Add to cart" control, scoped so recommendation-card "ADD" buttons cannot match.
- New `dismiss_modal` selector; the Blinkit app-download interstitial is closed at the top of every check and before every cart click.
- New `bar_price` selector for a pre-cart price sanity check.
- Added a wait for the action bar, which hydrates after the location bar and caused intermittent `unknown_layout` errors.
- `--capture` now waits for networkidle plus real text, captures every target, and prints what each selector actually matches.
- Fixed `--login` crashing with TargetClosedError when the browser window is closed instead of pressing Enter.
- `delivery.label` set to "Doddakannelli": Blinkit shows no pincode, so the label must appear in the rendered address string.

Live verification: four consecutive cycles, both cars correctly OUT_OF_STOCK, no errors. WhatsApp alerting confirmed working end to end.

## 2026-11-07 — fix(deploy): run locally in Docker after the VPS was Cloudflare-blocked
- Session import now triggers when the profile holds no Blinkit cookies, instead of only when the profile directory is empty. The old check silently skipped import for a profile that exists but cannot be read — exactly a Windows profile mounted into a Linux container — leaving the bot logged out.
- Container gets its own `profile-docker/` volume. Mounting the host's Windows `profile/` both failed to decrypt and risked corrupting the profile `--login`/`--capture` rely on.
- Verified locally: session imported (19 cookies, 1 origin), both cars OUT_OF_STOCK across repeated cycles, no Cloudflare challenge on a residential IP.
- Verified `restart: unless-stopped` fires on a real crash (control container restarted twice). Note `docker kill` never triggers it — Docker treats a manual kill as user-initiated, so it is not a valid crash test.
