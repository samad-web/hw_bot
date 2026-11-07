import dataclasses

import pytest
from checker import check, CheckResultKind
from config import Config, ProductConfig, DeliveryConfig, PollingConfig, PaymentConfig, SafetyConfig, ReliabilityConfig, SelectorsConfig, TelegramConfig, EvolutionConfig


class MockElement:
    def __init__(self, text: str = "", attributes: dict | None = None):
        self._text = text
        self._attributes = attributes or {}

    def inner_text(self) -> str:
        return self._text

    def get_attribute(self, attr: str):
        return self._attributes.get(attr)


class MockPage:
    def __init__(self, elements: dict | None = None, visible: dict | None = None):
        self.elements = elements or {}
        self.visible = visible or {}

    def query_selector(self, selector: str):
        return self.elements.get(selector)

    def is_visible(self, selector: str) -> bool:
        return self.visible.get(selector, False)


def test_missing_selector_returns_error(base_config: Config, target):
    empty_sel_cfg = dataclasses.replace(
        base_config,
        selectors=SelectorsConfig(product_title="", header_address="div.addr"),
    )
    page = MockPage()
    res = check(page, empty_sel_cfg, target)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "missing_selector"
    assert "product_title" in res.message


def test_login_wall_detected(base_config: Config, target):
    page = MockPage(
        visible={"div.login-modal": True},
    )
    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "login"


def test_location_drift_detected(base_config: Config, target):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Delivering to: Office, Bangalore 560001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R"),
            "button.add-btn": MockElement("Add"),
        },
        visible={"button.add-btn": True},
    )
    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "location_drift"


def test_wrong_product_detected(base_config: Config, target):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Delivering to: Home, Mumbai 400001"),
            "h1.p-title": MockElement("Hot Wheels Barbie Corvette 1956"),
            "button.add-btn": MockElement("Add"),
        },
        visible={"button.add-btn": True},
    )
    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "wrong_product"
    assert "Barbie Corvette" in res.message


def test_in_stock_detected(base_config: Config, target):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R R34"),
            "button.add-btn": MockElement("Add"),
        },
        visible={"button.add-btn": True},
    )
    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.IN_STOCK
    assert "Add button present" in res.message


def test_in_stock_quantity_stepper(base_config: Config, target):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R R34"),
            "div.stepper": MockElement("1"),
        },
        visible={"div.stepper": True},
    )
    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.IN_STOCK
    assert "Quantity stepper" in res.message


def test_out_of_stock_detected(base_config: Config, target):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R"),
            "div.out-of-stock": MockElement("Notify Me"),
        },
        visible={"div.out-of-stock": True},
    )
    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.OUT_OF_STOCK
    assert "Out-of-stock indicator" in res.message


def test_add_button_disabled_is_out_of_stock(base_config: Config, target):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R"),
            "button.add-btn": MockElement("Add", attributes={"disabled": "disabled"}),
        },
        visible={"button.add-btn": True},
    )
    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.OUT_OF_STOCK
    assert "disabled" in res.message


def test_unknown_layout_detected(base_config: Config, target):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R"),
        },
        visible={},
    )
    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "unknown_layout"


def test_waits_for_location_bar_to_hydrate(base_config: Config, target):
    """Blinkit server-renders the location bar as an empty shimmer and fills the
    address client-side, so reading it immediately looks exactly like drift."""
    from unittest.mock import MagicMock

    page = MagicMock()
    page.is_visible.return_value = False
    page.query_selector.return_value = None

    check(page, base_config, target)

    assert page.wait_for_function.called, "must wait for the address to hydrate"
    called_with = str(page.wait_for_function.call_args)
    assert base_config.selectors.header_address in called_with


def test_hydration_timeout_does_not_crash_the_check(base_config: Config, target):
    """A hydration timeout must degrade to a normal ERROR verdict, not an exception."""
    from unittest.mock import MagicMock

    page = MagicMock()
    page.wait_for_function.side_effect = TimeoutError("hydration timed out")
    page.is_visible.return_value = False
    page.query_selector.return_value = None

    res = check(page, base_config, target)
    assert res.kind == CheckResultKind.ERROR
