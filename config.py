"""Configuration loader and validator for the Blinkit Hot Wheels bot.

Reads config.yaml, overlays environment variables (.env), and validates into
frozen dataclasses. Fails fast on misconfiguration.
"""

from __future__ import annotations

import logging
import os
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("hw_bot")

MIN_POLLING_INTERVAL_SECONDS = 20


MODE_C_SELECTORS = (
    "bar_price", "cart_items", "cart_line_title", "quantity_stepper", "cart_minus", "checkout_button", "proceed_to_pay", "payment_frame", "cod_option",
    "pay_button",
)


class ConfigError(ValueError):
    """Raised when configuration validation fails."""
    pass


@dataclass(frozen=True)
class ProductConfig:
    """One watch target. ``id`` is the Blinkit prid: the stable key for state,
    since Blinkit resolves product pages by prid and the URL slug is cosmetic."""
    id: str = ""
    name: str = ""
    url: str = ""
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
    # Hard ceiling on the SUM of every order this bot places. The last line of
    # defence if a per-order gate is wrong.
    max_total_spend_inr: float = 0.0


@dataclass(frozen=True)
class ReliabilityConfig:
    recycle_hours: float = 6.0
    heartbeat_hours: float = 6.0


@dataclass(frozen=True)
class SelectorsConfig:
    product_title: str = ""
    product_id: str = ""
    add_button: str = ""
    dismiss_modal: str = ""
    bar_price: str = ""
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
    # Web cart + Cash-on-Delivery checkout (F11).
    cart_line_title: str = ""
    cart_minus: str = ""
    proceed_to_pay: str = ""
    payment_frame: str = ""
    cod_option: str = ""


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
    products: tuple[ProductConfig, ...]
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

    # Products (watch targets)
    prods_raw = raw.get("products")
    if not isinstance(prods_raw, list) or not prods_raw:
        raise ConfigError("config.yaml must define a non-empty 'products:' list")
    products = tuple(
        ProductConfig(
            id=str(p.get("id", "")).strip(),
            name=str(p.get("name", "")).strip(),
            url=str(p.get("url", "")).strip(),
            max_price_inr=float(p.get("max_price_inr", 0.0)),
            quantity=int(p.get("quantity", 1)),
        )
        for p in prods_raw
        if isinstance(p, dict)
    )
    if len(products) != len(prods_raw):
        raise ConfigError("every entry under 'products:' must be a mapping")

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
    # The floor is per HTTP request, and one cycle fetches a page per target,
    # so it scales with the number of products.
    floor = MIN_POLLING_INTERVAL_SECONDS * len(products)
    raw_interval = int(poll_raw.get("interval_seconds", 45))
    if raw_interval < floor:
        logger.warning(
            "polling.interval_seconds (%d) is below the %ds floor for %d target(s). Clamping to %ds.",
            raw_interval, floor, len(products), floor,
        )
        interval = floor
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
        max_total_spend_inr=float(safe_raw.get("max_total_spend_inr", 0.0)),
    )

    # Reliability
    rel_raw = raw.get("reliability") or {}
    reliability = ReliabilityConfig(
        recycle_hours=float(rel_raw.get("recycle_hours", 6.0)),
        heartbeat_hours=float(rel_raw.get("heartbeat_hours", 6.0)),
    )

    # Selectors
    sel_raw = raw.get("selectors") or {}
    selectors = SelectorsConfig(**{
        f.name: str(sel_raw.get(f.name) or "").strip() for f in dataclasses.fields(SelectorsConfig)
    })

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
    ids = [p.id for p in products]
    for p in products:
        if not p.id:
            raise ConfigError(
                f"product '{p.name or p.url or '?'}' is missing its 'id' (the Blinkit prid "
                "from the product URL). It is the key the single-order lock is stored under."
            )
        if ids.count(p.id) > 1:
            raise ConfigError(f"duplicate product id '{p.id}' under products:")
        if p.quantity < 1:
            raise ConfigError(f"product {p.id}: quantity must be >= 1, got {p.quantity}")

    if safety.max_orders_total != len(products):
        raise ConfigError(
            f"safety.max_orders_total ({safety.max_orders_total}) must equal the number of "
            f"products ({len(products)}). Each target is bought at most once."
        )

    if mode == "C":
        if payment.max_order_value_inr <= 0:
            raise ConfigError(
                "Mode C requires payment.max_order_value_inr > 0 as the per-order spend ceiling."
            )
        if safety.max_total_spend_inr <= 0:
            raise ConfigError(
                "Mode C requires safety.max_total_spend_inr > 0 as the ceiling across ALL orders."
            )
        for p in products:
            if p.max_price_inr <= 0:
                raise ConfigError(
                    f"Mode C requires max_price_inr > 0 for product {p.id} "
                    "to prevent purchasing at an inflated price."
                )
        cheapest = min(p.max_price_inr for p in products)
        if safety.max_total_spend_inr < cheapest:
            raise ConfigError(
                f"safety.max_total_spend_inr ({safety.max_total_spend_inr:.0f}) is below the "
                f"cheapest target's ceiling ({cheapest:.0f}); no order could ever pass."
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
        for p in products:
            if not p.url:
                raise ConfigError(f"product {p.id}: url must be set in modes B and C")
            if not p.name or p.name.lower().startswith("hot wheels <"):
                raise ConfigError(
                    f"product {p.id}: name is still the config.yaml placeholder. Set the exact "
                    "product title as shown on the Blinkit page: it is the identity gate that "
                    "stops the bot from ordering the wrong item."
                )
        if delivery.pincode in ("", "000000"):
            raise ConfigError("delivery.pincode is still the placeholder '000000'")

        missing = [n for n in ("product_title", "header_address", "add_button")
                   if not getattr(selectors, n).strip()]
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
                "ERROR instead of OUT_OF_STOCK while an item is unavailable."
            )

    if mode == "C":
        # Web checkout offers no Blinkit Money; Cash on Delivery is the only
        # payment that needs no human (D9).
        if payment.priority != ["cod"]:
            raise ConfigError("Mode C supports only payment.priority: [cod] (web checkout)")
        missing_c = [n for n in MODE_C_SELECTORS if not getattr(selectors, n).strip()]
        if missing_c:
            raise ConfigError("Mode C requires these selectors: " + ", ".join(missing_c))

    return Config(
        products=products,
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
