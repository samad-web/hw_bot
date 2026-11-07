# F3 — Notifier: Telegram + WhatsApp (Evolution API)

## Purpose
Speed is the whole point: the restock alert must reach the phone before the bot does anything else. This is also the only channel for "the bot is blind", and the only way to control it without SSH.

## Architecture
Two outbound channels, both optional, at least one required.

- **Telegram** (`requests` → Bot API). `send_telegram(text)` → `POST /bot<token>/sendMessage`, 5 s timeout, 2 retries. Also the **only inbound channel**: `poll_commands()` → `getUpdates` with a persisted offset, filtered to the configured chat id, called once per loop iteration from `main.py`. Commands therefore execute between checks and can never interleave with a checkout.
- **WhatsApp via Evolution API** (added 2026-11-07 at user request). `send_whatsapp(text)` → `POST {base}/message/sendText/{instance}`, header `apikey: <token>`, body `{"number": "<E164 digits>", "text": "..."}`. Same 5 s timeout and retry policy. **Outbound only** — see decision D8.
- `send(text, priority=False)` fans out to whichever channels are configured. A channel failing is logged, never fatal, and never blocks the other channel.

No abstraction layer, no plugin registry: two functions and a fan-out, about 15 lines more than Telegram alone.

### Why WhatsApp is outbound only (D8)
Receiving WhatsApp commands means Evolution must POST a webhook to the bot, which means running an inbound HTTP server with a public URL and auth on the VPS. That is a disproportionate amount of new surface for six commands that Telegram already handles. Telegram keeps `/status /pause /resume /stop /mode /otp`; WhatsApp mirrors the alerts. Revisit only if Telegram is dropped entirely.

### Unverified
The Evolution base URL, the instance identifier accepted on the route, and the destination number are **unconfirmed** — a probe of `/instance/fetchInstances` returned 404 (consistent with an instance-scoped token, which typically cannot list instances) and further probing was blocked pending the user's permission. All three stay config values; a startup self-test message proves the channel or fails loudly.

## Events
Per spec Section 9: bot started, heartbeat (~6 h), restock detected (priority), cart ready, order placed, missed/sold out, error/blocked.

## Impact map
| Touches | What breaks |
|---|---|
| `main.py` loop | command polling adds one HTTP call per iteration; a hang would stall checks — hence the hard timeout |
| `state.json` | `/pause`, `/mode`, `/stop`, `/otp` all mutate state and must go through `state.save` |
| F6 OTP relay | `/otp` is the human step for a card payment; a dropped message means a timed-out checkout |
| `.env` | tokens, chat id, Evolution URL/instance/number. A wrong chat id means total silence → startup self-test exists to catch exactly that |
| logs | no message may ever contain a token, an OTP, or payment identifiers |

## Edge cases and failure modes
- Either provider down or no network → log and keep watching. Watching matters more than alerting.
- Both channels fail at startup → exit with a clear error. A bot that cannot alert is useless.
- Evolution instance disconnected from WhatsApp (phone unlinked) → send returns an error state; alert via Telegram, warn in heartbeat.
- `/stop` during an in-flight checkout → honoured *after* the checkout resolves, never mid-payment.
- `/mode C` while `order_placed` is true → accepted, but the lock still blocks ordering and the reply says so.
- Duplicate `getUpdates` delivery → offset is persisted, each update handled once.
- Mode A alert spam → 10-minute mute window after a restock alert.
- `/otp` arriving after the relay window closed → rejected with a clear reply, never entered into the page.

## Acceptance criteria
1. Startup sends "Bot started" naming the product on every configured channel; if all configured channels fail, exit non-zero.
2. A command from a non-configured chat id produces no reply and no state change.
3. `/pause` stops checks within one interval, `/resume` restarts them, and both survive a process restart.
4. `/status` reports mode, lock state, last result, consecutive errors, and per-channel health.
5. One channel unreachable → the other still delivers; the error is logged once per backoff step, not per attempt.
6. Mode A restock alert fires once, then is muted for 10 minutes.
7. No log line or outbound message ever contains a bot token, an Evolution apikey, or an OTP.
8. WhatsApp send is skipped cleanly (no error, no crash) when Evolution config is absent.
