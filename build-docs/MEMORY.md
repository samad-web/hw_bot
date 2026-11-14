# PROJECT MEMORY

## Decisions
- **2026-11-07 — Host: India-region cloud VPS.** User chose this over my recommendation of a home always-on machine. Rationale given against it: datacenter IP raises bot-flag risk and can geo-fence the per-dark-store stock reading. Accepted; mitigated by local headful login + copied browser profile, and by block detection that backs off and alerts instead of retrying. **If blocks recur, revisit this first.**
- **2026-11-07 — Build through Mode C**, payment via Blinkit Money wallet only for the first real run. COD deliberately not relied on: it is being withdrawn from many Blinkit accounts and may not appear at checkout.
- **2026-11-07 — State is an atomic JSON file, not SQLite.** Six keys, one writer; `os.replace` gives equivalent crash safety in ~20 lines. Spec Section 11 allows this with justification.
- **2026-11-07 — Telegram via plain `requests` + `getUpdates`,** not `python-telegram-bot`. Avoids an async framework for 6 commands; keeps the loop single-threaded so no command can interleave with a checkout.
- **2026-11-07 — Evolution API (WhatsApp) verified (Evolution GO):**
  - Host: `https://chat.sirahagents.com` (Manager UI at `/manager`)
  - Server is **Evolution GO** engine.
  - Instance name: `Samad` (User: Abdul Samad M, JID: `917806966124`).
  - Auth: instance token `409fca14-d122-479f-a4b9-50b6653efcc3` passed in `apikey` header.
  - Endpoints: status at `GET /instance/status` (tested: `{"Connected": true, "LoggedIn": true}`), text send route is `POST /send/text` with `{"number": ..., "text": ...}`.
  - `notifier.py` supports both Evolution GO (`/send/text`) and Evolution Node (`/message/sendText/{instance}`).
- **2026-11-07 — Selectors live only in `config.yaml`.** No CSS string in any module. A Blinkit UI change must be a config edit.

- **2026-11-14 — User: Zepto, Instamart, FirstCry are not reachable on the web; drive their apps on the phone, as planned for Blinkit (F9).** Proposed PLAN §7 (D15–D20, F13–F16), awaiting approval. I pushed back on a full AI agent (cost, latency, wrong taps with money) and recommended a deterministic watcher with an LLM only as a later fallback; user has not yet decided.
- **2026-11-14 — D16 accepted:** user is fine with the manual step after a phone restart (re-enable wireless adb). Rest of PLAN §7 still awaiting approval.

## Constraints
- Polling floor 20 s, hard, regardless of config. One account, one session, no parallelism.
- No captcha solving, no stealth plugins, no SMS/OTP interception. Blocked → back off and alert.
- No card number, CVV, UPI PIN or password is ever stored, logged or screenshotted.
- `max_orders_total = 1`. Default config is Mode A + `--dry-run`.

## Open questions
- Exact product + Blinkit URL, delivery address (label/lat/lng/pincode), price ceilings, Telegram credentials (bot token & chat id).
- Destination phone number for WhatsApp alerts (defaulted to `917806966124` in `.env`).

## Known issues
- **2026-11-14 — F17 car-list editor: tailnet-only (user choice)**, no password; `http://hw-bot-vps:8080`. `safety.max_orders_total` is now a backstop cap (was "must equal sum of max_orders"), because the page edits the list but never config.yaml. Spend caps stay config-only.
- **2026-11-14 — User: no WhatsApp for phone-relay outages** (log only). Kept: restock, login/blocked/blind, routine (startup, heartbeat, "back after N min", car list updated). Orders and manual-check alerts are always sent. Risk accepted: a dead phone is only noticed when it comes back or in the heartbeat.
- **2026-11-14 — "ALERT CHANNELS DOWN" popups on the laptop came from the TEST SUITE**, not the bot: tests that mock `notifier.send` with a bare MagicMock made the startup self-test fall through to `notify_local` (real beep + MessageBox). Fixed with an autouse fixture in `tests/conftest.py`. The bot does not run on the laptop; the stale local container was removed at the user's request.
- **2026-11-14 — ~40% of VPS checks are `unknown_layout`:** over the slow relay the sticky stock bar has not rendered when the check runs (capture shows page body, no bar). The SSR JSON already carries `"product_id":"<prid>"` with `"product_state":"out_of_stock"`/`"is_sold_out"`/`"inventory"`; reading that would fix the blind checks. Not yet built.
- **2026-11-14 — Stale local Docker container `blinkit_hotwheels_bot` (7-day-old image) crash-loops on the laptop** (config error each minute). Harmless but should be removed: `docker rm -f blinkit_hotwheels_bot`.
- All Blinkit selectors in `config.yaml` are empty placeholders until `--capture` is run against a logged-in session. Until then, `checker.py` will report ERROR (`missing_selector`) rather than false OUT_OF_STOCK.

