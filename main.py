"""Blinkit Hot Wheels Restock Bot - Main entry point and scheduler loop.

Watches target product availability 24/7, handles alerts and remote commands,
and executes cart/checkout actions according to configured mode and safety rules.
"""

from __future__ import annotations

import argparse
import os
import json
import dataclasses
import logging
import signal
import tempfile
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

import checker
from checker import CheckResultKind
import config
from config import Config
import executor
import hardening
import logger as bot_logger
import notifier
import state

logger = logging.getLogger("hw_bot")

DEFAULT_PROFILE_DIR = Path("profile")
DEFAULT_SESSION_FILE = Path("session.json")
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")


def browser_options() -> dict[str, Any]:
    """Launch options for every unattended flow.

    BROWSER_PROXY sends Blinkit traffic through the home relay (the VPS IP gets
    403). BROWSER_HEADLESS=0 runs a real window (Xvfb on the VPS): /checkout's
    Cloudflare check rejects headless browsers.
    """
    opts: dict[str, Any] = {
        "headless": os.environ.get("BROWSER_HEADLESS", "1") != "0",
        "viewport": {"width": 412, "height": 915},
        "user_agent": MOBILE_UA,
    }
    if os.environ.get("BROWSER_PROXY"):
        opts["proxy"] = {"server": os.environ["BROWSER_PROXY"]}
    return opts


def export_session(context: Any, path: Path = DEFAULT_SESSION_FILE) -> Path:
    """Write cookies and localStorage out as portable JSON.

    A Chromium profile directory does NOT move between operating systems: on
    Windows the cookie store is encrypted with DPAPI, which Linux cannot read,
    so a profile copied to the VPS arrives logged out. storage_state is plain
    JSON and transfers cleanly.
    """
    context.storage_state(path=str(path))
    return path


def import_session(context: Any, path: Path = DEFAULT_SESSION_FILE) -> bool:
    """Load an exported session into a fresh profile. Returns True if applied."""
    p = Path(path)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s: %s", p, exc)
        return False

    cookies = data.get("cookies") or []
    if cookies:
        context.add_cookies(cookies)

    # localStorage is where Blinkit keeps the chosen delivery location, so
    # cookies alone are not enough to restore the session.
    origins = data.get("origins") or []
    if origins:
        page = context.new_page()
        for origin in origins:
            try:
                page.goto(origin["origin"], wait_until="domcontentloaded", timeout=30000)
                page.evaluate(
                    "items => { for (const i of items) localStorage.setItem(i.name, i.value); }",
                    origin.get("localStorage", []),
                )
            except Exception as exc:
                logger.warning("Could not restore localStorage for %s: %s",
                               origin.get("origin"), exc)
        page.close()

    logger.info("Imported session: %d cookie(s), %d origin(s).", len(cookies), len(origins))
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Blinkit Hot Wheels Restock Bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--state", default=state.DEFAULT_PATH, help="Path to state.json")
    parser.add_argument("--mode", choices=["A", "B", "C"], help="Override operating mode")
    parser.add_argument("--dry-run", action="store_true", help="Run without executing pay click")
    parser.add_argument("--login", action="store_true", help="Open headful browser to log in locally and save session")
    parser.add_argument("--capture", action="store_true", help="Capture HTML & screenshot of product page and exit")
    parser.add_argument("--export-session", action="store_true",
                        help="Write session.json (portable cookies+localStorage) from the local profile")
    parser.add_argument("--import-session", action="store_true",
                        help="Load session.json into this machine's profile, then exit")
    parser.add_argument("--practice", metavar="PRID",
                        help="Dry-run the full COD checkout on an in-stock product "
                             "(stops before Pay Now, then empties the cart)")
    return parser.parse_args(argv)


