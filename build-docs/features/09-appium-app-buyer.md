# F9 — Appium app-buyer (real-device ordering)

## Purpose
Actually place the order. Blinkit web has no cart API and the mobile API is
walled by Play Integrity + HMAC signing (see MEMORY 2026-11-08). The only path
that passes Integrity without evasion is driving the **genuine app on a real,
Google-attested phone**. Appium taps the real buttons; the app handles signing
and attestation itself.

## Hard requirements (non-negotiable)
- A **physical Android phone** connected by USB with **USB debugging** on.
  An emulator fails Play Integrity → the only "fix" is rooting + an integrity-
  spoofing Magisk module = evasion. Out of scope, will not build.
- Blinkit (`com.grofers.customerapp`) installed and **logged in** on that phone,
  with the delivery address set and Blinkit Money wallet funded.
- Phone stays connected and powered while watching. Appium can wake/unlock it.

## Architecture (reuse, don't rebuild)
- **Detection stays on the web watcher** we already have: cheap, proven, no
  battery cost. It flips a product OUT_OF_STOCK → IN_STOCK.
- **New `app_buyer.py`**: on IN_STOCK (Mode C, `order_via=app`), it drives the
  phone:
  1. `adb` deep-link straight to the product: `am start -a VIEW -d
     "https://blinkit.com/.../prid/<id>"` (manifest confirms https deep links).
  2. Wait for the in-app "Add to cart"; tap.
  3. Open cart → checkout → select Blinkit Wallet → place order.
  4. Read the confirmation / order id; record it.
- **Single-order lock reused unchanged** from `state.py`: write
  `payment_attempt_started=<prid>` (fsynced) before the final Place-order tap,
  record the order after. Same crash-safety guarantee as the web path.
- Integration point: `main.handle_restock` Mode C branch calls the app buyer
  instead of `executor.checkout` when configured.

## Selectors
In-app element ids/text/content-desc are **unknown until captured from the live
app** on the connected phone (`app_buyer.py --capture` dumps the UI XML). Every
app selector is a TODO until then. No guessing — same rule as the web selectors.

## Safety
- `--dry-run` stops before the final Place-order / Pay tap, same as web.
- Before every tap, assert the on-screen product title matches the target: the
  identity gate, so it can never buy the wrong item.
- Price ceiling + `max_total_spend_inr` re-read from the checkout screen before
  the order tap; abort + alert on mismatch.
- First real run is supervised, on a low-value in-stock item, user watching.

## Edge cases
- Phone asleep/locked → Appium wakes + unlocks (needs no PIN, or PIN supplied).
- App not on the product screen (deep link bounced to home) → retry once, else
  ERROR + alert, do not blind-tap.
- App update / UI change → capture dump + alert, same as web unknown_layout.
- Device disconnects → ERROR + alert; watcher keeps detecting so nothing is lost.
- Play Integrity failure on a genuine device is not expected; if the app itself
  shows an integrity/error screen, abort + alert (do not attempt to bypass).

## Acceptance criteria
1. `adb devices` shows the phone; `app_buyer.py --capture` dumps UI XML for an
   in-stock product screen.
2. Dry-run drives Add→cart→checkout and stops before the order tap, alerting
   what it would buy.
3. Identity mismatch on screen aborts before any tap.
4. Lock written+fsynced before the order tap; a crash after leaves the uncertain
   state that blocks re-ordering.
5. One supervised real buy of a cheap in-stock item completes and records an
   order id.
