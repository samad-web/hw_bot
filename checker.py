"""Stock availability checker and identity assertor for Blinkit.

Checks if the target product is buyable at the configured location.
Biases towards reporting ERROR whenever unsure, to prevent silent blindness
or ordering the wrong item.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from config import Config, ProductConfig

logger = logging.getLogger("hw_bot")

# How long to let the client-side app fill in the delivery address before
# treating an empty location bar as drift.
# 20s, not 8s: through the home-phone relay the bar was still a shimmer at 8s.
# The wait ends as soon as it renders, so this only delays the ERROR verdict.
HYDRATION_TIMEOUT_MS = 20000
# The sticky action bar renders after the location bar, so it needs its own wait.
CTA_TIMEOUT_MS = 20000


class CheckResultKind(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    ERROR = "ERROR"


@dataclass(frozen=True)
class CheckResult:
    kind: CheckResultKind
    error_kind: Optional[str] = None  # e.g., missing_selector, login, blocked, location_drift, wrong_product, unknown_layout
    message: str = ""
    product_title: str = ""
    header_address: str = ""


def dismiss_interstitials(page: Any, cfg: Config) -> bool:
    """Close Blinkit's "get the app" overlay if it is covering the page.

    It appears unpredictably, sits above the product action bar, and swallows
    clicks, so every read and every click has to get past it first.
    """
    sel = getattr(cfg.selectors, "dismiss_modal", "")
    if not sel:
        return False
    try:
        if page.is_visible(sel):
            page.click(sel)
            page.wait_for_timeout(800)
            logger.info("Dismissed the Blinkit app-download interstitial.")
            return True
    except Exception as exc:
        logger.debug("Could not dismiss interstitial: %s", exc)
    return False


def check(page: Any, cfg: Config, product: ProductConfig) -> CheckResult:
    """Evaluate availability of ``product`` on the currently loaded page."""
    # 1. Selector validation
    selectors = cfg.selectors
    if not selectors.product_title:
        return CheckResult(
            CheckResultKind.ERROR,
            error_kind="missing_selector",
            message="Selector 'product_title' is not configured",
        )
    if not selectors.header_address:
        return CheckResult(
            CheckResultKind.ERROR,
            error_kind="missing_selector",
            message="Selector 'header_address' is not configured",
        )
    if not selectors.add_button and not selectors.out_of_stock:
        return CheckResult(
            CheckResultKind.ERROR,
            error_kind="missing_selector",
            message="Neither 'add_button' nor 'out_of_stock' selector is configured",
        )

    # 2. Clear any overlay before reading anything underneath it.
    dismiss_interstitials(page, cfg)

    # Check for login wall
    if selectors.login_wall:
        try:
            if page.is_visible(selectors.login_wall):
                return CheckResult(
                    CheckResultKind.ERROR,
                    error_kind="login",
                    message="Login wall detected - session expired or unauthenticated",
                )
        except Exception as e:
            logger.debug("Error checking login wall selector: %s", e)

    # 3. Location assertion. Blinkit server-renders the location bar as an empty
    # shimmer and fills the address in client-side, so reading it too early looks
    # exactly like location drift. Wait for real text before judging.
    try:
        page.wait_for_function(
            "sel => { const el = document.querySelector(sel);"
            " return !!el && el.innerText.trim().length > 0; }",
            arg=selectors.header_address,
            timeout=HYDRATION_TIMEOUT_MS,
        )
    except Exception as exc:
        logger.debug("Delivery address did not hydrate in %dms: %s", HYDRATION_TIMEOUT_MS, exc)

    try:
        addr_el = page.query_selector(selectors.header_address)
        if not addr_el:
            return CheckResult(
                CheckResultKind.ERROR,
                error_kind="location_drift",
                message=f"Header address element '{selectors.header_address}' not found",
            )
        addr_text = (addr_el.inner_text() or "").strip()
        expected_label = cfg.delivery.label.strip().lower()
        expected_pincode = cfg.delivery.pincode.strip()

        # Match either label or pincode if non-empty
        matched = False
        if expected_label and expected_label in addr_text.lower():
            matched = True
        elif expected_pincode and expected_pincode != "000000" and expected_pincode in addr_text:
            matched = True

        if not matched:
            return CheckResult(
                CheckResultKind.ERROR,
                error_kind="location_drift",
                message=(
                    f"Location drift: header shows '{addr_text}', "
                    f"expected label '{cfg.delivery.label}' or pincode '{cfg.delivery.pincode}'"
                ),
                header_address=addr_text,
            )
    except Exception as exc:
        return CheckResult(
            CheckResultKind.ERROR,
            error_kind="location_drift",
            message=f"Error reading delivery location: {exc}",
        )

    # 4. Identity assertion
    try:
        title_el = page.query_selector(selectors.product_title)
        if not title_el:
            return CheckResult(
                CheckResultKind.ERROR,
                error_kind="wrong_product",
                message=f"Product title element '{selectors.product_title}' not found",
                header_address=addr_text,
            )
        actual_title = (title_el.inner_text() or "").strip()
        expected_name = product.name.strip().lower()

        # If a name is configured (not empty or template placeholder)
        if expected_name and not expected_name.startswith("hot wheels <"):
            # Check if expected name is reasonably contained in title or vice versa
            if expected_name not in actual_title.lower() and actual_title.lower() not in expected_name:
                return CheckResult(
                    CheckResultKind.ERROR,
                    error_kind="wrong_product",
                    message=(
                        f"Product title mismatch: page shows '{actual_title}', "
                        f"expected '{product.name}'"
                    ),
                    product_title=actual_title,
                    header_address=addr_text,
                )
    except Exception as exc:
        return CheckResult(
            CheckResultKind.ERROR,
            error_kind="wrong_product",
            message=f"Error reading product title: {exc}",
            header_address=addr_text,
        )

    # 5. Check CTA / stock status.
    # The action bar hydrates after the address does. Reading it too early
    # yields a spurious unknown_layout, which costs a backoff and an alert.
    cta_sel = ", ".join(s for s in (selectors.add_button, selectors.out_of_stock) if s)
    if cta_sel:
        try:
            page.wait_for_selector(cta_sel, timeout=CTA_TIMEOUT_MS, state="visible")
        except Exception:
            logger.debug("Action bar did not render within %dms", CTA_TIMEOUT_MS)

    try:
        # Check quantity stepper first (if product is already in cart or active stepper)
        if selectors.quantity_stepper and page.is_visible(selectors.quantity_stepper):
            return CheckResult(
                CheckResultKind.IN_STOCK,
                message="Quantity stepper visible",
                product_title=actual_title,
                header_address=addr_text,
            )

        # Check Add button
        if selectors.add_button and page.is_visible(selectors.add_button):
            add_el = page.query_selector(selectors.add_button)
            # Check if button is disabled
            is_disabled = False
            if add_el:
                is_disabled = (
                    add_el.get_attribute("disabled") is not None
                    or add_el.get_attribute("aria-disabled") == "true"
                    or "disabled" in (add_el.get_attribute("class") or "").lower()
                )
            if is_disabled:
                return CheckResult(
                    CheckResultKind.OUT_OF_STOCK,
                    message="Add button present but disabled",
                    product_title=actual_title,
                    header_address=addr_text,
                )
            return CheckResult(
                CheckResultKind.IN_STOCK,
                message="Add button present and clickable",
                product_title=actual_title,
                header_address=addr_text,
            )

        # Check Out of stock / Notify me indicator
        if selectors.out_of_stock and page.is_visible(selectors.out_of_stock):
            return CheckResult(
                CheckResultKind.OUT_OF_STOCK,
                message="Out-of-stock indicator visible",
                product_title=actual_title,
                header_address=addr_text,
            )

        # Neither matched
        return CheckResult(
            CheckResultKind.ERROR,
            error_kind="unknown_layout",
            message="Neither Add button nor Out-of-Stock indicator found",
            product_title=actual_title,
            header_address=addr_text,
        )

    except Exception as exc:
        return CheckResult(
            CheckResultKind.ERROR,
            error_kind="unknown_layout",
            message=f"Error reading CTA status: {exc}",
            product_title=actual_title,
            header_address=addr_text,
        )
