import pytest
from pathlib import Path
from unittest.mock import MagicMock
import executor
from executor import CartResult, validate_cart, checkout
import state
from config import Config, ProductConfig, DeliveryConfig, PollingConfig, PaymentConfig, SafetyConfig, ReliabilityConfig, SelectorsConfig, TelegramConfig, EvolutionConfig


@pytest.fixture
def mock_config() -> Config:
    return Config(
        product=ProductConfig(
            name="Hot Wheels Nissan Skyline GT-R",
            max_price_inr=200.0,
            quantity=1,
        ),
        delivery=DeliveryConfig(
            label="Home",
            pincode="400001",
        ),
        mode="C",
        polling=PollingConfig(),
        payment=PaymentConfig(
            priority=["blinkit_wallet"],
            max_order_value_inr=300.0,
        ),
        safety=SafetyConfig(max_orders_total=1),
        reliability=ReliabilityConfig(),
        selectors=SelectorsConfig(
            checkout_button="button.checkout-btn",
            wallet_balance="span.wallet-bal",
            pay_button="button.pay-btn",
            order_confirmation="div.confirmation",
            order_id="span.order-id",
        ),
        telegram=TelegramConfig(),
        evolution=EvolutionConfig(),
    )


def test_validate_cart_price_ceiling(mock_config: Config):
    s = dict(state.DEFAULTS)
    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=250.0,  # exceeds 200
        quantity=1,
        delivery_address="Home - 400001",
        total_payable=270.0,
    )
    valid, reason = validate_cart(cart, mock_config, s)
    assert valid is False
    assert "exceeds max_price_inr" in reason


def test_validate_cart_total_order_ceiling(mock_config: Config):
    s = dict(state.DEFAULTS)
    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=150.0,
        quantity=1,
        delivery_address="Home - 400001",
        total_payable=350.0,  # exceeds 300
    )
    valid, reason = validate_cart(cart, mock_config, s)
    assert valid is False
    assert "exceeds max_order_value_inr" in reason


def test_validate_cart_extra_items_rejected(mock_config: Config):
    s = dict(state.DEFAULTS)
    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=150.0,
        quantity=1,
        delivery_address="Home - 400001",
        total_payable=200.0,
        has_extra_items=True,  # Foreign items in cart!
    )
    valid, reason = validate_cart(cart, mock_config, s)
    assert valid is False
    assert "unexpected items" in reason


def test_validate_cart_address_mismatch(mock_config: Config):
    s = dict(state.DEFAULTS)
    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=150.0,
        quantity=1,
        delivery_address="Office - 560001",
        total_payable=200.0,
    )
    valid, reason = validate_cart(cart, mock_config, s)
    assert valid is False
    assert "Cart address" in reason


def test_checkout_dry_run_never_pays(tmp_path: Path, mock_config: Config):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)

    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=150.0,
        quantity=1,
        delivery_address="Home - 400001",
        total_payable=180.0,
    )

    mock_page = MagicMock()
    mock_wallet = MagicMock()
    mock_wallet.inner_text.return_value = "₹500.00"
    mock_page.query_selector.return_value = mock_wallet

    res = checkout(mock_page, mock_config, cart, s, dry_run=True, state_path=str(state_file))
    assert res.success is True
    assert res.dry_run is True

    # Lock must NOT have been written
    s_loaded = state.load(state_file)
    assert s_loaded["payment_attempt_started"] is False
    assert s_loaded["order_placed"] is False
    # Pay button must not have been clicked
    assert mock_page.click.call_count == 1  # Only clicked checkout button


def test_checkout_lock_written_before_pay(tmp_path: Path, mock_config: Config):
    state_file = tmp_path / "state.json"
    s = state.load(state_file)

    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=150.0,
        quantity=1,
        delivery_address="Home - 400001",
        total_payable=180.0,
    )

    mock_page = MagicMock()
    mock_wallet = MagicMock()
    mock_wallet.inner_text.return_value = "₹500.00"
    mock_order_id = MagicMock()
    mock_order_id.inner_text.return_value = "ORD-TEST-999"

    def mock_query(sel):
        if sel == "span.wallet-bal":
            return mock_wallet
        if sel == "span.order-id":
            return mock_order_id
        return MagicMock()

    mock_page.query_selector.side_effect = mock_query

    # Track when payment_attempt_started was set
    observed_lock_during_pay = []

    def mock_click(sel):
        if sel == "button.pay-btn":
            # Check state file on disk right when pay is clicked
            cur = state.load(state_file)
            observed_lock_during_pay.append(cur.get("payment_attempt_started"))

    mock_page.click.side_effect = mock_click

    res = checkout(mock_page, mock_config, cart, s, dry_run=False, state_path=str(state_file))
    assert res.success is True
    assert res.order_id == "ORD-TEST-999"

    # Crucial assertion: lock was True on disk when pay was clicked!
    assert observed_lock_during_pay == [True]

    # After completion: order_placed is True
    final_s = state.load(state_file)
    assert final_s["order_placed"] is True
    assert final_s["order_id"] == "ORD-TEST-999"


def _good_cart() -> CartResult:
    return CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=150.0,
        quantity=1,
        delivery_address="Home - 400001",
        total_payable=180.0,
    )


def test_missing_pay_button_does_not_write_the_lock(tmp_path: Path, mock_config: Config):
    """Regression: the lock was written before the pay_button selector was checked,
    so a config mistake left the bot in the uncertain state and it refused to start."""
    import dataclasses

    cfg = dataclasses.replace(
        mock_config,
        selectors=dataclasses.replace(mock_config.selectors, pay_button=""),
    )
    state_file = tmp_path / "state.json"
    s = dict(state.DEFAULTS)

    page = MagicMock()
    page.query_selector.return_value = None  # no wallet balance element -> method still selected

    res = checkout(page, cfg, _good_cart(), s, dry_run=False, state_path=str(state_file))

    assert res.success is False
    assert "pay_button" in res.error
    page.click.assert_called_once()  # only the checkout button, never pay
    on_disk = state.load(state_file)
    assert on_disk["payment_attempt_started"] is False
    assert state.can_order(on_disk, 1)[0] is True


def test_uncertain_state_blocks_a_second_checkout(tmp_path: Path, mock_config: Config):
    """After a payment whose outcome is unknown, no retry may happen without a human."""
    s = dict(state.DEFAULTS, payment_attempt_started=True, order_placed=False)
    page = MagicMock()

    res = checkout(page, mock_config, _good_cart(), s, dry_run=False,
                   state_path=str(tmp_path / "state.json"))

    assert res.success is False
    assert "never confirmed" in res.error
    page.click.assert_not_called()