def run_login_flow(cfg: Config, profile_dir: Path = DEFAULT_PROFILE_DIR) -> int:
    """Launch a headful browser so the user can log in and set delivery address locally."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Opening headful browser for local session bootstrap in %s...", profile_dir)
    print("\n=== BLINKIT SESSION BOOTSTRAP ===")
    print("1. A browser window will open.")
    print("2. Log into your Blinkit account and complete OTP verification.")
    print(f"3. Set your delivery location to '{cfg.delivery.label}' ({cfg.delivery.pincode}).")
    print("4. When finished and logged in, close the browser window or press Enter here.\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            **{**browser_options(), "headless": False},
        )
        page = context.new_page()
        target_url = (cfg.products[0].url if cfg.products else "") or "https://blinkit.com"
        try:
            page.goto(target_url)
        except Exception as e:
            logger.warning("Initial navigation warning: %s", e)

        try:
            input("Press Enter here once you have logged in and verified your delivery address...")
        except (KeyboardInterrupt, EOFError):
            pass

        # Export BEFORE closing: the profile itself cannot be copied to a Linux
        # VPS (Windows encrypts the cookie store with DPAPI), but this JSON can.
        exported = None
        try:
            exported = export_session(context)
        except Exception as exc:
            logger.warning("Could not export session.json: %s", exc)

        # The user may well have closed the window rather than pressing Enter;
        # the profile is already flushed to disk by then, so this is not an error.
        try:
            context.close()
        except Exception as exc:
            logger.debug("Browser context was already closed: %s", exc)

    print("\nSession saved to the profile directory.")
    if exported:
        print(f"Portable session written to {exported} - copy THIS to the VPS, not profile/.")
    print("Next: python main.py --capture")
    return 0


def run_session_flow(cfg: Config, export: bool,
                     profile_dir: Path = DEFAULT_PROFILE_DIR) -> int:
    """Export this machine's session to portable JSON, or import it into the profile."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            **browser_options(),
        )
        try:
            if export:
                # storage_state only records localStorage for origins this
                # context has actually visited, and Blinkit keeps the chosen
                # delivery location there - so visit before exporting.
                page = context.new_page()
                try:
                    url = (cfg.products[0].url if cfg.products else "") or "https://blinkit.com"
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(3000)
                except Exception as exc:
                    logger.warning("Could not load Blinkit before export: %s", exc)
                path = export_session(context)
                page.close()
                print(f"Wrote {path}.")
                print("Copy THIS to the VPS. Do not copy profile/: a Windows Chromium "
                      "profile cannot be decrypted on Linux.")
            else:
                ok = import_session(context)
                print("Session imported into the profile."
                      if ok else "No usable session.json found; nothing imported.")
        finally:
            try:
                context.close()
            except Exception as exc:
                logger.debug("Context already closed: %s", exc)
    return 0


REPORTED_SELECTORS = (
    "product_title", "header_address", "out_of_stock", "add_button",
    "quantity_stepper", "login_wall", "cart_open",
)


def report_selectors(page: Any, cfg: Config, product: Any) -> None:
    """Print what each configured selector actually matches on the live page.

    This is the whole point of --capture: turning "it says ERROR" into "this
    selector matched nothing and that one matched four things".
    """
    print(f"\n--- {product.id}  {product.name}")
    for name in REPORTED_SELECTORS:
        sel = getattr(cfg.selectors, name, "")
        if not sel:
            print(f"  {name:<17} -- not configured --")
            continue
        try:
            count = len(page.query_selector_all(sel))
            el = page.query_selector(sel)
            text = ""
            if el:
                text = (el.inner_text() or "").strip().replace("\n", " / ")[:70]
            flag = "" if count == 1 else "   <-- CHECK"
            print(f"  {name:<17} matches={count:<3} text={text!r}{flag}")
        except Exception as exc:
            print(f"  {name:<17} SELECTOR ERROR: {exc}")


