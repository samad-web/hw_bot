"""Configuration loader and validator for the Blinkit Hot Wheels bot.

Reads config.yaml, overlays environment variables (.env), and validates into
frozen dataclasses. Fails fast on misconfiguration.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("hw_bot")

MIN_POLLING_INTERVAL_SECONDS = 20


class ConfigError(ValueError):
    """Raised when configuration validation fails."""
    pass


@dataclass(frozen=True)
class ProductConfig:
    name: str = ""
    url: str = ""
    search_keywords: list[str] = field(default_factory=lambda: ["hot wheels"])
    max_price_inr: float = 0.0
    quantity: int = 1


@dataclass(frozen=True)
class DeliveryConfig:
    label: str = "Home"
    lat: float = 0.0
    lng: float = 0.0
    pincode: str = "000000"


@dataclass(frozen=True)
class PollingConfig:
    interval_seconds: int = 45
    jitter_seconds: int = 15


@dataclass(frozen=True)
class PaymentConfig:
    priority: list[str] = field(default_factory=lambda: ["blinkit_wallet"])
    max_order_value_inr: float = 0.0
    otp_relay_timeout_seconds: int = 120


@dataclass(frozen=True)
class SafetyConfig:
    max_orders_total: int = 1
    stop_after_success: bool = True


@dataclass(frozen=True)
class ReliabilityConfig:
    recycle_hours: float = 6.0
    heartbeat_hours: float = 6.0


@dataclass(frozen=True)
class SelectorsConfig:
    product_title: str = ""
    product_id: str = ""
    add_button: str = ""
    out_of_stock: str = ""
    quantity_stepper: str = ""
    header_address: str = ""
    login_wall: str = ""
    cart_open: str = ""
    cart_items: str = ""
    cart_address: str = ""
    cart_total: str = ""
    checkout_button: str = ""
    payment_methods: str = ""
    wallet_balance: str = ""
    pay_button: str = ""
    otp_input: str = ""
    order_confirmation: str = ""
    order_id: str = ""
    order_history: str = ""


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token.strip() and self.chat_id.strip())


@dataclass(frozen=True)
class EvolutionConfig:
    base_url: str = ""
    instance: str = ""
    apikey: str = ""
    to_number: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(
            self.base_url.strip()
            and self.instance.strip()
            and self.apikey.strip()
            and self.to_number.strip()
        )


@dataclass(frozen=True)
class Config:
    product: ProductConfig
    delivery: DeliveryConfig
    mode: str
    polling: PollingConfig
    payment: PaymentConfig
    safety: SafetyConfig
    reliability: ReliabilityConfig
    selectors: SelectorsConfig
    telegram: TelegramConfig
    evolution: EvolutionConfig
    healthcheck_url: str = ""


def load_env_file(dotenv_path: str | Path = ".env") -> dict[str, str]:
    """Parse a .env file into a dictionary without modifying os.environ."""
    p = Path(dotenv_path)
    if not p.is_file():
        return {}

    env_vars: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            env_vars[key] = val
    return env_vars


def get_env(key: str, env_vars: dict[str, str], default: str = "") -> str:
    """Read a setting from os.environ first, then .env file dictionary, else default."""
    return os.environ.get(key, env_vars.get(key, default))


def load_config(
    config_path: str | Path = "config.yaml",
    env_path: str | Path = ".env",
) -> Config:
    """Load config.yaml, overlay environment secrets, validate and return frozen Config."""
    cp = Path(config_path)
    if not cp.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    with open(cp, "r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML parsing error in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Expected mapping in {config_path}, got {type(raw).__name__}")

    env_vars = load_env_file(env_path)

    # Check for secrets accidentally placed in config.yaml
    for secret_key in ("token", "bot_token", "apikey", "api_key", "password"):
        if secret_key in raw:
            logger.warning(
                "Secret key '%s' found in %s! Secrets should be in .env only.",
                secret_key,
                config_path,
            )

    # Product
    prod_raw = raw.get("product") or {}
    product = ProductConfig(
        name=str(prod_raw.get("name", "")).strip(),
        url=str(prod_raw.get("url", "")).strip(),
        search_keywords=list(prod_raw.get("search_keywords", ["hot wheels"])),
        max_price_inr=float(prod_raw.get("max_price_inr", 0.0)),
        quantity=int(prod_raw.get("quantity", 1)),
    )

    # Delivery
    deliv_raw = raw.get("delivery") or {}
    delivery = DeliveryConfig(
        label=str(deliv_raw.get("label", "Home")).strip(),
        lat=float(deliv_raw.get("lat", 0.0)),
        lng=float(deliv_raw.get("lng", 0.0)),
        pincode=str(deliv_raw.get("pincode", "000000")).strip(),
    )

    # Mode
    mode = str(raw.get("mode", "A")).upper().strip()
    if mode not in {"A", "B", "C"}:
        raise ConfigError(f"Invalid mode '{mode}'. Must be one of 'A', 'B', 'C'.")

    # Polling
    poll_raw = raw.get("polling") or {}
    raw_interval = int(poll_raw.get("interval_seconds", 45))
    if raw_interval < MIN_POLLING_INTERVAL_SECONDS:
        logger.warning(
            "polling.interval_seconds (%d) is below hard floor of %ds. Clamping to %ds.",
            raw_interval,
            MIN_POLLING_INTERVAL_SECONDS,
            MIN_POLLING_INTERVAL_SECONDS,
        )
        interval = MIN_POLLING_INTERVAL_SECONDS
    else:
        interval = raw_interval

    polling = PollingConfig(
        interval_seconds=interval,
        jitter_seconds=int(poll_raw.get("jitter_seconds", 15)),
    )

    # Payment
    pay_raw = raw.get("payment") or {}
    payment = PaymentConfig(
        priority=list(pay_raw.get("priority", ["blinkit_wallet"])),
        max_order_value_inr=float(pay_raw.get("max_order_value_inr", 0.0)),
        otp_relay_timeout_seconds=int(pay_raw.get("otp_relay_timeout_seconds", 120)),
    )

    # Safety
    safe_raw = raw.get("safety") or {}
    safety = SafetyConfig(
        max_orders_total=int(safe_raw.get("max_orders_total", 1)),
        stop_after_success=bool(safe_raw.get("stop_after_success", True)),
    )

    # Reliability
    rel_raw = raw.get("reliability") or {}
    reliability = ReliabilityConfig(
        recycle_hours=float(rel_raw.get("recycle_hours", 6.0)),
        heartbeat_hours=float(rel_raw.get("heartbeat_hours", 6.0)),
    )

    # Selectors
    sel_raw = raw.get("selectors") or {}
    selectors = SelectorsConfig(
        product_title=str(sel_raw.get("product_title", "")).strip(),
        product_id=str(sel_raw.get("product_id", "")).strip(),
        add_button=str(sel_raw.get("add_button", "")).strip(),
        out_of_stock=str(sel_raw.get("out_of_stock", "")).strip(),
        quantity_stepper=str(sel_raw.get("quantity_stepper", "")).strip(),
        header_address=str(sel_raw.get("header_address", "")).strip(),
        login_wall=str(sel_raw.get("login_wall", "")).strip(),
        cart_open=str(sel_raw.get("cart_open", "")).strip(),
        cart_items=str(sel_raw.get("cart_items", "")).strip(),
        cart_address=str(sel_raw.get("cart_address", "")).strip(),
        cart_total=str(sel_raw.get("cart_total", "")).strip(),
        checkout_button=str(sel_raw.get("checkout_button", "")).strip(),
        payment_methods=str(sel_raw.get("payment_methods", "")).strip(),
        wallet_balance=str(sel_raw.get("wallet_balance", "")).strip(),
        pay_button=str(sel_raw.get("pay_button", "")).strip(),
        otp_input=str(sel_raw.get("otp_input", "")).strip(),
        order_confirmation=str(sel_raw.get("order_confirmation", "")).strip(),
        order_id=str(sel_raw.get("order_id", "")).strip(),
        order_history=str(sel_raw.get("order_history", "")).strip(),
    )

    # Telegram
    telegram = TelegramConfig(
        bot_token=get_env("TELEGRAM_BOT_TOKEN", env_vars),
        chat_id=get_env("TELEGRAM_CHAT_ID", env_vars),
    )

    # Evolution API
    evolution = EvolutionConfig(
        base_url=get_env("EVOLUTION_BASE_URL", env_vars),
        instance=get_env("EVOLUTION_INSTANCE", env_vars),
        apikey=get_env("EVOLUTION_APIKEY", env_vars),
        to_number=get_env("EVOLUTION_TO_NUMBER", env_vars),
    )

    # Healthcheck URL
    healthcheck_url = get_env("HEALTHCHECK_URL", env_vars)

    # Fail-fast validation
    if safety.max_orders_total != 1:
        raise ConfigError(
            f"safety.max_orders_total is {safety.max_orders_total}, but only 1 is supported."
        )

    if product.quantity < 1:
        raise ConfigError(f"product.quantity must be >= 1, got {product.quantity}")

    if mode == "C":
        if payment.max_order_value_inr <= 0:
            raise ConfigError(
                "Mode C requires payment.max_order_value_inr > 0 as a hard spend ceiling."
            )
        if product.max_price_inr <= 0:
            raise ConfigError(
                "Mode C requires product.max_price_inr > 0 to prevent purchasing at inflated prices."
            )

    # A bot that cannot alert is useless, and in modes B/C it would spend money
    # with no way to tell you.
    if not telegram.is_configured and not evolution.is_configured:
        raise ConfigError(
            "No notification channel configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, "
            "or all four EVOLUTION_* variables, in .env"
        )

    # Placeholders left in config.yaml silently disable the product-identity gate
    # downstream (checker and executor skip the name match), so refuse to run any
    # mode that can touch the cart until they are replaced.
    if mode in ("B", "C"):
        if not product.url.strip():
            raise ConfigError("product.url must be set in modes B and C")
        if not product.name.strip() or product.name.strip().lower().startswith("hot wheels <"):
            raise ConfigError(
                "product.name is still the config.yaml placeholder. Set the exact product title "
                "as shown on the Blinkit page: it is the identity gate that stops the bot from "
                "ordering the wrong item."
            )
        if delivery.pincode.strip() in ("", "000000"):
            raise ConfigError("delivery.pincode is still the placeholder '000000'")

        required = ["product_title", "header_address", "add_button"]
        missing = [n for n in required if not getattr(selectors, n).strip()]
        if missing:
            raise ConfigError(
                "These selectors are not filled in: " + ", ".join(missing) + ". Run "
                "'python main.py --capture' against a logged-in profile and copy the real "
                "selectors into config.yaml. Capture 'add_button' from any in-stock product "
                "page: the Add control is the same markup site-wide."
            )
        if not selectors.out_of_stock.strip():
            logger.warning(
                "selectors.out_of_stock is empty: the bot can detect a restock but will report "
                "ERROR instead of OUT_OF_STOCK while the item is unavailable."
            )

    if mode == "C":
        missing_c = [
            n for n in ("checkout_button", "pay_button", "order_confirmation")
            if not getattr(selectors, n).strip()
        ]
        if missing_c:
            raise ConfigError(
                "Mode C requires these selectors: " + ", ".join(missing_c)
                + ". Without them the bot can reach payment but cannot confirm the outcome."
            )

    return Config(
        product=product,
        delivery=delivery,
        mode=mode,
        polling=polling,
        payment=payment,
        safety=safety,
        reliability=reliability,
        selectors=selectors,
        telegram=telegram,
        evolution=evolution,
        healthcheck_url=healthcheck_url,
    )
