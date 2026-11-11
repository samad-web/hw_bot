import pytest
from pathlib import Path
from unittest.mock import MagicMock
import executor
from executor import CartResult, validate_cart, checkout
import state
from config import Config, ProductConfig, DeliveryConfig, PollingConfig, PaymentConfig, SafetyConfig, ReliabilityConfig, SelectorsConfig, TelegramConfig, EvolutionConfig


def test_validate_cart_price_ceiling(mock_config: Config, target):
    s = dict(state.DEFAULTS)
    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=250.0,  # exceeds 200
        quantity=1,
        delivery_address="Home - 400001",
        total_payable=270.0,
    )
    valid, reason = validate_cart(cart, mock_config, target, s)
    assert valid is False
    assert "exceeds max_price_inr" in reason


def test_validate_cart_total_order_ceiling(mock_config: Config, target):
    s = dict(state.DEFAULTS)
    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=150.0,
        quantity=1,
        delivery_address="Home - 400001",
        total_payable=350.0,  # exceeds 300
    )
    valid, reason = validate_cart(cart, mock_config, target, s)
    assert valid is False
    assert "exceeds max_order_value_inr" in reason


def test_validate_cart_extra_items_rejected(mock_config: Config, target):
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
    valid, reason = validate_cart(cart, mock_config, target, s)
    assert valid is False
    assert "unexpected items" in reason


def test_validate_cart_address_mismatch(mock_config: Config, target):
    s = dict(state.DEFAULTS)
    cart = CartResult(
        success=True,
        item_name="Hot Wheels Nissan Skyline GT-R",
        unit_price=150.0,
        quantity=1,
        delivery_address="Office - 560001",
        total_payable=200.0,
    )
    valid, reason = validate_cart(cart, mock_config, target, s)
    assert valid is False
    assert "Cart address" in reason


def _good_cart(**kw) -> CartResult:
    base = dict(success=True, item_name="Hot Wheels Nissan Skyline GT-R", unit_price=150.0,
                quantity=1, total_payable=180.0)
    base.update(kw)
    return CartResult(**base)


def _cod_page(cfg, cod_disabled=False, address="Home: 206, 2nd floor, Mumbai 400001"):
    """A page already on the cart, whose checkout reaches a payment page with COD."""
    page = MagicMock()
    body = MagicMock()
    body.text_content.return_value = f"Select Payment Method | Delivery Address | {address} | Pay Now"
    cod = page.frame_locator.return_value.locator.return_value.first
    cod.get_attribute.return_value = "" if cod_disabled else None
    cod.locator.return_value.count.return_value = 0
    pay_loc = MagicMock()
    pay = pay_loc.first
    pay.count.return_value = 1
    pay.get_attribute.return_value = None  # enabled once COD is chosen
    page.locator.side_effect = lambda sel: (
        pay_loc if sel == cfg.selectors.pay_button else body if sel == "body" else MagicMock())
    page.url = "https://blinkit.com/order/12345678"
    return page, pay


def test_checkout_dry_run_never_pays(tmp_path: Path, mock_config: Config, target):
    state_file = tmp_path / "state.json"
    page, pay = _cod_page(mock_config)
    res = checkout(page, mock_config, target, _good_cart(), state.load(state_file),
                   dry_run=True, state_path=str(state_file))
    assert res.success and res.dry_run and res.payment_method == "cod"
    pay.click.assert_not_called()
    on_disk = state.load(state_file)
    assert on_disk["payment_attempt_started"] is None and on_disk["orders"] == {}


def test_checkout_lock_written_before_pay(tmp_path: Path, mock_config: Config, target):
    state_file = tmp_path / "state.json"
    page, pay = _cod_page(mock_config)
    seen = []
    pay.click.side_effect = lambda *a, **k: seen.append(
        state.load(state_file).get("payment_attempt_started"))

    res = checkout(page, mock_config, target, _good_cart(), state.load(state_file),
                   dry_run=False, state_path=str(state_file))

    assert res.success and res.order_id == "12345678" and res.payment_method == "cod"
    assert seen == [target.id], "lock must name this product on disk at the Pay click"
    final = state.load(state_file)
    assert final["orders"][target.id][-1]["order_id"] == "12345678"
    assert final["payment_attempt_started"] is None


def test_cod_unavailable_aborts_without_lock(tmp_path: Path, mock_config: Config, target):
    state_file = tmp_path / "state.json"
    page, pay = _cod_page(mock_config, cod_disabled=True)
    res = checkout(page, mock_config, target, _good_cart(), state.load(state_file),
                   dry_run=False, state_path=str(state_file))
    assert not res.success and "Cash on Delivery" in res.error
    pay.click.assert_not_called()
    assert state.load(state_file)["payment_attempt_started"] is None


