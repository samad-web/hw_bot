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


@pytest.fixture
def base_config() -> Config:
    return Config(
        product=ProductConfig(
            name="Hot Wheels Nissan Skyline GT-R",
            url="https://blinkit.com/prn/hot-wheels-gtr/prid/123",
            max_price_inr=200,
            quantity=1,
        ),
        delivery=DeliveryConfig(
            label="Home",
            lat=19.0,
            lng=72.0,
            pincode="400001",
        ),
        mode="A",
        polling=PollingConfig(interval_seconds=45, jitter_seconds=15),
        payment=PaymentConfig(max_order_value_inr=250),
        safety=SafetyConfig(max_orders_total=1),
        reliability=ReliabilityConfig(),
        selectors=SelectorsConfig(
            product_title="h1.p-title",
            header_address="div.h-addr",
            add_button="button.add-btn",
            out_of_stock="div.out-of-stock",
            quantity_stepper="div.stepper",
            login_wall="div.login-modal",
        ),
        telegram=TelegramConfig(),
        evolution=EvolutionConfig(),
    )


def test_missing_selector_returns_error(base_config: Config):
    empty_sel_cfg = Config(
        product=base_config.product,
        delivery=base_config.delivery,
        mode=base_config.mode,
        polling=base_config.polling,
        payment=base_config.payment,
        safety=base_config.safety,
        reliability=base_config.reliability,
        selectors=SelectorsConfig(product_title="", header_address="div.addr"),
        telegram=base_config.telegram,
        evolution=base_config.evolution,
    )
    page = MockPage()
    res = check(page, empty_sel_cfg)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "missing_selector"
    assert "product_title" in res.message


def test_login_wall_detected(base_config: Config):
    page = MockPage(
        visible={"div.login-modal": True},
    )
    res = check(page, base_config)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "login"


def test_location_drift_detected(base_config: Config):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Delivering to: Office, Bangalore 560001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R"),
            "button.add-btn": MockElement("Add"),
        },
        visible={"button.add-btn": True},
    )
    res = check(page, base_config)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "location_drift"


def test_wrong_product_detected(base_config: Config):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Delivering to: Home, Mumbai 400001"),
            "h1.p-title": MockElement("Hot Wheels Barbie Corvette 1956"),
            "button.add-btn": MockElement("Add"),
        },
        visible={"button.add-btn": True},
    )
    res = check(page, base_config)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "wrong_product"
    assert "Barbie Corvette" in res.message


def test_in_stock_detected(base_config: Config):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R R34"),
            "button.add-btn": MockElement("Add"),
        },
        visible={"button.add-btn": True},
    )
    res = check(page, base_config)
    assert res.kind == CheckResultKind.IN_STOCK
    assert "Add button present" in res.message


def test_in_stock_quantity_stepper(base_config: Config):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R R34"),
            "div.stepper": MockElement("1"),
        },
        visible={"div.stepper": True},
    )
    res = check(page, base_config)
    assert res.kind == CheckResultKind.IN_STOCK
    assert "Quantity stepper" in res.message


def test_out_of_stock_detected(base_config: Config):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R"),
            "div.out-of-stock": MockElement("Notify Me"),
        },
        visible={"div.out-of-stock": True},
    )
    res = check(page, base_config)
    assert res.kind == CheckResultKind.OUT_OF_STOCK
    assert "Out-of-stock indicator" in res.message


def test_add_button_disabled_is_out_of_stock(base_config: Config):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R"),
            "button.add-btn": MockElement("Add", attributes={"disabled": "disabled"}),
        },
        visible={"button.add-btn": True},
    )
    res = check(page, base_config)
    assert res.kind == CheckResultKind.OUT_OF_STOCK
    assert "disabled" in res.message


def test_unknown_layout_detected(base_config: Config):
    page = MockPage(
        elements={
            "div.h-addr": MockElement("Home - 400001"),
            "h1.p-title": MockElement("Hot Wheels Nissan Skyline GT-R"),
        },
        visible={},
    )
    res = check(page, base_config)
    assert res.kind == CheckResultKind.ERROR
    assert res.error_kind == "unknown_layout"
