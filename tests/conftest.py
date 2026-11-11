"""Shared test fixtures.

One place to build a valid Config, so a schema change is a one-file fix rather
than an edit in every test module.
"""

import pytest

from config import (
    Config, ProductConfig, DeliveryConfig, PollingConfig, PaymentConfig,
    SafetyConfig, ReliabilityConfig, SelectorsConfig, TelegramConfig, EvolutionConfig,
)

# Single target used by the checker/executor/notifier suites.
SKYLINE = ProductConfig(
    id="123",
    name="Hot Wheels Nissan Skyline GT-R",
    url="https://blinkit.com/prn/hot-wheels-gtr/prid/123",
    max_price_inr=200,
    quantity=1,
)

# The two real targets, for multi-product behaviour.
K5 = ProductConfig(
    id="799027",
    name="Hot Wheels 1985 Chevrolet K5 Blazer Die Cast Car",
    url="https://blinkit.com/prn/x/prid/799027",
    max_price_inr=659,
    quantity=1,
)
RAM = ProductConfig(
    id="1416802",
    name="Hot Wheels 23 Ram 1500 Die Cast Car",
    url="https://blinkit.com/prn/x/prid/1416802",
    max_price_inr=215,
    quantity=1,
)

FULL_SELECTORS = SelectorsConfig(
    product_title="h1.p-title",
    header_address="div.h-addr",
    add_button="button.add-btn",
    out_of_stock="div.out-of-stock",
    quantity_stepper="div.stepper",
    login_wall="div.login-modal",
    cart_open="div.cart",
    cart_items="li.cart-item",
    cart_address="div.cart-addr",
    cart_total="div.cart-total",
    checkout_button="button.checkout-btn",
    payment_methods="div.pay-methods",
    wallet_balance="span.wallet-bal",
    pay_button="button.pay-btn",
    order_confirmation="div.confirmation",
    order_id="span.order-id",
    order_history="div.order-history",
    bar_price="div.bar-price",
    cart_line_title="div.line-title",
    cart_minus="div.minus",
    proceed_to_pay="div.proceed-to-pay",
    payment_frame="#payment_widget",
    cod_option="div[title='Cash']",
)


def make_config(**overrides) -> Config:
    """A valid single-target Config; pass keyword overrides for variations."""
    base = dict(
        products=(SKYLINE,),
        delivery=DeliveryConfig(label="Home", lat=19.0, lng=72.0, pincode="400001"),
        mode="A",
        polling=PollingConfig(interval_seconds=60, jitter_seconds=15),
        payment=PaymentConfig(max_order_value_inr=300),
        safety=SafetyConfig(max_orders_total=1, max_total_spend_inr=800),
        reliability=ReliabilityConfig(),
        selectors=FULL_SELECTORS,
        telegram=TelegramConfig(bot_token="test-token", chat_id="12345"),
        evolution=EvolutionConfig(
            base_url="https://evo.example.com",
            instance="test-instance",
            apikey="test-key",
            to_number="919876543210",
        ),
    )
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def base_config() -> Config:
    return make_config()


@pytest.fixture
def mock_config() -> Config:
    return make_config()


@pytest.fixture
def target() -> ProductConfig:
    """The product under test in the single-target fixtures."""
    return SKYLINE


@pytest.fixture
def multi_config() -> Config:
    """Two real targets, as deployed."""
    return make_config(
        products=(K5, RAM),
        safety=SafetyConfig(max_orders_total=2, max_total_spend_inr=800),
        payment=PaymentConfig(max_order_value_inr=700),
    )
