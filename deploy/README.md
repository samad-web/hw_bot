# Deploying to the Hostinger VPS

## Target

`1714755` — **93.127.199.127**, Ubuntu 24.04, KVM 2 (2 vCPU / 8 GB), Mumbai (DC 13).

Chosen because it has an Indian IP (matching the Bengaluru delivery address) and is
the only one of the three boxes not already running a Docker stack. The others:

| VPS | Location | Running | Verdict |
|---|---|---|---|
| 1917148 · 62.72.30.234 | Mumbai | 3 spaceair apps | production, leave alone |
| 1883418 · 187.127.119.27 | Kuala Lumpur | Supabase (11 containers) | production, and wrong country |

## Why the profile directory is NOT copied

A Chromium profile does not move between operating systems. On Windows the cookie
store is encrypted with DPAPI, tied to that Windows user account; Linux cannot
decrypt it, so a copied `profile/` arrives **logged out** and the bot reports every
product unavailable forever.

The session therefore travels as `session.json` — Playwright `storage_state`, plain
JSON holding cookies plus localStorage (Blinkit keeps the chosen delivery location
in localStorage, so cookies alone are not enough). On first run the container finds
an empty profile and imports it.

## One-time, on the machine with the login

```bash
python main.py --login            # OTP once, set the delivery address
python main.py --export-session   # writes session.json
python main.py --capture          # confirms every selector still matches
```

`session.json` holds live auth cookies. It is gitignored. Never commit it.

## Deploy

```bash
./deploy/deploy.sh                       # defaults to root@93.127.199.127
./deploy/deploy.sh root@HOST /opt/hw_bot # or specify
```

Requires an SSH key authorised on the box. Add one with the Hostinger API
(`vps_ssh-keys_add-virtual-machine`) or via hPanel.

## Verify

```bash
ssh root@93.127.199.127 'cd /opt/hw_bot && docker compose logs -f'
```

Expect a "Bot started" message on Telegram and WhatsApp, then a line per target
per cycle reading `OUT_OF_STOCK Out-of-stock indicator visible`. Anything reading
`ERROR` repeatedly means the session did not transfer — re-export and redeploy.

Then confirm it survives a kill and a reboot:

```bash
ssh root@93.127.199.127 'docker kill -s KILL blinkit_hotwheels_bot'   # must come back
ssh root@93.127.199.127 'reboot'                                      # must come back
```

## Going live on Mode C

The bot ships in Mode A. Do not jump straight to C: `pay_button`,
`wallet_balance` and `order_confirmation` only exist on a real checkout screen and
are still empty in `config.yaml`. Run Mode B first, harvest those selectors during
one deliberate purchase, then switch.

## Session expiry

The Blinkit session will eventually lapse (weeks). The bot reports `ERROR(login)`
and alerts. Recovery is to re-run `--login` and `--export-session` locally, then
re-run `deploy.sh`. This is expected maintenance, not a fault.