def run_capture_flow(cfg: Config, profile_dir: Path = DEFAULT_PROFILE_DIR) -> int:
    """Capture every target page and report what the configured selectors see."""
    saved: list[str] = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            **browser_options(),
        )
        page = context.new_page()
        for product in cfg.products:
            url = product.url or "https://blinkit.com"
            logger.info("Capturing %s (%s)...", product.id or "home", url)
            try:
                # Blinkit renders the product block and the location bar only
                # after hydration, so domcontentloaded is far too early.
                page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception as exc:
                logger.warning("Capture navigation issue for %s: %s", url, exc)

            for sel_name in ("product_title", "header_address"):
                sel = getattr(cfg.selectors, sel_name, "")
                if not sel:
                    continue
                try:
                    page.wait_for_function(
                        "sel => { const el = document.querySelector(sel);"
                        " return !!el && el.innerText.trim().length > 0; }",
                        arg=sel, timeout=20000,
                    )
                except Exception:
                    logger.warning("%s never produced text within 20s: %s", sel_name, sel)
            page.wait_for_timeout(2000)

            cap_dir = hardening.save_failure_capture(page, f"capture_{product.id or 'home'}")
            if cap_dir:
                saved.append(str(cap_dir))
            report_selectors(page, cfg, product)
        context.close()

    if saved:
        print("\nSaved:")
        for s in saved:
            print(f"  {s}")
        return 0
    print("Failed to save any capture.")
    return 1


def run_practice_flow(cfg: Config, prid: str, profile_dir: Path = DEFAULT_PROFILE_DIR) -> int:
    """Dry-run the whole COD checkout on an in-stock product. Never presses Pay Now,
    writes no state, and empties the cart afterwards."""
    url = f"https://blinkit.com/prn/x/prid/{prid}"
    scratch_state = str(Path(tempfile.gettempdir()) / "hw_practice_state.json")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir), **browser_options())
        page = context.new_page()
        ok = False
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector(cfg.selectors.add_button, timeout=30000)
            title = page.inner_text(cfg.selectors.product_title).strip()
            product = config.ProductConfig(id=str(prid), name=title, url=url)
            print(f"Practice target: {title}")
            st = dict(state.DEFAULTS)  # in memory only
            cart = executor.add_to_cart(page, cfg, product, st)
            print(f"Cart: ok={cart.success} item={cart.item_name!r} qty={cart.quantity} "
                  f"unit=Rs {cart.unit_price:.0f} total=Rs {cart.total_payable:.0f} "
                  f"extra_items={cart.has_extra_items} {cart.error}")
            chk = executor.checkout(page, cfg, product, cart, st, dry_run=True,
                                    state_path=scratch_state)
            print(f"Checkout: ok={chk.success} dry_run={chk.dry_run} "
                  f"method={chk.payment_method} {chk.error}")
            print(f"Pay Now matches (not clicked): {page.locator(cfg.selectors.pay_button).count()}")
            ok = chk.success and chk.dry_run
        except Exception as exc:
            print(f"Practice failed: {exc}")
        finally:
            hardening.save_failure_capture(page, f"practice_{prid}")
            print(f"Cart emptied afterwards: {executor.empty_cart(page, cfg)}")
            context.close()
    print("PRACTICE PASSED" if ok else "PRACTICE FAILED")
    return 0 if ok else 1


MODE_A_MUTE_SECONDS = 600


