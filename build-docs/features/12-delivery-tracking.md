# F12 — Delivery tracking

## Purpose
User wants to know when the order is coming and when it has arrived, so the cash is ready.

## Architecture
- After `record_order`, the product's order record gets `status` and `status_ts`.
- Each loop (at most once per 3 min while an order is open): load `blinkit.com/account/orders`
  through the same browser and relay. Find the card for the recorded order (order id,
  else the latest card whose items match product.name). Read the status text.
- On a change, send an alert: e.g. "K5 Blazer: Out for delivery — keep Rs 555 ready" / "Delivered".
- Terminal states: `Delivered`/`Arrived` close tracking. `Cancelled` sends an alert and
  **re-arms that product** (removes its order record and refunds `total_spent`), so a
  cancelled order doesn't stop the user getting the car.
- Watching the other car carries on while one order is open. Waiting for delivery
  could miss a short restock. The spec rule "one at a time" is about payment,
  which the lock already serialises.

## Impact map
- `state.py`: order record gains `status`, `status_ts`; add `rearm(state, prid)`.
- `main.py` loop: call `track_orders()` when any order is open.
- New small `tracker.py` (parse + diff) or a function in `checker.py`. Pick whichever is smaller.
- `notifier.handle_command /status`: show the order status.

## Edge cases
- Order card not found → keep the last status and log it; no alert spam. After 24h, alert once "can't see order status, check app".
- Page layout change → status unchanged plus a capture dump (existing unknown_layout path).
- Cancelled after a refund → re-armed; the spend cap is recomputed.

## Acceptance criteria
1. Status change fixture → exactly one alert per change.
2. Delivered → tracking stops; the product stays bought.
3. Cancelled → product re-armed, spend refunded, alert sent.
4. Missing card → no alert until the 24h staleness rule.
