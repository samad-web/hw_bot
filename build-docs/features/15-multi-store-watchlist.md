# F15 — Multi-store watchlist

## Purpose
Let the user's car list span stores: one car may be on Blinkit and Zepto, another only on FirstCry.

## Architecture
- `config.yaml` products gain `store: blinkit|zepto|instamart|firstcry` (default `blinkit`, so today's config is unchanged) and `url` = the share link.
- State key becomes `<store>:<id>`; Blinkit keeps the bare `prid` so the live VPS `state.json` (orders, locks) stays valid.
- Main loop dispatches per product: `blinkit` → existing web checker/executor; others → the app adapter (F16).
- Spend cap, `max_orders` and the payment lock stay global: one payment in flight at a time, across all stores.

## Impact map
- `config.py` (store allowed, url host matches store, max_orders sum), `state.py` keys, `main.py` loop + heartbeat, notifier text names the store.
- Tests: `test_config.py`, `test_state.py`, `test_main.py`.
- Live VPS `state.json`: must load unchanged (migration test).

## Edge cases
- Unknown store, or a link from a different store → config error at startup, not at restock time.
- Same car on two stores → two targets with their own `max_orders`; user sets counts.
- Store judged alert-only by F13 → per-store `mode: A`.

## Acceptance criteria
1. Existing Blinkit-only config and VPS `state.json` work with zero edits.
2. Mixed-store config validates; bad store/url rejected with a clear message.
3. Only one payment in flight across all stores (lock test).
