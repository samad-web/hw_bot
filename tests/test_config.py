import pytest
from pathlib import Path
import yaml
from config import load_config, ConfigError, MIN_POLLING_INTERVAL_SECONDS


def create_minimal_config(path: Path, **overrides) -> Path:
    base = {
        "products": [
            {
                "id": "12345",
                "name": "Hot Wheels Nissan Skyline GT-R",
                "url": "https://blinkit.com/prn/hot-wheels-gtr/prid/12345",
                "max_price_inr": 200.0,
                "quantity": 1,
            }
        ],
        "delivery": {
            "label": "Home",
            "lat": 19.0760,
            "lng": 72.8777,
            "pincode": "400001",
        },
        "mode": "A",
        "polling": {
            "interval_seconds": 45,
            "jitter_seconds": 15,
        },
        "payment": {
            "priority": ["cod"],
            "max_order_value_inr": 300.0,
            "otp_relay_timeout_seconds": 120,
        },
        "safety": {
            "max_orders_total": 1,
            "stop_after_success": True,
            "max_total_spend_inr": 800.0,
        },
        "reliability": {
            "recycle_hours": 6,
            "heartbeat_hours": 6,
        },
        "selectors": {
            "product_title": "h1.product-title",
            "add_button": "button.add-btn",
        },
    }
    base.update(overrides)
    path.write_text(yaml.dump(base), encoding="utf-8")
    # A notification channel is mandatory, so every valid fixture needs one.
    env_file = path.parent / ".env"
    if not env_file.exists():
        env_file.write_text(
            "TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_CHAT_ID=12345\n", encoding="utf-8"
        )
    return path


def test_load_valid_config(tmp_path: Path):
    cfg_file = create_minimal_config(tmp_path / "config.yaml")
    cfg = load_config(cfg_file, env_path=tmp_path / ".env")
    assert cfg.products[0].name == "Hot Wheels Nissan Skyline GT-R"
    assert cfg.mode == "A"
    assert cfg.polling.interval_seconds == 45
    assert cfg.safety.max_orders_total == 1


def test_polling_interval_clamped_to_floor(tmp_path: Path):
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml",
        polling={"interval_seconds": 5, "jitter_seconds": 2},
    )
    cfg = load_config(cfg_file, env_path=tmp_path / ".env")
    assert cfg.polling.interval_seconds == MIN_POLLING_INTERVAL_SECONDS


def test_invalid_mode_rejected(tmp_path: Path):
    cfg_file = create_minimal_config(tmp_path / "config.yaml", mode="INVALID")
    with pytest.raises(ConfigError, match="Invalid mode"):
        load_config(cfg_file, env_path=tmp_path / ".env")


def test_mode_c_requires_positive_spend_ceilings(tmp_path: Path):
    # max_order_value_inr == 0 in Mode C
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml",
        mode="C",
        payment={"max_order_value_inr": 0},
    )
    with pytest.raises(ConfigError, match="max_order_value_inr > 0"):
        load_config(cfg_file, env_path=tmp_path / ".env")

    # max_price_inr == 0 in Mode C
    cfg_file2 = create_minimal_config(
        tmp_path / "config.yaml",
        mode="C",
        products=[{"id": "1", "name": "Hot Wheels Nissan Skyline GT-R",
                    "url": "https://blinkit.com/prn/x/prid/1", "max_price_inr": 0}],
        payment={"max_order_value_inr": 500},
    )
    with pytest.raises(ConfigError, match="max_price_inr > 0"):
        load_config(cfg_file2, env_path=tmp_path / ".env")


def test_max_orders_total_is_a_backstop_not_a_restatement(tmp_path: Path):
    """F17: the car list is edited from the web, so max_orders_total became a cap set only
    in config.yaml; it no longer has to equal the sum of per-car max_orders."""
    prod = {"name": "Hot Wheels A", "url": "https://blinkit.com/prn/x/prid/1",
            "max_price_inr": 100.0, "max_orders": 3}
    cfg_file = create_minimal_config(tmp_path / "config.yaml", products=[prod],
                                     safety={"max_orders_total": 2, "max_total_spend_inr": 800.0})
    assert load_config(cfg_file, env_path=tmp_path / ".env").products[0].max_orders == 3
    cfg_file = create_minimal_config(tmp_path / "config.yaml", products=[prod],
                                     safety={"max_orders_total": 0, "max_total_spend_inr": 800.0})
    with pytest.raises(ConfigError, match="max_orders_total must be >= 1"):
        load_config(cfg_file, env_path=tmp_path / ".env")


