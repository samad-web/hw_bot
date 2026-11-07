# ARCHITECTURE

## Process model
One Python process, one Playwright persistent browser context, one page, reused for the whole run. Docker (`restart: unless-stopped`) is the only supervisor. No threads, no asyncio, no scheduler library — the main loop is `while True: check; sleep(interval ± jitter)`.

Telegram commands are polled with `getUpdates(timeout=0)` once per loop iteration, so there is no second thread and no command can interleave with a checkout.

## Data flow
```
config.yaml + .env ──> Config (validated dataclass)
                          │
state.json <──────── state.py (atomic read/write, single writer)
                          │
                   main.py loop
                          ├─ checker.check(page) ──> IN_STOCK | OUT_OF_STOCK | ERROR
                          ├─ executor.handle_restock(page, mode)
                          │      ├─ add_to_cart
                          │      ├─ validate (name, price, qty, address, lock)
                          │      └─ pay (wallet | cod | card+OTP relay)
                          └─ notifier.send(event)
```

## Module boundaries
| Module | Owns | Must not |
|---|---|---|
| `main.py` | loop, timing, backoff, signals, mode dispatch | touch selectors or the DOM |
| `checker.py` | reading stock + identity from the page | click anything, mutate state |
| `executor.py` | all clicks that change the cart or spend money | decide timing, send raw HTTP |
| `notifier.py` | Telegram I/O only | know about Playwright |
| `state.py` | the only writer of `state.json` | know about Telegram or the browser |
| `logger.py` | rotating handler setup | anything else |

**Selectors live only in `config.yaml` under `selectors:`.** No module hard-codes a CSS string. A Blinkit UI change is a config edit, never a code change.

## State machine
`state.json`:
```json
{"order_placed": false, "payment_attempt_started": false, "order_id": null,
 "last_status": "OUT_OF_STOCK", "last_check_ts": 0, "last_alert_ts": 0,
 "paused": false, "mode": "A", "consecutive_errors": 0}
```
Write = serialise to `state.json.tmp`, `fsync`, `os.replace`. Atomic on both POSIX and Windows.

**Single-order lock.** `payment_attempt_started=true` is written *and flushed* before the pay click; `order_placed=true` after confirmation. On startup, `payment_attempt_started && !order_placed` is the uncertain state: the bot refuses to order, checks order history, and alerts. This is the one invariant the whole build protects.

## Stock check
Stock is per dark store, so the delivery location must be live in the session before every check. The persistent profile holds it; the bot re-asserts the displayed address each loop and treats a drift as ERROR, not as a stock reading.

Identity assertion gates the result: if the product title/id on the page does not match config, the result is ERROR. A missing "Add" button on the *wrong page* must never be reported as OUT_OF_STOCK, and a present one must never trigger an order.

## Failure policy
Errors escalate 1→2→5→15 min (capped), reset on any successful check. Blocks and captchas take the same path but alert immediately. Every unknown layout dumps HTML + screenshot to `logs/capture/` before backing off. No `except` is silent.
