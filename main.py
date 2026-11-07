"""Blinkit Hot Wheels Restock Bot - Main entry point and scheduler loop.

Watches target product availability 24/7, handles alerts and remote commands,
and executes cart/checkout actions according to configured mode and safety rules.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import signal
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Blinkit Hot Wheels Restock Bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--state", default=state.DEFAULT_PATH, help="Path to state.json")
    parser.add_argument("--mode", choices=["A", "B", "C"], help="Override operating mode")
    parser.add_argument("--dry-run", action="store_true", help="Run without executing pay click")
    parser.add_argument("--login", action="store_true", help="Open headful browser to log in locally and save session")
    parser.add_argument("--capture", action="store_true", help="Capture HTML & screenshot of product page and exit")
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
            headless=False,
            viewport={"width": 412, "height": 915},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
            ),
        )
        page = context.new_page()
        target_url = cfg.product.url or "https://blinkit.com"
        try:
            page.goto(target_url)
        except Exception as e:
            logger.warning("Initial navigation warning: %s", e)

        try:
            input("Press Enter here once you have logged in and verified your delivery address...")
        except (KeyboardInterrupt, EOFError):
            pass

        context.close()

    print("\n✅ Session saved to profile directory! You can now copy 'profile/' to your VPS.")
    return 0


def run_capture_flow(cfg: Config, profile_dir: Path = DEFAULT_PROFILE_DIR) -> int:
    """Load product page headless, dump HTML and screenshot to logs/capture/, and exit."""
    logger.info("Running capture flow for %s...", cfg.product.url)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            viewport={"width": 412, "height": 915},
        )
        page = context.new_page()
        target_url = cfg.product.url or "https://blinkit.com"
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        cap_dir = hardening.save_failure_capture(page, "manual_capture")
        context.close()

    if cap_dir:
        print(f"✅ HTML and screenshot captured to: {cap_dir}")
        return 0
    else:
        print("❌ Failed to save capture.")
        return 1


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

    if bot_state.get("order_placed") and cfg.safety.stop_after_success:
        logger.info("Single-order lock active: order already placed (%s). Exiting.", bot_state.get("order_id"))
        return 0

    # Startup greeting & self-test
    mode_desc = f"Mode {cfg.mode}" + (" (DRY RUN)" if args.dry_run else "")
    greeting = (
        f"🤖 *Blinkit Hot Wheels Bot Started*\n"
        f"• Target: {cfg.product.name or 'Configured Item'}\n"
        f"• Delivery: {cfg.delivery.label} ({cfg.delivery.pincode})\n"
        f"• Operating Mode: {mode_desc}\n"
        f"• Polling Interval: ~{cfg.polling.interval_seconds}s"
    )
    logger.info("Bot started in %s. Polling target every ~%ds.", mode_desc, cfg.polling.interval_seconds)
    notifier.send(greeting, cfg)

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

    profile_dir = DEFAULT_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)

    def launch(pw: Any) -> tuple[Any, Any]:
        """Open the persistent context. One profile, one page, reused between checks."""
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            viewport={"width": 412, "height": 915},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
            ),
        )
        return ctx, ctx.new_page()

    with sync_playwright() as p:
        browser_context, page = launch(p)

        try:
            while running:
                # 1. Inbound Telegram command polling
                bot_state, stop_requested = notifier.poll_commands(cfg, bot_state, state_path)
                if stop_requested:
                    logger.info("Stop requested via Telegram command.")
                    break

                # 2. Check if paused
                if bot_state.get("paused"):
                    logger.debug("Bot is paused. Sleeping...")
                    time.sleep(10)
                    continue

                # 2b. Recycle the browser context periodically to bound memory, but
                # never while the item is in stock or a checkout may be in flight.
                if (time.time() - last_recycle_ts >= cfg.reliability.recycle_hours * 3600
                        and bot_state.get("last_status") != "IN_STOCK"):
                    logger.info("Recycling browser context after %.1fh.", cfg.reliability.recycle_hours)
                    try:
                        browser_context.close()
                    except Exception as exc:
                        logger.warning("Error closing context during recycle: %s", exc)
                    browser_context, page = launch(p)
                    last_recycle_ts = time.time()

                # 3. Heartbeat check
                now = time.time()
                if now - last_heartbeat_ts >= cfg.reliability.heartbeat_hours * 3600:
                    last_heartbeat_ts = now
                    notifier.send(
                        f"💓 Heartbeat: Bot is actively watching {cfg.product.name}. "
                        f"Status: {bot_state.get('last_status', 'OK')}",
                        cfg,
                    )

                # 4. Availability check. The page MUST be re-fetched every iteration:
                # a product page does not flip to "Add" on its own, so re-reading a
                # stale DOM would mean never seeing the restock.
                target_url = cfg.product.url
                try:
                    if target_url:
                        page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
                    else:
                        page.reload(timeout=30000, wait_until="domcontentloaded")
                except Exception as exc:
                    logger.warning("Page navigation failed: %s", exc)

                res = checker.check(page, cfg)
                bot_state = state.save(
                    bot_state, state_path,
                    last_status=res.kind.value,
                    last_check_ts=int(now),
                )
                hardening.ping_healthcheck(cfg.healthcheck_url)

                # A verdict of IN_STOCK or OUT_OF_STOCK is only reachable once the
                # identity assertion has passed, so it doubles as proof the bot can
                # still read the page. Shout if that has not happened in an hour.
                if res.kind in (CheckResultKind.IN_STOCK, CheckResultKind.OUT_OF_STOCK):
                    bot_state = state.save(bot_state, state_path, last_identity_ok_ts=int(now))
                else:
                    ref_ts = bot_state.get("last_identity_ok_ts") or start_ts
                    if hardening.is_possibly_blind(ref_ts, now) and now - last_blind_alert_ts > 3600:
                        last_blind_alert_ts = now
                        notifier.send(
                            "Possibly blind: the product-identity check has not passed for over "
                            "an hour. Selectors may have drifted - check logs/capture/.",
                            cfg,
                            priority=True,
                        )

                if res.kind == CheckResultKind.IN_STOCK:
                    bot_state = state.save(bot_state, state_path, consecutive_errors=0)
                    logger.info("RESTOCK DETECTED! %s", res.message)

                    # Mode A: Notify only
                    if cfg.mode == "A":
                        # Mute window lives in state so a restart cannot re-spam.
                        if now - bot_state.get("last_alert_ts", 0) > 600:
                            bot_state = state.save(bot_state, state_path, last_alert_ts=int(now))
                            notifier.send(
                                f"🚨 *RESTOCK ALERT!*\n"
                                f"*{cfg.product.name}* is IN STOCK!\n"
                                f"Order now: {cfg.product.url}",
                                cfg,
                                priority=True,
                            )

                    # Mode B: Cart + confirm
                    elif cfg.mode == "B":
                        notifier.send(f"🚨 *RESTOCK ALERT!* Adding to cart...", cfg, priority=True)
                        cart_res = executor.add_to_cart(page, cfg)
                        if cart_res.success:
                            notifier.send(
                                f"🛒 *Item added to cart!*\n"
                                f"• Item: {cart_res.item_name}\n"
                                f"• Total: ₹{cart_res.total_payable}\n"
                                f"• Address: {cart_res.delivery_address}\n"
                                f"👉 Open Blinkit and tap PAY to complete order!",
                                cfg,
                                priority=True,
                            )
                        else:
                            notifier.send(f"⚠️ Cart addition failed: {cart_res.error}", cfg)

                    # Mode C: Full auto-order
                    elif cfg.mode == "C":
                        notifier.send(f"🚨 *RESTOCK ALERT!* Starting automated checkout...", cfg, priority=True)
                        cart_res = executor.add_to_cart(page, cfg)
                        chk_res = executor.checkout(
                            page, cfg, cart_res, bot_state,
                            dry_run=args.dry_run,
                            state_path=state_path,
                        )
                        # checkout() writes the lock itself, so re-read from disk:
                        # a stale in-memory copy would let the next iteration retry
                        # a payment whose outcome is unknown.
                        bot_state = state.load(state_path)
                        if chk_res.success:
                            if chk_res.dry_run:
                                notifier.send(
                                    f"✅ [DRY RUN] Order simulated successfully! Method: {chk_res.payment_method}",
                                    cfg,
                                )
                            else:
                                notifier.send(
                                    f"🎉 *ORDER PLACED!* Order ID: {chk_res.order_id}\nPayment: {chk_res.payment_method}",
                                    cfg,
                                    priority=True,
                                )
                                if cfg.safety.stop_after_success:
                                    logger.info("Order placed and stop_after_success is True. Exiting.")
                                    break
                        else:
                            notifier.send(f"❌ Checkout failed: {chk_res.error}", cfg, priority=True)

                elif res.kind == CheckResultKind.OUT_OF_STOCK:
                    bot_state = state.save(bot_state, state_path, consecutive_errors=0)
                    logger.debug("Product out of stock. Watching...")

                elif res.kind == CheckResultKind.ERROR:
                    cons_errors = bot_state.get("consecutive_errors", 0) + 1
                    bot_state = state.save(bot_state, state_path, consecutive_errors=cons_errors)
                    logger.warning("Check returned error (%s): %s", res.error_kind, res.message)

                    # Capture layout on unknown layout or block
                    if res.error_kind in ("unknown_layout", "login", "blocked"):
                        hardening.save_failure_capture(page, res.error_kind or "error")

                    if cons_errors == 1 or res.error_kind in ("login", "blocked"):
                        notifier.send(f"⚠️ Bot warning ({res.error_kind}): {res.message}", cfg)

                    delay = hardening.next_delay(cons_errors)
                    logger.info("Backing off for %ds due to errors (%d consecutive)", delay, cons_errors)
                    time.sleep(delay)
                    continue

                # Sleep standard jittered interval
                sleep_sec = hardening.calculate_interval(cfg.polling.interval_seconds, cfg.polling.jitter_seconds)
                time.sleep(sleep_sec)

        finally:
            logger.info("Closing browser context...")
            browser_context.close()

    logger.info("Bot exited cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