def test_duplicate_product_id_rejected(tmp_path: Path):
    dup = {"id": "1", "name": "Hot Wheels A", "url": "https://blinkit.com/prn/x/prid/1",
           "max_price_inr": 100.0}
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml",
        products=[dict(dup), dict(dup)],
        safety={"max_orders_total": 2, "max_total_spend_inr": 800.0},
    )
    with pytest.raises(ConfigError, match="duplicate product id"):
        load_config(cfg_file, env_path=tmp_path / ".env")


def test_polling_floor_scales_with_target_count(tmp_path: Path):
    """One cycle fetches a page per target, so the 20s floor is per request."""
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml",
        products=[
            {"id": "1", "name": "A", "url": "https://blinkit.com/prn/x/prid/1", "max_price_inr": 100.0},
            {"id": "2", "name": "B", "url": "https://blinkit.com/prn/x/prid/2", "max_price_inr": 100.0},
            {"id": "3", "name": "C", "url": "https://blinkit.com/prn/x/prid/3", "max_price_inr": 100.0},
        ],
        safety={"max_orders_total": 3, "max_total_spend_inr": 800.0},
        polling={"interval_seconds": 30, "jitter_seconds": 5},
    )
    cfg = load_config(cfg_file, env_path=tmp_path / ".env")
    assert cfg.polling.interval_seconds == 60  # 20s x 3 targets


def test_env_overlay_reads_telegram_and_evolution(tmp_path: Path):
    cfg_file = create_minimal_config(tmp_path / "config.yaml")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=test-token-123\n"
        "TELEGRAM_CHAT_ID=987654\n"
        "EVOLUTION_BASE_URL=https://evo.example.com\n"
        "EVOLUTION_INSTANCE=my-instance\n"
        "EVOLUTION_APIKEY=secret-api-key\n"
        "EVOLUTION_TO_NUMBER=919876543210\n"
        "HEALTHCHECK_URL=https://hc-ping.com/uuid\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file, env_path=env_file)
    assert cfg.telegram.is_configured is True
    assert cfg.telegram.bot_token == "test-token-123"
    assert cfg.telegram.chat_id == "987654"
    assert cfg.evolution.is_configured is True
    assert cfg.evolution.base_url == "https://evo.example.com"
    assert cfg.evolution.to_number == "919876543210"
    assert cfg.healthcheck_url == "https://hc-ping.com/uuid"


def test_requires_at_least_one_notification_channel(tmp_path: Path):
    cfg_file = create_minimal_config(tmp_path / "config.yaml")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="No notification channel"):
        load_config(cfg_file, env_path=tmp_path / ".env")


def test_mode_b_rejects_placeholder_product_name(tmp_path: Path):
    """The placeholder makes checker/executor SKIP the identity gate, so it must
    never reach a mode that can touch the cart."""
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml",
        mode="B",
        products=[{
            "id": "1",
            "name": "Hot Wheels <exact model name>",
            "url": "https://blinkit.com/prn/x/prid/1",
            "max_price_inr": 200.0,
            "quantity": 1,
        }],
    )
    with pytest.raises(ConfigError, match="placeholder"):
        load_config(cfg_file, env_path=tmp_path / ".env")


def test_mode_b_rejects_placeholder_pincode(tmp_path: Path):
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml",
        mode="B",
        delivery={"label": "Home", "lat": 0.0, "lng": 0.0, "pincode": "000000"},
    )
    with pytest.raises(ConfigError, match="pincode"):
        load_config(cfg_file, env_path=tmp_path / ".env")


def test_mode_b_requires_core_selectors(tmp_path: Path):
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml",
        mode="B",
        selectors={"product_title": "h1", "add_button": ""},
    )
    with pytest.raises(ConfigError, match="selectors are not filled in"):
        load_config(cfg_file, env_path=tmp_path / ".env")


def test_mode_c_requires_checkout_selectors(tmp_path: Path):
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml",
        mode="C",
        selectors={
            "product_title": "h1",
            "header_address": ".addr",
            "add_button": "button.add",
            "out_of_stock": ".oos",
        },
    )
    with pytest.raises(ConfigError, match="Mode C requires these selectors"):
        load_config(cfg_file, env_path=tmp_path / ".env")


def test_mode_c_rejects_wallet_payment(tmp_path: Path):
    """F11/D9: web checkout has no Blinkit Money, so Mode C must be COD-only."""
    cfg_file = create_minimal_config(
        tmp_path / "config.yaml", mode="C",
        payment={"priority": ["blinkit_wallet"], "max_order_value_inr": 300.0},
        selectors={"product_title": "h1", "header_address": ".addr",
                   "add_button": "button.add", "out_of_stock": ".oos"},
    )
    with pytest.raises(ConfigError, match=r"only payment.priority: \[cod\]"):
        load_config(cfg_file, env_path=tmp_path / ".env")
