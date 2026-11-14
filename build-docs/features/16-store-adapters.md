# F16 — Store adapters (Zepto, Instamart, FirstCry)

## Purpose
Per-store knowledge kept as data: package name, stock texts, cart/checkout/COD button texts. Built one store at a time, only for stores that pass F13.

## Architecture
- `config.yaml` → `stores.<name>`: `package`, `in_stock_texts`, `out_of_stock_texts`, `add_text`, `cart_text`, `checkout_text`, `cod_text`, `place_order_text`. Values come from F13 dumps, never guessed (same rule as Blinkit selectors).
- One generic `app_store.py`:
  - `check(product)`: open link → dump → identity (title contains product name) → stock state.
  - `order(product)`: add → cart (only this item) → checkout → assert COD + address + price ≤ ceiling → write lock (fsync) → place → read confirmation.
- Store-specific code only where a store truly differs.

## Impact map
- Reuses `state.py` lock, executor price/address checks, notifier, hardening captures.
- `main.handle_restock` dispatches by store.

## Edge cases
- Cart has other items → refuse (same rule as Blinkit `has_extra_items`).
- COD missing at checkout → abort before place, alert "pay manually now".
- Price above ceiling, quantity > 1, wrong address → abort + alert.
- Crash after the place tap → uncertain lock → bot stops for that store, never double-orders.
- FirstCry is not 10-minute delivery; stock lasts longer, so it can poll slower.

## Acceptance criteria (per store)
1. Alert-only: OUT_OF_STOCK and IN_STOCK read correctly on real cars.
2. Dry run reaches checkout with COD selected and stops before place.
3. Identity mismatch aborts before any tap.
4. Lock written before place; simulated crash leaves the uncertain state.
