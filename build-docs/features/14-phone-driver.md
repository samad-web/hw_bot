# F14 — Phone driver (adb over Tailscale)

## Purpose
One small module the bot uses to drive the relay phone from the VPS: open a link, read the screen, tap an element, and know when the phone is unreachable.

## Architecture
- `phone.py` replaces `app_buyer.py`: `connect()`, `open_link(url, package)`, `dump() -> xml`, `find(xml, text=, desc=) -> bounds`, `tap(bounds)`, `screenshot(path)`, `healthy() -> bool`.
- `subprocess` + `adb -s 100.90.34.88:5555`, XML via stdlib `xml.etree`. No Appium, no new pip dependency.
- Docker: add the `adb` apt package to the image.
- Strictly serial: one adb sequence at a time (the phone has one screen). The loop is single-threaded already.

## Impact map
- `Dockerfile`: +adb. `docker-compose.yml`: the bot must reach `100.90.34.88`; tailscale runs in userspace mode (SOCKS only), so either tunnel adb through the SOCKS proxy or switch tailscale to kernel/TUN mode. Decided by F13 Q6.
- `main.py`: phone health check each cycle; "PHONE ADB LOST / back" alerts with the same 5-min debounce as the relay.
- `app_buyer.py` and its references: removed.
- F10 relay: same phone. Heavy dumps must not starve the relay; watch phone temperature and battery.

## Edge cases
- Phone rebooted → adb refused → one alert after 5 min; Blinkit web keeps running.
- Screen asleep → `input keyevent KEYCODE_WAKEUP`. Lock screen detected in dump → alert; never unlock with a stored PIN.
- Dump fails during animation ("could not get idle state") → retry once after 1 s.
- Call / update prompt / other app on top → unknown screen → capture + alert, no taps.
- Every adb call has a 10 s timeout so a hung phone never hangs the loop.

## Acceptance criteria
1. From the VPS container, `phone.healthy()` is True with the phone on Wi-Fi.
2. `open_link` + `dump` returns XML containing the product title for one share link.
3. Phone off → one alert after 5 min, one on recovery; Blinkit checks continue meanwhile.
4. Every adb call times out (tested with a fake hanging adb).
