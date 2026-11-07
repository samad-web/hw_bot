# PROJECT MEMORY

## Decisions
- **2026-11-07 — Host: India-region cloud VPS.** User chose this over my recommendation of a home always-on machine. Rationale given against it: datacenter IP raises bot-flag risk and can geo-fence the per-dark-store stock reading. Accepted; mitigated by local headful login + copied browser profile, and by block detection that backs off and alerts instead of retrying. **If blocks recur, revisit this first.**
- **2026-11-07 — Build through Mode C**, payment via Blinkit Money wallet only for the first real run. COD deliberately not relied on: it is being withdrawn from many Blinkit accounts and may not appear at checkout.
- **2026-11-07 — State is an atomic JSON file, not SQLite.** Six keys, one writer; `os.replace` gives equivalent crash safety in ~20 lines. Spec Section 11 allows this with justification.
- **2026-11-07 — Telegram via plain `requests` + `getUpdates`,** not `python-telegram-bot`. Avoids an async framework for 6 commands; keeps the loop single-threaded so no command can interleave with a checkout.
- **2026-11-07 — Evolution API (WhatsApp) added as a second outbound alert channel (D8).** Telegram remains the only inbound/command channel: receiving WhatsApp commands requires a public webhook endpoint on the VPS, which is disproportionate new attack surface for six commands. Credentials live in `.env` only.
- **2026-11-07 — Selectors live only in `config.yaml`.** No CSS string in any module. A Blinkit UI change must be a config edit.
- **2026-11-07 — Verified by search:** Blinkit Money wallet is real (`blinkit.com/account/wallet`). COD exists but is account/area-dependent and is revoked from some accounts. Spec Section 16's two "fully hands-off" methods are therefore one reliable (wallet) and one unreliable (COD).

## Constraints
- Polling floor 20 s, hard, regardless of config. One account, one session, no parallelism.
- No captcha solving, no stealth plugins, no SMS/OTP interception. Blocked → back off and alert.
- No card number, CVV, UPI PIN or password is ever stored, logged or screenshotted.
- `max_orders_total = 1`. Default config is Mode A + `--dry-run`.

## Open questions
- Exact product + Blinkit URL, delivery address (label/lat/lng/pincode), price ceilings, Telegram credentials.
- Evolution API: confirmed base URL, instance identifier accepted on the send route, destination number. `/instance/fetchInstances` returned 404 with the instance token; further probing blocked pending permission.
- Git repo and GitHub remote not created yet — awaiting user approval.

## Known issues
- All Blinkit selectors are unverified until `--capture` is run against a logged-in session. Until then every selector is a TODO and the bot will report ERROR rather than a false OUT_OF_STOCK.