- **2026-11-07 review:** three blockers fixed (stale page, `--state` not threaded, Docker single-file state mount). See CHANGELOG.
- **2026-11-07 — RESOLVED: Blinkit web hides coming-soon items from search/browse, but the direct product deep link renders them fine.** Verified by fetching `blinkit.com/prn/<slug>/prid/1454803` (a Hot Wheels out-of-stock item): the page returns HTTP 200, is server-rendered, and shows the status text **"Coming soon"**, while in-stock products on the same page show **"ADD"**. The Playwright-on-web architecture stands; no Appium or mobile API is needed. **Consequence: the bot MUST be given the direct product URL — searching by keyword will not find the item while it is out of stock.**
- **2026-11-07 — The out-of-stock marker on Blinkit is the text "Coming soon", not "Notify Me" or "Out of stock"** as spec Section 6.3 assumed. `selectors.out_of_stock` must target the Coming-soon element.
- **2026-11-07 — Anonymous Blinkit requests always report "Coming soon".** Stock is resolved per delivery address, so without a logged-in session and a set location every product looks out of stock. Consequence: in-stock selectors (`add_button`, cart, checkout) can only be captured from the user's own session, never derived from a public fetch.
- **2026-11-07 — Blinkit's location bar is SSR'd as an empty shimmer** and hydrated client-side. Any read of the header address must wait for non-empty text or it reports false `location_drift`. Handled by `checker.HYDRATION_TIMEOUT_MS`.
- **2026-11-07 — Selector durability:** Blinkit mixes Tailwind utilities (`tw-*`, deterministic, safe to match exactly) with styled-components classes carrying a per-build hash (`LocationBar__Container-sc-x8ezho-6 gcLVHe`). Always match the latter with `class*=` on the component-name prefix; never the hash.
- **2026-11-07 — Blinkit has TWO unavailable states in the same sticky-bar slot:** "Out of stock" (`tw-text-grey-700`) and "Coming soon" (`tw-text-yellow-700`). A colour-based selector catches only one. The status line `div.tw-text-200.tw-font-medium` is unique page-wide on every product page checked, so match that plus `:has-text()` on the wording.
- **2026-11-07 — Blinkit resolves product pages by `prid` alone**; the slug is cosmetic (`/prn/x/prid/1416802` works). Confirmed targets: K5 Blazer = `prid/799027`, 23 Ram 1500 = `prid/1416802`.
- **2026-11-07 — SCOPE CHANGE REQUESTED: user wants multiple cars watched and auto-bought**, not one. The build is single-product throughout (`product:` singular, `max_orders_total` hard-validated to 1, `stop_after_success`). Needs a plan before implementation.
- **2026-11-07 — Selectors verified LIVE against a logged-in session** (Doddakannelli, Bengaluru). On the two out-of-stock targets `out_of_stock` matches 1 and `add_button` 0; on an in-stock page the reverse. `product_title` and `header_address` match exactly once on all three pages.
- **2026-11-07 — The in-stock CTA is "Add to cart"** in the sticky bar, NOT "ADD". Recommendation cards further down carry their own `role=button` "ADD" controls, so `add_button` MUST stay scoped to `div.tw-items-center.tw-justify-between.tw-p-3` or the bot could cart the wrong car.
- **2026-11-07 — Blinkit shows a "Get the blinkit app" interstitial** that covers the page and swallows clicks. Escape via `div[class*="DownloadAppModal__ContinueLink"]`. Dismissed at the top of every check and before every cart click.
- **2026-11-07 — Blinkit renders no pincode.** The address is a Plus Code plus area, so `delivery.label` must be a token appearing in that string — set to "Doddakannelli".
- **2026-11-07 — The action bar hydrates AFTER the location bar**, causing intermittent `unknown_layout`. Fixed with `CTA_TIMEOUT_MS`; four consecutive live cycles then ran clean.

## 2026-11-07 — VPS deployment BLOCKED by Cloudflare
- Deployed to Hostinger VPS 1714755 (93.127.199.127, Mumbai). Image built, container ran, `session.json` imported cleanly (19 cookies, 1 origin). **But every page returns a Cloudflare challenge**: captured HTML contains `Just a moment...`, `captcha` and `cf-` markers, and **zero** product markup — all selectors match 0.
- **Risk D1 has materialised.** The datacenter IP is bot-flagged. The same code, same session and same selectors work perfectly from the home machine (four clean cycles, both cars OUT_OF_STOCK).
- **Not to be worked around.** Project constraint and spec Section 15 both forbid captcha solving, stealth and evasion tooling. Container has been stopped rather than left retrying.
- **Documented fallback is the home machine** (PLAN.md risk table, D1). Hosting decision needs revisiting with the user.
- Untested long shot: the second Mumbai box 1917148 (62.72.30.234) may sit in a different reputation range, but it runs the spaceair production apps.

