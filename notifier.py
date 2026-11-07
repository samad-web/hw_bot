"""Notifier module for Telegram and WhatsApp (Evolution API / Evolution GO).

Handles outbound alerts and inbound Telegram remote commands.
Telegram is the sole inbound command channel to avoid exposing webhook endpoints.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests
import state
from config import Config

logger = logging.getLogger("hw_bot")

REQUEST_TIMEOUT_SECONDS = 5.0
MAX_RETRIES = 2


def send_telegram(text: str, cfg: Config) -> bool:
    """Send an outbound alert via Telegram Bot API."""
    if not cfg.telegram.is_configured:
        return False

    url = f"https://api.telegram.org/bot{cfg.telegram.bot_token}/sendMessage"
    payload = {
        "chat_id": cfg.telegram.chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 200 and resp.json().get("ok"):
                return True
            # A stray '*' or '_' in a product name makes Telegram reject the whole
            # message. The alert matters far more than the formatting.
            if resp.status_code == 400 and "parse_mode" in payload:
                payload.pop("parse_mode")
                logger.warning("Telegram rejected Markdown formatting; retrying as plain text.")
                continue
            logger.warning(
                "Telegram API error (attempt %d/%d): status %d, body: %s",
                attempt,
                MAX_RETRIES,
                resp.status_code,
                resp.text,
            )
        except requests.RequestException as exc:
            logger.warning("Telegram network error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)

    return False


def get_whatsapp_status(cfg: Config) -> dict[str, Any]:
    """Check connection status of the Evolution WhatsApp instance."""
    if not cfg.evolution.is_configured:
        return {"configured": False, "connected": False}

    base_url = cfg.evolution.base_url.rstrip("/")
    headers = {"apikey": cfg.evolution.apikey}

    for path in ["/instance/status", f"/instance/connectionState/{cfg.evolution.instance}"]:
        try:
            resp = requests.get(f"{base_url}{path}", headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return {
                    "configured": True,
                    "connected": bool(data.get("Connected") or data.get("state") == "open"),
                    "name": data.get("Name", cfg.evolution.instance),
                    "details": data,
                }
        except Exception as exc:
            logger.debug("WhatsApp status probe error (%s): %s", path, exc)

    return {"configured": True, "connected": False}


def send_whatsapp(text: str, cfg: Config) -> bool:
    """Send an outbound alert via Evolution API (supports both Evolution GO and Node API)."""
    if not cfg.evolution.is_configured:
        return False

    base_url = cfg.evolution.base_url.rstrip("/")
    clean_number = re.sub(r"[^\d]", "", cfg.evolution.to_number)

    headers = {
        "apikey": cfg.evolution.apikey,
        "Content-Type": "application/json",
    }
    payload = {
        "number": clean_number,
        "text": text,
    }

    endpoints = [
        f"{base_url}/send/text",
        f"{base_url}/message/sendText/{cfg.evolution.instance}",
    ]

    for url in endpoints:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
                if resp.status_code in (200, 201):
                    data = resp.json() if resp.content else {}
                    if data.get("error"):
                        logger.warning("Evolution API error message from %s: %s", url, data.get("error"))
                        break
                    return True
                elif resp.status_code == 404:
                    break
                else:
                    logger.warning(
                        "Evolution API error (%s, attempt %d/%d): status %d, body: %s",
                        url,
                        attempt,
                        MAX_RETRIES,
                        resp.status_code,
                        resp.text,
                    )
            except requests.RequestException as exc:
                logger.warning(
                    "Evolution API network error (%s, attempt %d/%d): %s",
                    url,
                    attempt,
                    MAX_RETRIES,
                    exc,
                )

    return False


def send(text: str, cfg: Config, priority: bool = False) -> dict[str, bool]:
    """Fan-out notification to all configured channels."""
    results: dict[str, bool] = {}

    if cfg.telegram.is_configured:
        results["telegram"] = send_telegram(text, cfg)

    if cfg.evolution.is_configured:
        results["whatsapp"] = send_whatsapp(text, cfg)

    return results


def handle_command(
    cmd_text: str,
    cfg: Config,
    current_state: dict[str, Any],
    state_path: str = state.DEFAULT_PATH,
) -> tuple[str, dict[str, Any], bool]:
    """Process a single command string from an authenticated chat.

    Returns:
        (reply_message, updated_state, should_stop)
    """
    parts = cmd_text.strip().split()
    if not parts:
        return "", current_state, False

    command = parts[0].lower()
    args = parts[1:]

    if command == "/status":
        can_ord, ord_reason = state.can_order(current_state, cfg.safety.max_orders_total)
        wa_status = get_whatsapp_status(cfg)
        wa_desc = "Connected" if wa_status.get("connected") else ("Configured (Offline)" if wa_status.get("configured") else "Not configured")

        status_msg = (
            f"🤖 *Bot Status*\n"
            f"• Mode: {current_state.get('mode') or cfg.mode}\n"
            f"• Paused: {current_state.get('paused', False)}\n"
            f"• Can order: {can_ord} ({ord_reason if not can_ord else 'Ready'})\n"
            f"• Order placed: {current_state.get('order_placed', False)}\n"
            f"• Order ID: {current_state.get('order_id') or 'None'}\n"
            f"• Last check: {current_state.get('last_status', 'Never')}\n"
            f"• Consecutive errors: {current_state.get('consecutive_errors', 0)}\n"
            f"• Telegram: Connected\n"
            f"• WhatsApp: {wa_desc}"
        )
        return status_msg, current_state, False

    elif command == "/pause":
        updated = state.save(current_state, state_path, paused=True)
        return "⏸️ Bot checks paused. Send /resume to restart watching.", updated, False

    elif command == "/resume":
        updated = state.save(current_state, state_path, paused=False)
        return "▶️ Bot checks resumed. Watching for restock.", updated, False

    elif command == "/stop":
        return "🛑 Stopping bot gracefully...", current_state, True

    elif command == "/mode":
        if not args or args[0].upper() not in {"A", "B", "C"}:
            return "Usage: /mode <A|B|C>", current_state, False
        new_mode = args[0].upper()
        if new_mode == "C" and (cfg.payment.max_order_value_inr <= 0 or cfg.product.max_price_inr <= 0):
            return "❌ Cannot switch to Mode C: price ceilings not configured in config.yaml.", current_state, False
        updated = state.save(current_state, state_path, mode=new_mode)
        reply = f"✅ Switched to Mode {new_mode}."
        if current_state.get("order_placed"):
            reply += " (Note: Lock is active; order was already placed)."
        return reply, updated, False

    elif command == "/otp":
        if not args:
            return "Usage: /otp <code>", current_state, False
        code = args[0].strip()
        if not re.match(r"^\d{4,8}$", code):
            return "❌ Invalid OTP format. Please provide 4 to 8 digits.", current_state, False
        # Deliberately NOT stored: an OTP must never be written to disk. The card
        # OTP relay is not implemented in this build (payment priority is the
        # Blinkit wallet), so nothing is waiting to consume this code.
        return (
            "⚠️ Card OTP relay is not implemented in this build - payment uses the Blinkit "
            "wallet. Your code was not stored anywhere. If a card OTP is required, complete "
            "the payment manually in the app.",
            current_state,
            False,
        )

    else:
        return (
            "Available commands:\n"
            "/status - View current status\n"
            "/pause - Pause watching\n"
            "/resume - Resume watching\n"
            "/mode <A|B|C> - Switch operating mode\n"
            "/otp <code> - Submit OTP for card checkout\n"
            "/stop - Stop the bot",
            current_state,
            False,
        )


def poll_commands(
    cfg: Config,
    current_state: dict[str, Any],
    state_path: str = state.DEFAULT_PATH,
) -> tuple[dict[str, Any], bool]:
    """Poll Telegram getUpdates for new commands from the authorized chat.

    Returns:
        (updated_state, should_stop)
    """
    if not cfg.telegram.is_configured:
        return current_state, False

    offset = current_state.get("telegram_offset", 0)
    url = f"https://api.telegram.org/bot{cfg.telegram.bot_token}/getUpdates"
    params = {"offset": offset, "timeout": 0}

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.warning("Telegram getUpdates returned status %d", resp.status_code)
            return current_state, False
        data = resp.json()
        if not data.get("ok"):
            return current_state, False
    except requests.RequestException as exc:
        logger.warning("Telegram getUpdates error: %s", exc)
        return current_state, False

    updates = data.get("result", [])
    should_stop = False

    for update in updates:
        update_id = update.get("update_id", offset)
        offset = max(offset, update_id + 1)
        current_state = state.save(current_state, state_path, telegram_offset=offset)

        message = update.get("message") or update.get("channel_post")
        if not message:
            continue

        chat_id = str(message.get("chat", {}).get("id", ""))
        configured_chat_id = str(cfg.telegram.chat_id).strip()

        if chat_id != configured_chat_id:
            logger.warning("Ignored command from unauthorized chat ID: %s", chat_id)
            continue

        text = (message.get("text") or "").strip()
        if text.startswith("/"):
            reply, current_state, stop_requested = handle_command(text, cfg, current_state, state_path)
            if stop_requested:
                should_stop = True
            if reply:
                send_telegram(reply, cfg)

    return current_state, should_stop
