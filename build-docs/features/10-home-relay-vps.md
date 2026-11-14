# F10 — Home relay: run on the VPS through the old phone

## Purpose
Blinkit returns 403 to the VPS's datacenter IP (verified 2026-11-11 with curl), and
the user does not want the laptop as the host. The old Android 16 phone at home
becomes a network relay so the VPS reaches Blinkit from the home IP. No laptop,
no USB, no ADB.

## Architecture
```
VPS docker compose
  tailscale  (userspace networking, SOCKS5 :1055, --exit-node=<phone>)
  bot        (Xvfb + headful Chromium, proxy socks5://tailscale:1055)
      Blinkit traffic -> tailnet -> phone (exit node) -> home Wi-Fi -> blinkit.com
      WhatsApp/Telegram  -> direct from the VPS (not proxied)
Phone: Tailscale app, "Run as exit node", Always-on VPN, battery Unrestricted, charger + Wi-Fi.
```
- Userspace mode means only traffic sent to the SOCKS port uses the phone. The
  VPS's own routes, SSH and the other apps on it are untouched.
- **Headful Chromium under Xvfb**, because `/checkout` sits behind Cloudflare
  Turnstile for headless browsers. Plain browser, no fingerprint spoofing, no
  challenge solving.
- The VPS joins the tailnet through a login URL the user clicks once, so no auth
  key is pasted into chat.

## Impact map
- `main.py` `launch()`: add `proxy` and `headless` from config. Same in the login/capture flows.
- `config.py` + `config.yaml`: `network.proxy` (empty = direct), `browser.headless` (bool).
- `Dockerfile`: add `xvfb` and run under `xvfb-run`. `docker-compose.yml`: add a `tailscale` service with a state volume.
- `deploy/deploy.sh`: compose up both services.
- Watcher block detection (F2/F7) is reused: a relay outage looks like a navigation failure.

## Edge cases
- Phone offline (power cut, Wi-Fi down, Tailscale killed): SOCKS connect fails; after 5 min
  continuous outage (blips are silent) the bot sends one "RELAY OFFLINE" alert, backs off and retries, and alerts again
  when the relay recovers. It never falls back to the direct VPS IP: that IP is
  blocked, and hammering it could flag the account.
- Phone reboot: Always-on VPN restarts Tailscale with no human step.
- Home IP rotates (ISP): harmless, because Tailscale reconnects.
- Turnstile challenges even the headful VPS browser: this is the **gate test**.
  If it fails, stop and report. No bypass.
- Tailscale state volume lost: the VPS needs one re-login click. Alert says so.

## Acceptance criteria
1. From the bot container, the egress IP seen through the proxy equals the home IP.
2. A product page loads through the relay (identity gate passes).
3. **Gate:** `/checkout` (cart validated) renders `#payment_widget` from the VPS through the relay.
4. Phone killed → RELAY OFFLINE alert within 2 cycles. Phone back → recovery alert.
5. Notifier traffic does not go through the proxy.
