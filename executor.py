"""Executor module for cart automation (Mode B) and checkout/payment (Mode C).

Web flow (F11): product page Add -> /cart (foreign lines removed, exactly one
unit) -> address -> payment page -> Cash on Delivery -> single-order lock ->
Pay Now. One unit per order; repeat orders wait for delivery (D14). Every safety gate runs before the lock is written.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import checker
import state
from config import Config, ProductConfig

logger = logging.getLogger("hw_bot")

CART_URL = "https://blinkit.com/cart"
STEP_WAIT_MS = 2500
# Handling + small-cart/delivery fees Blinkit adds on top of the items. Reserved
# when deciding how many units fit under the money caps; the real grand total is
# re-checked against the caps before paying.
FEE_BUFFER_INR = 60


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

    if not 1 <= cart.quantity <= product.quantity:
        return False, f"Cart quantity ({cart.quantity}) outside 1..{product.quantity}"

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


def _js_click(locator: Any) -> None:
    # Cart steppers report "outside of the viewport" to a normal click.
    locator.evaluate("el => el.click()")


def _line_qty(line: Any, sel: Any) -> int:
    """Quantity of one cart line: the bare text node inside the stepper. The +/-
    icons are font glyphs that render as digits, so never regex the whole box."""
    try:
        txt = line.locator(sel.quantity_stepper).first.evaluate(
            "el => [...el.childNodes].filter(n => n.nodeType === 3)"
            ".map(n => n.textContent).join('')")
        return int(re.sub(r"\D", "", txt) or 0)
    except Exception:
        return 0


def _grand_total(body: str) -> float:
    """Grand total from the cart page text (bottom bar '₹352 TOTAL', else the bill)."""
    m = (re.search(r"₹\s*([\d,]+(?:\.\d+)?)\s*TOTAL", body)
         or re.search(r"Grand total\D{0,6}?₹\s*([\d,]+(?:\.\d+)?)", body))
    return float(m.group(1).replace(",", "")) if m else 0.0


def _title_matches(title: str, product: ProductConfig) -> bool:
    a, b = title.strip().lower(), product.name.strip().lower()
    return bool(a) and (a in b or b in a)


def target_quantity(unit_price: float, product: ProductConfig, cfg: Config,
                    current_state: dict[str, Any]) -> int:
    """Units to buy: product.quantity, cut down to what the money caps allow."""
    if unit_price <= 0:
        return 0
    budgets = []
    if cfg.payment.max_order_value_inr > 0:
        budgets.append(cfg.payment.max_order_value_inr)
    if cfg.safety.max_total_spend_inr > 0:
        budgets.append(cfg.safety.max_total_spend_inr
                       - float(current_state.get("total_spent") or 0))
    qty = product.quantity
    if budgets:
        qty = min(qty, int((min(budgets) - FEE_BUFFER_INR) // unit_price))
    return max(qty, 0)


def open_cart(page: Any, cfg: Config) -> None:
    page.goto(CART_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(cfg.selectors.cart_items, timeout=15000)
    except Exception:
        pass  # an empty cart redirects to the home page and has no lines


def empty_cart(page: Any, cfg: Config) -> bool:
    """Remove everything from the cart. True when no cart line is left."""
    open_cart(page, cfg)
    for _ in range(40):
        if page.locator(cfg.selectors.cart_items).count() == 0:
            return True
        # Lines render before their steppers hydrate: no minus yet means wait.
        minus = page.locator(cfg.selectors.cart_minus)
        if minus.count():
            _js_click(minus.first)
        page.wait_for_timeout(STEP_WAIT_MS)
    return page.locator(cfg.selectors.cart_items).count() == 0


def add_to_cart(page: Any, cfg: Config, product: ProductConfig,
                current_state: dict[str, Any]) -> CartResult:
    """From the product page: Add, open the cart, drop foreign lines, keep one
    unit, then read back what checkout will validate."""
    sel = cfg.selectors
    if not sel.add_button:
        return CartResult(success=False, error="Selector 'add_button' is not configured")
    try:
        # The app-download overlay swallows clicks; clear it first.
        checker.dismiss_interstitials(page, cfg)
        if not page.is_visible(sel.add_button):
            if sel.out_of_stock and page.is_visible(sel.out_of_stock):
                return CartResult(success=False, missed=True, error="Product sold out before Add click")
            return CartResult(success=False, error="Add button not visible on page")

        el = page.query_selector(sel.bar_price) if sel.bar_price else None
        unit_price = _parse_currency(el.inner_text() or "") if el else 0.0
        fits = target_quantity(unit_price, product, cfg, current_state)
        if fits < 1:
            return CartResult(success=False, unit_price=unit_price, error=(
                f"Unit price Rs {unit_price:.0f} leaves no room under the spend caps"
                if unit_price else "Could not read the unit price"))

        page.click(sel.add_button)
        page.wait_for_timeout(STEP_WAIT_MS)
        open_cart(page, cfg)

        # Leftovers from earlier sessions must never ride along: remove every
        # line that is not the target before touching quantities.
        for _ in range(40):
            lines = page.locator(sel.cart_items)
            foreign = [lines.nth(i) for i in range(lines.count())
                       if not _title_matches(
                           lines.nth(i).locator(sel.cart_line_title).first.inner_text(), product)]
            if not foreign:
                break
            _js_click(foreign[0].locator(sel.cart_minus).first)
            page.wait_for_timeout(STEP_WAIT_MS)

        lines = page.locator(sel.cart_items)
        n = lines.count()
        if n == 0:
            return CartResult(success=False, missed=True, unit_price=unit_price,
                              error="Cart is empty after Add (sold out in the meantime?)")
        line = lines.first
        # A unit left over from an earlier failed attempt would make this 2.
        for _ in range(10):
            if _line_qty(line, sel) <= 1:
                break
            _js_click(line.locator(sel.cart_minus).first)
            page.wait_for_timeout(STEP_WAIT_MS)
        return CartResult(
            success=True,
            item_name=line.locator(sel.cart_line_title).first.inner_text().strip(),
            unit_price=unit_price,
            # Read back, not assumed: a leftover unit of the same car would make it 2,
            # and validate_cart then refuses (one unit per order, D14).
            quantity=_line_qty(line, sel),
            total_payable=_grand_total(page.inner_text("body")),
            has_extra_items=n > 1,
        )
    except Exception as exc:
        return CartResult(success=False, error=f"Exception during add_to_cart: {exc}")


def _await_confirmation(page: Any, cfg: Config) -> Optional[str]:
    """After Pay Now: the order id, or None when success could not be seen.

    shortcut: success = the page leaves /checkout (and not back to /cart) within
    60s; unverified until the first real order. None keeps the lock (uncertain
    state), so the bot alerts and never orders twice.
    """
    sel = cfg.selectors
    try:
        if sel.order_confirmation:
            page.wait_for_selector(sel.order_confirmation, timeout=60000)
        else:
            page.wait_for_url(lambda u: "/checkout" not in u and "/cart" not in u,
                              timeout=60000)
    except Exception:
        return None
    m = re.search(r"(\d{6,})", page.url)
    return m.group(1) if m else f"ORD-{int(time.time())}"


def checkout(
    page: Any,
    cfg: Config,
    product: ProductConfig,
    cart: CartResult,
    current_state: dict[str, Any],
    dry_run: bool = False,
    state_path: str = state.DEFAULT_PATH,
) -> CheckoutResult:
    """Cart page -> address -> payment page -> Cash on Delivery -> lock -> Pay Now."""
    ok, why = state.can_order(current_state, product.id, cfg.safety.max_orders_total)
    if not ok:
        return CheckoutResult(success=False, error=f"Ordering not permitted: {why}")
    if not cart.success:
        return CheckoutResult(success=False, error=f"Cart preparation failed: {cart.error}")
    sel = cfg.selectors
    # Everything that can fail without spending money fails BEFORE the lock.
    for name in ("checkout_button", "proceed_to_pay", "payment_frame", "cod_option", "pay_button"):
        if not getattr(sel, name):
            return CheckoutResult(success=False, error=(
                f"Selector '{name}' is not configured; refusing to start a payment."))

    try:
        # "Proceed" + address sheet appear only when no address is chosen yet;
        # otherwise the cart goes straight to "Proceed To Pay". The address is
        # verified on the payment page either way.
        proceed = page.locator(sel.checkout_button)
        if proceed.count():
            proceed.last.click()
            page.wait_for_timeout(3000)
        addr = page.get_by_text(cfg.delivery.pincode)
        if addr.count():
            addr.first.click()  # address sheet: never guess, pick by pincode
            page.wait_for_timeout(4000)
        page.locator(sel.proceed_to_pay).last.click()
        page.wait_for_selector(sel.payment_frame, timeout=45000)
        page.wait_for_timeout(4000)
        m = re.search(r"Delivery Address(.{0,250})", page.inner_text("body"), re.S)
        cart = dataclasses.replace(cart, delivery_address=m.group(1) if m else "")
    except Exception as exc:
        return CheckoutResult(success=False, error=f"Could not reach the payment page: {exc}")

    valid, reason = validate_cart(cart, cfg, product, current_state)
    if not valid:
        logger.error("Pre-checkout validation failed: %s", reason)
        return CheckoutResult(success=False, error=reason)

    cod = page.frame_locator(sel.payment_frame).locator(sel.cod_option).first
    try:
        if (cod.count() == 0 or cod.get_attribute("disabled") is not None
                or cod.locator("[aria-disabled='true']").count() > 0):
            return CheckoutResult(success=False, error="Cash on Delivery is not offered for this order")
        cod.click()
        page.wait_for_timeout(2000)
        pay = page.locator(sel.pay_button)
        if pay.count() == 0:
            return CheckoutResult(success=False, error="Pay Now button not found; refusing to pay.")
    except Exception as exc:
        return CheckoutResult(success=False, error=f"Could not select Cash on Delivery: {exc}")

    if dry_run:
        logger.info("[DRY RUN] COD ready: %s x%d, total Rs %.0f. Halting before Pay Now.",
                    cart.item_name, cart.quantity, cart.total_payable)
        return CheckoutResult(success=True, dry_run=True, payment_method="cod")

    # SINGLE-ORDER LOCK: written and fsynced BEFORE the pay click.
    current_state = state.save(current_state, state_path, payment_attempt_started=product.id)
    logger.info("Lock written and fsynced for product %s. Clicking Pay Now.", product.id)
    try:
        pay.last.click()
        order_id = _await_confirmation(page, cfg)
    except Exception as exc:
        order_id = None
        logger.critical("Pay Now step raised: %s", exc)
    if order_id is None:
        logger.critical("Pay Now clicked but no confirmation seen. Order status uncertain!")
        return CheckoutResult(success=False, payment_method="cod", error=(
            "Pay Now was clicked but no confirmation was seen. Order status UNCERTAIN: "
            "check Blinkit orders. The bot will not order this item again on its own."))
    state.record_order(current_state, product.id, order_id, cart.total_payable, state_path)
    return CheckoutResult(success=True, order_id=order_id, payment_method="cod")