def handle_restock(page: Any, cfg: Config, product: Any, bot_state: dict[str, Any],
                   args: argparse.Namespace, state_path: str) -> tuple[dict[str, Any], bool]:
    """Act on a detected restock of one product. Returns (state, bought).

    The restock alert always goes out before any cart action, so a failure
    further down still leaves you able to buy it by hand.
    """
    now = time.time()

    if cfg.mode == "A":
        alerts = dict(bot_state.get("last_alert_ts") or {})
        if now - alerts.get(product.id, 0) <= MODE_A_MUTE_SECONDS:
            return bot_state, False
        alerts[product.id] = int(now)
        bot_state = state.save(bot_state, state_path, last_alert_ts=alerts)
        notifier.send(f"RESTOCK: {product.name} is IN STOCK.\n{product.url}", cfg, priority=True)
        return bot_state, False

    notifier.send(f"RESTOCK: {product.name} is IN STOCK. Adding to cart...", cfg, priority=True)
    cart = executor.add_to_cart(page, cfg, product, bot_state)

    if cfg.mode == "B":
        if cart.success:
            notifier.send(
                f"Cart ready: {cart.item_name}\nTotal Rs {cart.total_payable}\n"
                f"Address: {cart.delivery_address}\nOpen Blinkit and tap PAY now.",
                cfg, priority=True)
        else:
            notifier.send(f"Could not cart {product.name}: {cart.error}", cfg, priority=True)
        return bot_state, False

    # Mode C
    chk = executor.checkout(page, cfg, product, cart, bot_state,
                            dry_run=args.dry_run, state_path=state_path)
    # checkout() writes the lock itself, so re-read: a stale in-memory copy would
    # let the next cycle retry a payment whose outcome is unknown.
    bot_state = state.load(state_path)

    if chk.success and chk.dry_run:
        notifier.send(
            f"[DRY RUN] Would have ordered {product.name} x{cart.quantity} "
            f"(Rs {cart.total_payable:.0f}, Cash on Delivery).", cfg)
        return bot_state, False
    if chk.success:
        notifier.send(
            f"ORDER PLACED: {product.name} x{cart.quantity}\nOrder ID: {chk.order_id}\n"
            f"Cash on Delivery: keep Rs {cart.total_payable:.0f} ready for the rider.\n"
            f"Total ordered so far: Rs {bot_state.get('total_spent', 0):.0f}",
            cfg, priority=True)
        return bot_state, True
    notifier.send(f"Checkout FAILED for {product.name}: {chk.error}", cfg, priority=True)
    return bot_state, False


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bot_logger.setup_logger()

    try:
        cfg = config.load_config(args.config, env_path=args.env)
    except config.ConfigError as exc:
        logger.critical("Configuration error: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Override mode if provided on CLI
    if args.mode:
        cfg = dataclasses.replace(cfg, mode=args.mode)

    # CLI sub-commands
    if args.login:
        return run_login_flow(cfg)

    if args.capture:
        return run_capture_flow(cfg)

    if args.export_session or args.import_session:
        return run_session_flow(cfg, export=args.export_session)

    if args.practice:
        return run_practice_flow(cfg, args.practice)

    # Load persistent state
    bot_state = state.load(args.state)
    if bot_state.get("corrupt"):
        msg = f"CRITICAL: State file was corrupt and quarantined at {bot_state.get('corrupt_path')}. Manual check required!"
        logger.critical(msg)
        notifier.send(f"🚨 {msg}", cfg, priority=True)
        return 1

    if state.needs_manual_check(bot_state):
        msg = "CRITICAL: Uncertain state! A previous payment attempt was started but never confirmed. Check Blinkit order history before running."
        logger.critical(msg)
        notifier.send(f"⚠️ {msg}", cfg, priority=True)
        return 1

    if state.all_bought(bot_state, len(cfg.products)) and cfg.safety.stop_after_success:
        logger.info("All %d targets already ordered. Nothing to do.", len(cfg.products))
        return 0

    # Startup greeting & self-test
    mode_desc = f"Mode {cfg.mode}" + (" (DRY RUN)" if args.dry_run else "")
    remaining = [q for q in cfg.products if not state.is_bought(bot_state, q.id)]
    target_lines = "\n".join(f"   - {q.name} (max Rs {q.max_price_inr:.0f})" for q in remaining)
    greeting = (
        f"Blinkit Hot Wheels Bot started\n"
        f"- Watching {len(remaining)} of {len(cfg.products)} target(s):\n{target_lines}\n"
        f"- Delivery: {cfg.delivery.label} ({cfg.delivery.pincode})\n"
        f"- {mode_desc}, cycle ~{cfg.polling.interval_seconds}s"
    )
    if cfg.safety.max_total_spend_inr:
        greeting += (f"\n- Spend cap Rs {cfg.safety.max_total_spend_inr:.0f}"
                     f" (spent so far Rs {bot_state.get('total_spent', 0):.0f})")
    logger.info("Bot started in %s watching %d target(s).", mode_desc, len(remaining))
    # Startup self-test: if no remote channel actually delivers, the bot would
    # watch silently and you would miss the restock. Make that impossible to ignore.
    startup = notifier.send(greeting, cfg)
    if not any(v for k, v in startup.items() if k in ("telegram", "whatsapp")):
        warn = ("ALERT CHANNELS DOWN: the startup message reached no remote channel "
                "(WhatsApp/Telegram). You will NOT get restock alerts on your phone. "
                "Fix the Evolution server or add a Telegram token in .env.")
        logger.error(warn)
        notifier.notify_local(warn)

    # Graceful shutdown handler
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        logger.info("Shutdown signal received (%s). Finishing current cycle...", sig)
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    state_path = args.state
    start_ts = time.time()
    last_heartbeat_ts = start_ts
    last_recycle_ts = start_ts
    last_blind_alert_ts = 0.0
    relay_down = False  # one alert per outage, not one per failed page load

    profile_dir = DEFAULT_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)

    def launch(pw: Any) -> tuple[Any, Any]:
        """Open the persistent context. One profile, one page, reused between checks."""
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            **browser_options(),
        )
        return ctx, ctx.new_page()

    with sync_playwright() as p:
        browser_context, page = launch(p)

        # Import the portable session whenever this profile holds no Blinkit
        # cookies. Testing the cookies rather than "is the directory empty"
        # also covers a profile that exists but cannot be read - which is
        # exactly how a Windows profile looks mounted into a Linux container.
        try:
            has_session = bool(browser_context.cookies("https://blinkit.com"))
        except Exception:
            has_session = False
        if not has_session:
            if import_session(browser_context):
                logger.info("No Blinkit session in profile; restored from %s",
                            DEFAULT_SESSION_FILE)
            else:
                logger.warning(
                    "No Blinkit session in the profile and no usable %s. The bot will "
                    "see every product as unavailable. Run --login then --export-session.",
                    DEFAULT_SESSION_FILE)

        try:
            while running:
                # 1. Inbound Telegram commands. Polled between cycles only, so a
                # command can never interleave with a checkout.
                bot_state, stop_requested = notifier.poll_commands(cfg, bot_state, state_path)
                if stop_requested:
                    logger.info("Stop requested via Telegram command.")
                    break

                if bot_state.get("paused"):
                    time.sleep(10)
                    continue

                # 2. Recycle the browser context periodically to bound memory, but
                # never while something is in stock or a checkout may be in flight.
                if (time.time() - last_recycle_ts >= cfg.reliability.recycle_hours * 3600
                        and bot_state.get("last_status") != "IN_STOCK"):
                    logger.info("Recycling browser context after %.1fh.",
                                cfg.reliability.recycle_hours)
                    try:
                        browser_context.close()
                    except Exception as exc:
                        logger.warning("Error closing context during recycle: %s", exc)
                    browser_context, page = launch(p)
                    last_recycle_ts = time.time()

                # 3. Heartbeat
                now = time.time()
                if now - last_heartbeat_ts >= cfg.reliability.heartbeat_hours * 3600:
                    last_heartbeat_ts = now
                    pending = [q for q in cfg.products if not state.is_bought(bot_state, q.id)]
                    notifier.send(
                        f"Heartbeat: watching {len(pending)} target(s), last check "
                        f"{bot_state.get('last_status', 'n/a')}. Bought "
                        f"{len(bot_state.get('orders') or {})}/{len(cfg.products)}.",
                        cfg,
                    )

                # 4. One pass over every target still outstanding.
                targets = [q for q in cfg.products if not state.is_bought(bot_state, q.id)]
                if not targets:
                    notifier.send(
                        f"All {len(cfg.products)} targets ordered. Total spent Rs "
                        f"{bot_state.get('total_spent', 0):.0f}. Shutting down.",
                        cfg, priority=True,
                    )
                    logger.info("Every target has been ordered. Exiting.")
                    break

                # Spread requests evenly across the cycle so no two page loads land
                # closer together than the politeness floor.
                gap_base = max(1, cfg.polling.interval_seconds // len(targets))
                gap_jitter = cfg.polling.jitter_seconds // len(targets)

                for product in targets:
                    if not running:
                        break
                    now = time.time()
                    try:
                        page.goto(product.url, timeout=60000, wait_until="domcontentloaded")
                    except Exception as exc:
                        # Never check the previous page's DOM: it would report a stale status.
                        logger.warning("Navigation to product %s failed: %s", product.id, exc)
                        cons = bot_state.get("consecutive_errors", 0) + 1
                        bot_state = state.save(bot_state, state_path, consecutive_errors=cons,
                                               last_status="ERROR", last_check_ts=int(now))
                        if not relay_down:
                            relay_down = True
                            notifier.send(
                                ("RELAY OFFLINE: cannot reach Blinkit through the home phone. "
                                 "Check it is on charger + Wi-Fi with Tailscale on. "
                                 if os.environ.get("BROWSER_PROXY") else
                                 "Cannot reach Blinkit (network down?). ")
                                + "Not watching until it is back.", cfg, priority=True)
                        # Fixed 60s, not the growing backoff: a dead relay never reaches
                        # Blinkit, and a 15-min wait after it returns could miss a restock.
                        time.sleep(hardening.next_delay(1))
                        continue
                    if relay_down:
                        relay_down = False
                        notifier.send("Connection to Blinkit is back. Watching again.", cfg)

                    res = checker.check(page, cfg, product)
                    bot_state = state.save(bot_state, state_path,
                                           last_status=res.kind.value, last_check_ts=int(now))
                    hardening.ping_healthcheck(cfg.healthcheck_url)
                    logger.info("[%s] %s %s", product.id, res.kind.value, res.message)

                    if res.kind == CheckResultKind.ERROR:
                        cons = bot_state.get("consecutive_errors", 0) + 1
                        bot_state = state.save(bot_state, state_path, consecutive_errors=cons)
                        if res.error_kind in ("unknown_layout", "login", "blocked"):
                            hardening.save_failure_capture(page, f"{product.id}_{res.error_kind}")
                        if cons == 1 or res.error_kind in ("login", "blocked"):
                            notifier.send(
                                f"Bot warning on {product.name} ({res.error_kind}): {res.message}",
                                cfg)
                        ref_ts = bot_state.get("last_identity_ok_ts") or start_ts
                        if (hardening.is_possibly_blind(ref_ts, now)
                                and now - last_blind_alert_ts > 3600):
                            last_blind_alert_ts = now
                            notifier.send(
                                "Possibly blind: the product-identity check has not passed for "
                                "over an hour. Selectors may have drifted - check logs/capture/.",
                                cfg, priority=True)
                        time.sleep(hardening.next_delay(cons))
                        continue

                    # IN_STOCK or OUT_OF_STOCK is only reachable once the identity
                    # assertion passed, so it doubles as proof we can read the page.
                    bot_state = state.save(bot_state, state_path,
                                           last_identity_ok_ts=int(now), consecutive_errors=0)

                    if res.kind == CheckResultKind.IN_STOCK:
                        bot_state, bought = handle_restock(
                            page, cfg, product, bot_state, args, state_path)
                        if bought:
                            # Start a fresh cycle so two checkouts can never overlap.
                            break

                    time.sleep(hardening.calculate_interval(gap_base, gap_jitter))

        finally:
            logger.info("Closing browser context...")
            browser_context.close()

    logger.info("Bot exited cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
