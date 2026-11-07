"""Executor module for cart automation (Mode B) and checkout/payment (Mode C).

Enforces strict pre-checkout validation, safe payment method selection,
and the single-order lock sequence before any payment click.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import checker
import state
from config import Config, ProductConfig

logger = logging.getLogger("hw_bot")


@dataclass(frozen=True)
class CartResult:
    success: bool
    item_name: str = ""
    unit_price: float = 0.0
    quantity: int = 0
    delivery_address: str = ""
    total_payable: float = 0.0
    has_extra_items: bool = False
    missed: bool = False
    error: str = ""


@dataclass(frozen=True)
class CheckoutResult:
    success: bool
    order_id: Optional[str] = None
    dry_run: bool = False
    payment_method: str = ""
    error: str = ""


def _parse_currency(text: str) -> float:
    """Extract numeric currency amount from text (e.g. '₹ 199.00' -> 199.0)."""
    match = re.search(r"[\d,]+(?:\.\d+)?", text.replace(",", ""))
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return 0.0
    return 0.0


def validate_cart(cart: CartResult, cfg: Config, product: ProductConfig,
                  current_state: dict[str, Any]) -> tuple[bool, str]:
    """Perform pre-checkout safety checks. Every rule must pass or checkout aborts."""
    can_ord, reason = state.can_order(
        current_state, product.id, cfg.safety.max_orders_total,
        cfg.safety.max_total_spend_inr, cart.total_payable,
    )
    if not can_ord:
        return False, f"Ordering not permitted: {reason}"

    if not cart.success:
        return False, f"Cart preparation failed: {cart.error}"

    if cart.missed:
        return False, "Item sold out before order could be placed"

    if cart.has_extra_items:
        return False, "Cart contains unexpected items. Refusing to checkout foreign items."

    if cart.quantity != product.quantity:
        return False, f"Cart quantity ({cart.quantity}) does not match expected ({product.quantity})"

    # Price ceilings
    if product.max_price_inr > 0 and cart.unit_price > product.max_price_inr:
        return False, (
            f"Unit price (Rs {cart.unit_price}) exceeds max_price_inr ceiling (Rs {product.max_price_inr}) for {product.id}"
        )

    if cfg.payment.max_order_value_inr > 0 and cart.total_payable > cfg.payment.max_order_value_inr:
        return False, (
            f"Total payable (₹{cart.total_payable}) exceeds max_order_value_inr ceiling (₹{cfg.payment.max_order_value_inr})"
        )

    # Product name match
    expected_name = product.name.strip().lower()
    if expected_name and not expected_name.startswith("hot wheels <"):
        actual_name = cart.item_name.strip().lower()
        if expected_name not in actual_name and actual_name not in expected_name:
            return False, f"Cart item '{cart.item_name}' does not match configured '{product.name}'"

    # Delivery address match
    expected_label = cfg.delivery.label.strip().lower()
    expected_pincode = cfg.delivery.pincode.strip()
    actual_addr = cart.delivery_address.lower()

    matched_addr = False
    if expected_label and expected_label in actual_addr:
        matched_addr = True
    elif expected_pincode and expected_pincode != "000000" and expected_pincode in actual_addr:
        matched_addr = True

    if not matched_addr:
        return False, (
            f"Cart address '{cart.delivery_address}' does not match configured label '{cfg.delivery.label}' "
            f"or pincode '{cfg.delivery.pincode}'"
        )

    return True, ""


def add_to_cart(page: Any, cfg: Config, product: ProductConfig) -> CartResult:
    """Add ``product`` to the cart and read back the values Mode C will validate."""
    selectors = cfg.selectors
    if not selectors.add_button:
        return CartResult(success=False, error="Selector 'add_button' is not configured")

    try:
        # The app-download overlay swallows clicks; clear it before touching
        # anything, not just before reading.
        checker.dismiss_interstitials(page, cfg)

        # Check if button is visible
        if not page.is_visible(selectors.add_button):
            # Check if sold out in the meantime
            if selectors.out_of_stock and page.is_visible(selectors.out_of_stock):
                return CartResult(success=False, missed=True, error="Product sold out before Add click")
            return CartResult(success=False, error="Add button not visible on page")

        # Click Add button
        page.click(selectors.add_button)

        # Wait for stepper or confirmation
        if selectors.quantity_stepper:
            try:
                page.wait_for_selector(selectors.quantity_stepper, timeout=4000)
            except Exception:
                logger.warning("Quantity stepper did not appear immediately after click")

        # Open cart
        if selectors.cart_open and page.is_visible(selectors.cart_open):
            page.click(selectors.cart_open)

        # Read back cart data
        item_name = ""
        if selectors.product_title:
            el = page.query_selector(selectors.product_title)
            if el:
                item_name = (el.inner_text() or "").strip()

        unit_price = 0.0
        total_payable = 0.0
        if selectors.cart_total:
            el = page.query_selector(selectors.cart_total)
            if el:
                total_payable = _parse_currency(el.inner_text() or "")
                unit_price = total_payable  # fallback for single item

        cart_address = ""
        if selectors.cart_address:
            el = page.query_selector(selectors.cart_address)
            if el:
                cart_address = (el.inner_text() or "").strip()
        elif selectors.header_address:
            el = page.query_selector(selectors.header_address)
            if el:
                cart_address = (el.inner_text() or "").strip()

        quantity = 1
        if selectors.quantity_stepper:
            el = page.query_selector(selectors.quantity_stepper)
            if el:
                match = re.search(r"\d+", el.inner_text() or "")
                if match:
                    quantity = int(match.group(0))

        # Check for unexpected extra items
        has_extra_items = False
        if selectors.cart_items:
            items = page.query_selector_all(selectors.cart_items)
            if len(items) > 1:
                has_extra_items = True

        return CartResult(
            success=True,
            item_name=item_name or product.name,
            unit_price=unit_price,
            quantity=quantity,
            delivery_address=cart_address,
            total_payable=total_payable,
            has_extra_items=has_extra_items,
        )

    except Exception as exc:
        return CartResult(success=False, error=f"Exception during add_to_cart: {exc}")


def checkout(
    page: Any,
    cfg: Config,
    product: ProductConfig,
    cart: CartResult,
    current_state: dict[str, Any],
    dry_run: bool = False,
    state_path: str = state.DEFAULT_PATH,
) -> CheckoutResult:
    """Execute pre-checkout validation, method selection, lock write, and payment."""
    # 1. Pre-checkout validation
    is_valid, reason = validate_cart(cart, cfg, product, current_state)
    if not is_valid:
        logger.error("Pre-checkout validation failed: %s", reason)
        return CheckoutResult(success=False, error=reason)

    selectors = cfg.selectors
    if not selectors.checkout_button:
        return CheckoutResult(success=False, error="Selector 'checkout_button' is not configured")

    # Navigate to checkout screen
    try:
        page.click(selectors.checkout_button)
    except Exception as exc:
        return CheckoutResult(success=False, error=f"Failed to click checkout button: {exc}")

    # 2. Payment method selection
    selected_method = None
    for method in cfg.payment.priority:
        if method == "blinkit_wallet":
            # Check wallet balance if selector configured
            if selectors.wallet_balance:
                el = page.query_selector(selectors.wallet_balance)
                if el:
                    balance = _parse_currency(el.inner_text() or "")
                    if balance < cart.total_payable:
                        logger.warning(
                            "Wallet balance (₹%.2f) is less than order total (₹%.2f)",
                            balance,
                            cart.total_payable,
                        )
                        continue
            selected_method = "blinkit_wallet"
            break

        elif method == "cod":
            # Check if COD option is visible and enabled
            if selectors.payment_methods:
                el = page.query_selector(selectors.payment_methods)
                if el and "cod" in (el.inner_text() or "").lower():
                    selected_method = "cod"
                    break

        elif method == "saved_card_otp_relay":
            selected_method = "saved_card_otp_relay"
            break

    if not selected_method:
        return CheckoutResult(
            success=False,
            error="No eligible payment method with sufficient balance available",
        )

    # 3. Dry run check
    if dry_run:
        logger.info(
            "[DRY RUN] Mode C checkout ready: method='%s', total=₹%.2f, item='%s'. Halting before pay click.",
            selected_method,
            cart.total_payable,
            cart.item_name,
        )
        return CheckoutResult(
            success=True,
            dry_run=True,
            payment_method=selected_method,
        )

    # Everything that can fail without spending money must fail BEFORE the lock is
    # written, otherwise a config mistake leaves the bot in the uncertain state and
    # it refuses to start until a human clears it.
    if not selectors.pay_button:
        return CheckoutResult(
            success=False,
            error="Selector 'pay_button' is not configured; refusing to start a payment.",
        )

    # 4. SINGLE-ORDER LOCK SEQUENCE: Atomic write and fsync BEFORE pay click
    current_state = state.save(current_state, state_path, payment_attempt_started=product.id)
    logger.info("Lock written and fsynced for product %s. Proceeding to pay click.", product.id)

    try:
        # Click pay
        page.click(selectors.pay_button)

        # Wait for confirmation screen
        order_id = None
        if selectors.order_confirmation:
            page.wait_for_selector(selectors.order_confirmation, timeout=30000)
            if selectors.order_id:
                el = page.query_selector(selectors.order_id)
                if el:
                    order_id = (el.inner_text() or "").strip()

        # Mark this target bought and clear the in-flight flag, atomically.
        order_id = order_id or f"ORD-{int(time.time())}"
        state.record_order(current_state, product.id, order_id, cart.total_payable, state_path)
        return CheckoutResult(
            success=True,
            order_id=order_id,
            payment_method=selected_method,
        )

    except Exception as exc:
        logger.critical("Payment step encountered error: %s. Order status uncertain!", exc)
        return CheckoutResult(
            success=False,
            payment_method=selected_method,
            error=f"Payment execution error: {exc}",
        )