def test_wrong_delivery_address_aborts_before_cod(tmp_path: Path, mock_config: Config, target):
    state_file = tmp_path / "state.json"
    page, pay = _cod_page(mock_config, address="Office: 12 MG Road, Chennai 600028")
    res = checkout(page, mock_config, target, _good_cart(), state.load(state_file),
                   dry_run=False, state_path=str(state_file))
    assert not res.success and "address" in res.error.lower()
    page.frame_locator.assert_not_called()
    pay.click.assert_not_called()


def test_missing_pay_button_does_not_write_the_lock(tmp_path: Path, mock_config: Config, target):
    """Regression: a config mistake must fail before the lock, never leave it set."""
    import dataclasses
    cfg = dataclasses.replace(
        mock_config, selectors=dataclasses.replace(mock_config.selectors, pay_button=""))
    state_file = tmp_path / "state.json"
    page = MagicMock()
    res = checkout(page, cfg, target, _good_cart(), dict(state.DEFAULTS),
                   dry_run=False, state_path=str(state_file))
    assert not res.success and "pay_button" in res.error
    page.locator.assert_not_called()
    on_disk = state.load(state_file)
    assert on_disk["payment_attempt_started"] is None
    assert state.can_order(on_disk, target.id, 1)[0] is True


def test_no_confirmation_leaves_uncertain_lock(tmp_path: Path, mock_config: Config, target):
    """Pay clicked but success never seen: the lock stays so the bot never re-orders."""
    state_file = tmp_path / "state.json"
    page, pay = _cod_page(mock_config)

    def wait(sel, **kw):
        if sel == mock_config.selectors.order_confirmation:
            raise TimeoutError("no confirmation")
    page.wait_for_selector.side_effect = wait

    res = checkout(page, mock_config, target, _good_cart(), state.load(state_file),
                   dry_run=False, state_path=str(state_file))
    assert not res.success and "UNCERTAIN" in res.error
    pay.click.assert_called_once()
    on_disk = state.load(state_file)
    assert on_disk["payment_attempt_started"] == target.id
    assert state.can_order(on_disk, target.id, 1)[0] is False


def test_uncertain_state_blocks_a_second_checkout(tmp_path: Path, mock_config: Config, target):
    """After a payment whose outcome is unknown, no retry may happen without a human."""
    s = dict(state.DEFAULTS, payment_attempt_started="999", orders={})
    page = MagicMock()
    res = checkout(page, mock_config, target, _good_cart(), s, dry_run=False,
                   state_path=str(tmp_path / "state.json"))
    assert not res.success and "never confirmed" in res.error
    page.locator.assert_not_called()


def test_one_unit_per_order(mock_config: Config, target):
    """D14: one unit per order; a leftover second unit must be refused, not bought."""
    ok, why = validate_cart(_good_cart(quantity=2, delivery_address="Home - 400001"),
                            mock_config, target, dict(state.DEFAULTS))
    assert not ok and "quantity" in why.lower()


def test_target_quantity_respects_spend_caps(mock_config: Config):
    supra = ProductConfig(id="1454828", name="Supra", max_price_inr=659, quantity=1)
    assert executor.target_quantity(549, supra, mock_config, dict(state.DEFAULTS)) == 0  # 300 cap
    import dataclasses
    cfg = dataclasses.replace(mock_config, payment=PaymentConfig(max_order_value_inr=700))
    assert executor.target_quantity(549, supra, cfg, dict(state.DEFAULTS)) == 1
    spent = dict(state.DEFAULTS, total_spent=300)  # 800 - 300 = 500 left < 549 + fees
    assert executor.target_quantity(549, supra, cfg, spent) == 0
    assert executor.target_quantity(0, supra, cfg, dict(state.DEFAULTS)) == 0


def test_grand_total_parsing():
    assert executor._grand_total("Proceed | ₹352\nTOTAL | Proceed") == 352
    assert executor._grand_total("Grand total ⓘ\n₹1,300\n") == 1300
    assert executor._grand_total("nothing here") == 0


def test_pay_now_still_disabled_aborts_without_lock(tmp_path: Path, mock_config: Config, target):
    """If Pay Now stays disabled, Cash was not really selected: never pay."""
    state_file = tmp_path / "state.json"
    page, pay = _cod_page(mock_config)
    pay.get_attribute.return_value = ""
    res = checkout(page, mock_config, target, _good_cart(), state.load(state_file),
                   dry_run=False, state_path=str(state_file))
    assert not res.success and "disabled" in res.error
    pay.click.assert_not_called()
    assert state.load(state_file)["payment_attempt_started"] is None
