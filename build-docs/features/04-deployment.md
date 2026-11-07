# F4 — Deployment: session bootstrap, Docker, 24/7

## Purpose
Get a logged-in, location-set browser session onto an India-region VPS without ever doing an interactive OTP login there, then keep the process alive forever.

## Architecture
**Session bootstrap (the critical piece).** The VPS cannot receive your login OTP, and attempting a fresh login from a datacenter IP is the most likely way to get flagged. So:
1. On your own PC, run `python main.py --login`. This opens a **headful** Chromium on the persistent profile dir, you log in by hand, complete the OTP once, and set the delivery address.
2. The script then verifies the address matches config and exits.
3. `tar` the profile dir, copy it to the VPS, mount it into the container at the same path.
4. The VPS runs headless on that profile and only ever refreshes the session.

**Docker.** `python:3.13-slim` plus Playwright's Chromium deps, `playwright install --with-deps chromium`. `docker-compose.yml` with `restart: unless-stopped`, two volumes (profile dir, and a data dir holding `state.json` + `logs/`), `env_file: .env`, `TZ=Asia/Kolkata`.

**Liveness.** Heartbeat to Telegram/WhatsApp every ~6 h (F3). Optional external dead-man switch: ping `HEALTHCHECK_URL` once per loop, skipped when the env var is empty. The external ping is what catches a container that is up but wedged.

## Impact map
| Touches | What breaks |
|---|---|
| profile volume | **not mounted → login lost on every container rebuild** → login wall every check |
| state volume | not mounted → the single-order lock resets on rebuild → double-order risk |
| `.env` | must be `env_file`, never baked into the image, never in the repo |
| container TZ | wrong TZ makes logs and any time-window logic misleading |
| F2 | headless-vs-headful rendering differences can change selectors — hence `--capture` runs in the same headless mode the bot uses |
| image size / ARM | not applicable on x86 VPS; would matter if the host changes to a Pi |

## Edge cases and failure modes
- Profile copied while the local browser is still open → corrupt profile. The bootstrap must close the context before telling you to copy.
- Profile dir permissions wrong inside the container → Chromium fails to start; detect and report clearly, do not loop.
- VPS reboot → `restart: unless-stopped` plus Docker's own service start covers it.
- `kill -9` mid-checkout → F1's uncertain-state detector refuses to re-order and alerts.
- Clock drift / NTP absent on the VPS → TLS failures; surfaced as ERROR plus alert.
- Session eventually expires regardless (weeks) → ERROR(login), alert, and you re-run the bootstrap. This is expected maintenance, not a bug.
- Datacenter IP blocked (accepted risk D1) → block detection backs off and alerts; the documented fallback is to move the container to a home machine using the same profile.

## Acceptance criteria
1. `--login` opens a headful browser, and after a manual login the profile dir alone is sufficient for a later headless run to reach the product page logged in.
2. `docker compose up` starts the bot and it sends "Bot started".
3. `docker kill -s KILL` the container → it restarts automatically and does not re-order.
4. Host reboot → container comes back without manual action.
5. `state.json` and the profile survive `docker compose down && up` and an image rebuild.
6. With `HEALTHCHECK_URL` empty, no ping is attempted and nothing errors.
7. No secret appears in the built image (`docker history` / image inspect shows no token).
