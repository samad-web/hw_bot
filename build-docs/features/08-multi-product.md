# F8 — Multiple targets, bought one at a time

## Purpose
Watch several Hot Wheels cars at once. When any one restocks, buy that one, then
carry on watching the rest. Each car is bought at most once; the bot stops when
every target is bought.

Supersedes the single-product assumption in PLAN.md §1 and spec Section 1.

## Why this is not a small change
`product:` is singular in config, `max_orders_total` is **hard-validated to 1**,
`order_placed` is a single boolean, and `stop_after_success` exits after one
order. All four assume one target.

## Architecture

**Config** — `product:` becomes `products:`, a list. Per-car fields:
```yaml
products:
  - id: "799027"                     # Blinkit prid; the stable key for state
    name: "Hot Wheels 1985 Chevrolet K5 Blazer Die Cast Car"
    url: "https://blinkit.com/prn/x/prid/799027"
    max_price_inr: 650
    quantity: 1
safety:
  max_orders_total: 3                # must equal len(products)
  max_total_spend_inr: 1500          # NEW: hard ceiling across ALL orders
```
`prid` is the key because Blinkit resolves pages by it and the slug is cosmetic.

**State** — replaces the single lock with a per-product map, plus one global
in-flight flag (only ever one checkout at a time):
```json
{"orders": {"799027": {"order_placed": true, "order_id": "...", "spent": 549}},
 "payment_attempt_started": "1416802",
 "total_spent": 549}
```
`payment_attempt_started` becomes the **prid currently being paid for**, or
`null`. That keeps the existing crash-safety guarantee and additionally records
*which* car was in flight, which the order-history check will need.

**Loop** — each cycle iterates only the not-yet-bought targets:
```
for p in products where not bought(p):
    goto p.url; check
    if IN_STOCK: alert -> cart -> validate -> pay -> mark bought -> break cycle
    sleep(per_request_gap)
```
Breaking after a purchase means the next cycle starts fresh, so two checkouts can
never overlap. Exit when every target is bought.

**Polling budget** — N targets means N page loads per cycle. The 20 s floor
becomes *per request*, not per cycle: `cycle >= 20 * len(products)`, with the
existing jitter applied on top. 3 cars at a 45 s base is one request every 15 s,
which is below the floor and would be impolite, so the floor now scales.

## Impact map
| Touches | What breaks |
|---|---|
| `config.py` | whole product section + the `max_orders_total != 1` validator I added; every placeholder check becomes per-product |
| `state.py` | `can_order` and `needs_manual_check` take a prid; migration needed for existing `state.json` |
| `main.py` | loop becomes per-product; `stop_after_success` means "all bought" |
| `checker.py` | unchanged — it already takes the page and a config; it just needs per-product name/url |
| `executor.py` | `validate_cart` compares against the *specific* target, not the single global one |
| `tests/` | every fixture using `cfg.product.*` |
| **money** | N purchases instead of 1. `max_total_spend_inr` is the only thing bounding the total. |

## Edge cases and failure modes
- Two cars restock in the same cycle → buy the first, `break`, buy the second next cycle. Never two checkouts in flight.
- Crash mid-payment → `payment_attempt_started` names the prid; the bot refuses **all** further ordering until a human clears it, not just that car's.
- Cart not empty from a previous failed attempt → the existing extra-items check aborts; must be cleared manually.
- Wallet runs dry after car 1 → car 2's payment-method selection finds no eligible method, alerts "pay manually NOW", keeps watching.
- `total_spent + this order > max_total_spend_inr` → refuse, alert. Checked *before* the lock write.
- A target is delisted (404) → ERROR for that car only; the others keep being watched.
- Same car appears twice in config → reject at startup (duplicate prid).

## Acceptance criteria
1. Two targets configured, one restocks → only that one is ordered; the other is still watched afterwards.
2. After both are bought, the bot exits cleanly and a restart does not re-order either.
3. A per-product lock survives a crash: a bought car is never re-bought.
4. `payment_attempt_started` set to a prid blocks ordering of **every** target until cleared.
5. `max_total_spend_inr` blocks the order that would cross it, before any lock write.
6. Cycle interval with 3 products is never below 60 s total, and no two requests are less than 20 s apart.
7. Duplicate prid in config → startup error naming it.
8. `max_orders_total != len(products)` → startup error.
