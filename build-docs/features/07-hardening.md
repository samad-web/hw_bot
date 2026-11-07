# F7 — Hardening: backoff, capture, recovery

## Purpose
A bot that must survive weeks of unattended running fails from slow problems: drifting selectors, leaking memory, silent blindness. This feature makes those visible and survivable.

## Architecture
- **Backoff.** `next_delay(consecutive_errors)` → 1, 2, 5, 15 min, capped at 15. Reset to the normal jittered interval on any successful check. Pure function, trivially testable.
- **Jitter.** `interval ± jitter`, uniform, with the 20 s hard floor applied after jitter.
- **Context recycling.** Close and relaunch the browser context every `N` hours (default 6) to bound memory. The persistent profile makes this cheap and keeps the session.
- **Failure capture.** On ERROR of kind `unknown_layout`, `blocked` or `login`, write HTML plus screenshot to `logs/capture/<ts>-<kind>/`. Capped at the newest 20 directories so disk cannot fill.
- **Blindness detection.** Track consecutive identical OUT_OF_STOCK results with no successful identity match. If identity assertion has not passed in ~1 h, alert "possibly blind" — this is the guard against the quietest and worst failure: watching a page that no longer says what the bot thinks.
- **Graceful shutdown.** SIGTERM/SIGINT set a flag; the loop finishes the current iteration, never aborts mid-checkout, closes the context, and exits 0.
- **Logging.** `logger.py` wraps `logging.handlers.RotatingFileHandler` (5 MB × 3) — stdlib, about 15 lines. Every check result logged with a timestamp. No secrets.

## Impact map
| Touches | What breaks |
|---|---|
| `main.py` loop | backoff and recycling both change timing; a bug here can stall watching entirely |
| F2 | consumes error kinds; a new kind must get a backoff and capture policy |
| F6 | shutdown must never land mid-payment — the flag is checked only between iterations |
| disk | capture dirs and logs are the only unbounded growth; both are capped |
| F3 | blindness and recovery notices are alerts, so a notifier outage hides them (logged regardless) |

## Edge cases and failure modes
- Error storm (site down for hours) → backoff caps at 15 min, one alert per escalation step, not per attempt.
- Recovery after a storm → send a "recovered" notice so silence is never ambiguous.
- Context recycle fails to relaunch → fatal, exit non-zero, let Docker restart the process.
- Recycle landing exactly during a restock → recycle is skipped whenever the last status was IN_STOCK or a checkout is in flight.
- Disk full → capture write fails; log and continue watching rather than crash.
- SIGKILL → no graceful path exists by definition; F1's lock is the safety net.
- Selector drift that still parses (Blinkit renames "Notify Me" to "Coming soon") → caught by blindness detection, not by the parser.

## Acceptance criteria
1. `next_delay` returns 60, 120, 300, 900, 900, 900 for errors 1…6.
2. One success resets the delay to the jittered base interval.
3. Jittered interval never drops below 20 s across 1000 samples.
4. Capture dir is created with both HTML and screenshot on an unknown-layout error, and the count never exceeds 20.
5. SIGTERM during a sleep exits 0 within one interval, with the context closed.
6. SIGTERM while a checkout is in flight does not interrupt it (asserted with a stubbed slow checkout).
7. Identity assertion failing for the configured window triggers exactly one "possibly blind" alert, not one per check.
8. Log file rotates at the size limit and contains no token, OTP or card data.
