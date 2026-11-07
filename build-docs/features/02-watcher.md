# F2 — Watcher: session, location, availability

## Purpose
Answer one question reliably, every ~45 s, for weeks: is this exact product buyable at this exact address right now? A false OUT_OF_STOCK is the failure that silently loses the item, so the design biases toward reporting ERROR whenever it is unsure.

## Architecture
- `main.py` launches `chromium.launch_persistent_context(user_data_dir, ...)` with a mobile viewport and a normal user agent. The profile carries login plus delivery location; the bot never performs an interactive login on the VPS (see F4 bootstrap).
- `checker.check(page, cfg) -> Status`:
  1. `page.goto(product_url)` (or search by keyword when no URL), `wait_for_selector` on the title.
  2. **Assert location** — read the header address, compare to `delivery.label` / pincode. Mismatch → `ERROR(location_drift)`.
  3. **Assert identity** — page title / product id vs config. Mismatch → `ERROR(wrong_product)`.
  4. Read the CTA: Add or quantity stepper → `IN_STOCK`; Notify Me or Out of stock → `OUT_OF_STOCK`; neither → `ERROR(unknown_layout)`.
- `main.py --capture`: load the page, dump HTML plus a full-page screenshot to `logs/capture/`, exit. This is how real selector values get into `config.yaml` (decision D6).
- Selectors are read from `cfg.selectors`. An empty selector yields ERROR — never a guess.

## Impact map
| Touches | What breaks |
|---|---|
| `config.yaml: selectors` | every selector change lands here; a wrong one turns the bot blind |
| `main.py` loop + backoff | ERROR drives backoff, so an over-eager ERROR stalls polling |
| F5 / F6 | they act on IN_STOCK — a false positive starts a checkout for the wrong item |
| F3 heartbeat | reports last successful identity match, which is how blindness becomes visible |
| persistent profile dir | corrupt or absent profile = logged out = login wall on every check |

## Edge cases and failure modes
- Login wall / expired session → `ERROR(login)`, alert, back off. The bot does **not** attempt an OTP login on the VPS.
- Captcha or HTTP 429/403 → `ERROR(blocked)`, immediate alert, longest backoff. Never retry fast.
- Lazy-rendered CTA → bounded `wait_for_selector`; a timeout is ERROR, not OUT_OF_STOCK.
- Add button present but greyed out → OUT_OF_STOCK only if a disabled attribute is explicitly detected, otherwise ERROR.
- Product delisted (404) → ERROR plus alert. A 404 is not "out of stock".
- Memory creep over days → browser context recycled every N hours (F7).
- Blank or partial render after a network blip → identity assertion catches it → ERROR.

## Acceptance criteria
1. Fixture HTML of an out-of-stock page → `OUT_OF_STOCK`.
2. Fixture HTML of an in-stock page → `IN_STOCK`.
3. Fixture of a *different* product that has an Add button → `ERROR`, never `IN_STOCK`.
4. Fixture with the wrong address in the header → `ERROR(location_drift)` regardless of the CTA.
5. Empty or absent selector in config → `ERROR` naming the selector in the log.
6. Login-wall fixture → `ERROR(login)` plus an alert, never OUT_OF_STOCK.
7. `--capture` writes HTML and a screenshot and exits 0 without ordering anything.
