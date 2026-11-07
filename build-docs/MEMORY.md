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

## Constraints
- Polling floor 20 s, hard, regardless of config. One account, one session, no parallelism.
- No captcha solving, no stealth plugins, no SMS/OTP interception. Blocked → back off and alert.
- No card number, CVV, UPI PIN or password is ever stored, logged or screenshotted.
- `max_orders_total = 1`. Default config is Mode A + `--dry-run`.

## Open questions
- Exact product + Blinkit URL, delivery address (label/lat/lng/pincode), price ceilings, Telegram credentials (bot token & chat id).
- Destination phone number for WhatsApp alerts (defaulted to `917806966124` in `.env`).

## Known issues
- All Blinkit selectors in `config.yaml` are empty placeholders until `--capture` is run against a logged-in session. Until then, `checker.py` will report ERROR (`missing_selector`) rather than false OUT_OF_STOCK.

- **2026-11-07 review:** three blockers fixed (stale page, `--state` not threaded, Docker single-file state mount). See CHANGELOG.
- **2026-11-07 — RESOLVED: Blinkit web hides coming-soon items from search/browse, but the direct product deep link renders them fine.** Verified by fetching `blinkit.com/prn/<slug>/prid/1454803` (a Hot Wheels out-of-stock item): the page returns HTTP 200, is server-rendered, and shows the status text **"Coming soon"**, while in-stock products on the same page show **"ADD"**. The Playwright-on-web architecture stands; no Appium or mobile API is needed. **Consequence: the bot MUST be given the direct product URL — searching by keyword will not find the item while it is out of stock.**
- **2026-11-07 — The out-of-stock marker on Blinkit is the text "Coming soon", not "Notify Me" or "Out of stock"** as spec Section 6.3 assumed. `selectors.out_of_stock` must target the Coming-soon element.
