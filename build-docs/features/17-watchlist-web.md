# F17 — Car-list web editor

## Purpose
User asked (2026-11-14) for a webpage to update the car links without editing `config.yaml` or redeploying. Also lays the store field from F15 into config.

## Architecture
- `watchlist_web.py`: stdlib `http.server`, one page. GET shows every car (store, name, link, max price, orders) plus an "Add a car" row; POST saves the whole list.
- Writes `data/watchlist.json` atomically (`state.save`: fsync + `os.replace`). Validation is `config.load_config(products_raw=...)`, the bot's own rules, so the page cannot save a list the bot refuses.
- Bot: `config.load_config(watchlist_path=...)` prefers `data/watchlist.json`, else `config.yaml` products. `main.reload_watchlist` re-reads it at the top of each cycle when its mtime changes (never mid-checkout); an invalid file keeps the old list and sends "REJECTED".
- `ProductConfig.store` (default `blinkit`). Ids derived from the link: Blinkit prid; other stores `<store>:<sha1(url)[:10]>`. Only Blinkit cars are checked until F14–F16.
- Access: **tailnet only** (user choice). Container `hw_watchlist_web` shares the tailscale network namespace, binds 127.0.0.1:8080, publishes no port. URL: `http://hw-bot-vps:8080` or `http://100.124.162.119:8080` from any device on the user's Tailscale account.

## Impact map
- `config.py`: store + link validation; `max_orders_total` changed from "must equal the sum of max_orders" to a **backstop cap** (the web cannot edit config.yaml, so equality would block every edit). Spend caps unchanged and not editable from the page.
- `main.py`: watched() Blinkit-only; reload each cycle; startup message lists saved app-store cars.
- `docker-compose.yml` new service; `Dockerfile` COPY; `deploy/deploy.sh` scp list.
- `state.json`: untouched; Blinkit keys stay bare prids.

## Edge cases
- Bad link host / http / unknown store / non-numeric / empty list → 400 with the reason, file unchanged, user's input kept on the page.
- Cross-site POST (CSRF from another tab) → 403 (Origin/Referer must match Host). Body > 100 KB → 413.
- Names are HTML-escaped (XSS). `X-Frame-Options: DENY`.
- Removing a car mid-checkout: reload happens only between cycles; the payment lock is global and independent of the list.
- Concurrent write/read: atomic replace, the bot reads either the old or the new file.
- Page down: the bot keeps running on the last list.

## Acceptance criteria
1. First visit shows the config.yaml cars.
2. A valid list saves with derived ids.
3. Invalid input is rejected with a reason and the old file is kept.
4. Cross-site POST refused.
5. Names escaped.
6. Bot reloads a valid list within one cycle; keeps the old list on an invalid one.
7. Only Blinkit cars are checked until app support lands.
8. Reachable from a tailnet device; not reachable from the public internet.
