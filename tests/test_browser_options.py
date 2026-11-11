"""F10: browser launch options driven by env (laptop default vs VPS relay)."""
import main


def test_default_is_headless_and_direct(monkeypatch):
    monkeypatch.delenv("BROWSER_PROXY", raising=False)
    monkeypatch.delenv("BROWSER_HEADLESS", raising=False)
    opts = main.browser_options()
    assert opts["headless"] is True and "proxy" not in opts


def test_vps_relay_is_headful_and_proxied(monkeypatch):
    monkeypatch.setenv("BROWSER_PROXY", "socks5://127.0.0.1:1055")
    monkeypatch.setenv("BROWSER_HEADLESS", "0")
    opts = main.browser_options()
    assert opts["headless"] is False
    assert opts["proxy"] == {"server": "socks5://127.0.0.1:1055"}