## 2026-11-12 — Live ordering decisions
- **D14 repeat orders:** user wants up to 3 Supras + 3 Rams as separate 1-unit orders; the next is placed once the previous order is confirmed (not delivered), if still in stock. I flagged that Blinkit may cancel repeat orders / flag the account; user accepted.
- Targets: Supra 1454828 (replaced K5 799027) + Ram 1416802. Caps: Rs 750/order, Rs 3000 total backstop (user: cash is not a limit).
- User declined a supervised cheap real order; practice (dry run) passed instead. Post-Pay confirmation detection (URL leaves /checkout) is therefore unverified; failure leaves the uncertain lock -> bot stops + alerts, never double-orders.
- Phone relay drops when Android sleeps Tailscale: user must set battery Unrestricted / Always-on VPN / Stay awake.

## 2026-11-11 — CORRECTION: Blinkit web CAN check out (supersedes 2026-11-07 below)
Lead: open-source `hereisSwapnil/blinkit-mcp` (Playwright, Sept 2026) orders on web. Verified live, logged-in profile, never clicked Pay:
- Cart is **client-side until checkout** (so no API call on Add — the 11-07 trace was read wrongly). It DOES survive reload ("2 items Rs 346").
- Mobile `/cart` page → Proceed → address sheet (server-saved addresses) → `PATCH /v5/carts/<id>` → `POST /v5/carts/<id>/validate` → `/checkout` → `GET /createOrder/<id>` → Zomato `zpaykit` iframe `#payment_widget`.
- `/checkout` is behind **Cloudflare Turnstile for headless** (403 "access denied"). A normal **headful** browser loads it without any challenge interaction. Will NOT solve/spoof Turnstile; headful-only.
- Web payment options: Wallets (**Mobikwik only — no Blinkit Money on web**), Cards, Netbanking, UPI, **Cash (enabled)**, Pay Later. → **COD is the only no-human web payment.** The Rs 800 Blinkit Money is app-only.
- Cart selectors: line item `div[class*="CartProduct__Container"]`, minus `div[class*="AddToCart___StyledDiv-"]` (needs JS click; reported outside viewport).
- Leftover test items (Quick Chat, Head Gasket) remain in the cart; executor `has_extra_items` already refuses foreign items, so the order flow must empty the cart first.

## 2026-11-11 — VPS still hard-blocked; bot was down 12.5h
- VPS 93.127.199.127: `curl` product page → **403 access denied** (IP reputation, not browser). Any VPS run needs a residential egress.
- Native bot died silently at 09:38 after a context recycle (no traceback → parent session ended). Restarted 22:27 via `deploy/run_bot.cmd` (restart loop). Scheduled-Task autostart was refused by the permission classifier; user must approve or run it.
- The home IP got Turnstile-blocked once on `/s/` search from a fresh desktop context; product pages via the bot profile still pass.

## 2026-11-07 — Modes B and C are NOT achievable on Blinkit web (SUPERSEDED 2026-11-11)
Investigated while trying to harvest Mode C selectors. Evidence, all consistent:
- Clicking "Add to cart" fires **only Google ad pixels** — zero Blinkit cart/order/checkout API calls. Verified with a network trace on both a mobile UA and a desktop UA (1366x900).
- `blinkit.com/cart` renders "Oops! something went wrong".
- The cart button stays at "0 items Rs 0" after a click; the stepper that briefly appears is client-side only and does not survive a reload.

**Conclusion:** Blinkit's web surface is browse-and-display only; the real cart lives in the mobile app. This is not a selector problem — the capability is absent, so no amount of selector work enables Mode B or C here. It matches the user's first observation that coming-soon items appear only in the app.

**Consequences:**
- Mode A (detect + instant alert) works and is the deliverable. Deployed locally in Docker.
- `safety.max_orders_total`, wallet balance and the spend cap are moot until an ordering path exists.
- Auto-ordering would require spec Section 7 option 2 (Android emulator + Appium) — a substantial separate build — or the undocumented mobile API, which the project's constraints rule out.
- The config-validation guard that blocks Mode C without checkout selectors is doing exactly its job and should stay.

## 2026-11-08 — Blinkit APK analysis: ordering API found but gated
Extracted Blinkit.apk (user-supplied, their own account). Findings:
- Order endpoint: `POST api3.blinkit.com/v3/cart/orders/`; payment via `/v2/sdk/make_payment`, `/v2/sdk/complete_payment`. Hosts: jumbo.blinkit.com, api3.blinkit.com, api2.grofers.com.
- Auth headers: access_token, auth_key, device_id, session_id, merchant_id, app_version, platform, **x-sig**.
- **Guarded by two walls:** (1) HMAC request signing (x-sig; `hmac`/`signature` classes, 33/62 refs) and (2) **Google Play Integrity attestation** (full IntegrityManager/IntegrityTokenRequest stack in dex). No native .so — signing is in Java/Kotlin dex.
- **Verdict:** direct Python calls to /v3/cart/orders/ are NOT realistically achievable. HMAC signing is crackable with effort; Play Integrity is a device-attestation wall designed to be unforgeable from a script. Confirms web-automation and raw-API paths are both dead for auto-ordering.
- **Only viable auto-buy path:** drive the REAL app (Play Integrity + signing handled by the genuine app) on an Android emulator with Play Services via Appium/UIAutomator — spec Section 7 option 2, a separate build. Otherwise: Mode A alert + manual tap stays the deliverable.
