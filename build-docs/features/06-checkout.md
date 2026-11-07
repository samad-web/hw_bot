# F6 — Checkout and payment (Mode C)

## Purpose
Complete the order unattended from a pre-loaded Blinkit Money wallet, with enough gates that the worst realistic outcome is a missed item rather than a wrong or duplicated purchase.

## Architecture
`executor.checkout(page, cfg, cart: CartResult)`:

1. **Pre-checkout validation — all must pass or abort and alert:**
   - item name matches `product.name`
   - unit price ≤ `max_price_inr`
   - total payable ≤ `max_order_value_inr`
   - quantity == `product.quantity`
   - cart contains no unexpected items
   - delivery address == configured address
   - `can_order(state)` is True (lock not held, `max_orders_total` not reached)
2. **Payment method selection** per `payment.priority`, intersected with what the checkout screen actually offers:
   - `blinkit_wallet` — read displayed balance; use only if balance ≥ total payable.
   - `cod` — only if explicitly offered for this cart.
   - `saved_card_otp_relay` — reach the OTP field, alert "reply /otp <code> within 2 min", enter whatever the human sends, confirm. Timeout → cancel safely and alert.
   - none usable → abort, alert "Cart ready, pay manually NOW".
3. **The lock sequence** (the single most important ordering in the codebase):
   ```
   state.save(payment_attempt_started=True)   # fsynced BEFORE the click
   click pay
   wait for confirmation screen
   state.save(order_placed=True, order_id=<id>)
   ```
4. Capture the confirmation screen, read order id and ETA, alert, and if `stop_after_success` shut down gracefully.

**Retry policy.** A failure after `payment_attempt_started` is never blindly retried. The bot first opens order history and checks for an order matching this item: found → mark `order_placed`, alert, stop; clearly absent → one retry allowed; ambiguous → stop and alert for manual check.

**`--dry-run`** performs everything including validation and method selection, then stops immediately before the pay click and alerts what it would have done.

## Security rules (spec 16.5)
No card number, CVV, UPI PIN or password is stored, logged, or screenshotted. The bot never reads SMS and never bypasses authentication — the OTP arrives only from the human over Telegram. Payment identifiers are masked in logs, and confirmation screenshots are saved masked.

## Impact map
| Touches | What breaks |
|---|---|
| F1 lock | **a lock bug here is a double charge** — the only irreversible failure |
| F5 `CartResult` | all validation reads from it; a bad read-back means validating fiction |
| F3 | OTP relay depends on inbound Telegram; the restock and outcome alerts depend on outbound |
| `config.yaml` ceilings | the only thing bounding worst-case spend |
| real money / real account | every other feature is reversible; this one is not |
| `selectors` | checkout, payment list, wallet balance, pay button, OTP field, confirmation, order history |

## Edge cases and failure modes
- Sold out at the payment step → alert "missed it", clear `payment_attempt_started`, resume watching.
- Wallet balance just short (fees added at the last step) → do not silently fall through to a card; abort and alert unless the next method in priority is explicitly allowed.
- Total changes between validation and pay (surge fee appears) → re-read and re-validate immediately before the click; any change above the ceiling aborts.
- Pay clicked, page hangs, no confirmation → the ambiguous case. Order-history check decides; default is stop and alert.
- Charged but no order visible → alert with the last masked screenshot, stop, never retry.
- OTP arrives twice or malformed → only the first well-formed 4–8 digit code within the window is used.
- Crash between the two `state.save` calls → startup detects uncertainty and refuses to order.
- `max_orders_total` reached → refuse even if everything else passes.
- Address changed server-side mid-session → the re-validation before the click catches it.

## Acceptance criteria
1. Each validation failure independently blocks payment and produces a named alert (one test per rule).
2. Price ₹1 over `max_price_inr` → no pay click.
3. Wallet balance below total → no pay click when wallet is the only allowed method.
4. `payment_attempt_started` is written and fsynced before the pay click (asserted by ordering spy).
5. Simulated crash after that write → next startup refuses to order and alerts.
6. Simulated post-pay failure with a matching order in history → `order_placed=true`, no retry.
7. Simulated post-pay failure with no order and no charge → exactly one retry.
8. `--dry-run` never calls the pay click, on any path, in any mode.
9. OTP relay: a code outside the window is rejected; no OTP appears in any log.
10. After success, `stop_after_success: true` exits cleanly and a restart does not re-order.
