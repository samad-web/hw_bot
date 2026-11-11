# F11 — Web checkout with Cash on Delivery (Mode C)

## Purpose
Place the order on blinkit.com with no human. Verified 2026-11-11: the web can
check out, but Blinkit Money is not offered on the web, so COD is the only payment
that needs no OTP or PIN. User chose COD.

## Flow (all verified live up to, not including, Pay Now)
1. **Empty the cart**: `/cart`, JS-click every minus `div[class*="AddToCart___StyledDiv-"]`, reload, assert empty.
2. Product page → sticky-bar "Add to cart" (existing scoped `add_button`).
3. `/cart` → assert exactly one `CartProduct__Container`, title == product.name, qty 1, unit price ≤ ceiling.
4. "Proceed" → address sheet → pick the card containing `delivery.pincode` (560035).
5. "Proceed To Pay" → `/checkout` → wait for `#payment_widget` (zpaykit iframe).
6. In the frame: `div[title='Cash']` must be enabled; click it. If it is disabled, ABORT and alert. Never fall back to another method.
7. Re-read the grand total. It must be ≤ `max_order_value_inr` and within `max_total_spend_inr`.
8. Write the lock `payment_attempt_started=<prid>` (fsync). Then click "Pay Now".
9. Wait for the confirmation or order page, then `record_order` and alert:
   "ORDERED <car> — COD, keep Rs <total> cash ready".

`--dry-run` stops before step 8 and alerts what it would have bought.

## Impact map
- `executor.py`: replace the wallet path in `add_to_cart`/`checkout` with the steps above, and add `empty_cart`. `validate_cart` is unchanged and stays the safety gate.
- `config.yaml` selectors: add `cart_line`, `cart_minus`, `proceed`, `proceed_to_pay`, `payment_frame`, `cod_option`, `pay_now`. `payment.priority: [cod]`.
- `config.py`: allow `cod` as a payment method. Mode C validation now requires these selectors.
- `state.py`: unchanged (lock and order records reused).
- Tests: `test_executor*` updated with fake-page fixtures.

## Edge cases
- Sold out between Add and Pay → `missed`. Alert and keep watching.
- COD disabled for this order → abort + alert "pay manually in app (wallet)".
- Address sheet missing 560035 → abort (never ship elsewhere).
- Crash after the lock and before confirmation → uncertain state blocks re-ordering. Alert "check Blinkit orders" (existing behaviour).
- A foreign item reappears in the cart → `has_extra_items` aborts.
- Logged out (session expired) → login wall → alert "re-login needed". The one human step this design cannot remove; Blinkit decides the session lifetime.

## Acceptance criteria
1. Dry run on a cheap in-stock car reaches the Cash-selected screen, does not press Pay Now, and alerts the total.
2. Cart with a foreign item → emptied first. If emptying fails → abort.
3. COD disabled (fixture) → abort, no lock written.
4. Total over the ceiling → abort, no lock written.
5. **One supervised real COD order** of a cheap in-stock item, with the user present to receive and pay it. The order id is recorded.
