"""Appium app-buyer: place a Blinkit order by driving the genuine app on a real
phone. Detection stays on the web watcher; this only performs the purchase.

Two entry points for now:
  python app_buyer.py --devices             list connected phones
  python app_buyer.py --capture <prid>      deep-link to a product, dump the UI

The tap sequence (Add -> cart -> checkout -> wallet -> place order) is written
only after the real in-app selectors are captured from the live screen: guessing
them would risk buying the wrong item. See build-docs/features/09-appium-app-buyer.md.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# adb shipped alongside this project (see deploy notes). Override with ADB_PATH.
_DEFAULT_ADB = Path(
    os.environ.get("ADB_PATH", "")
) if os.environ.get("ADB_PATH") else None

PACKAGE = "com.grofers.customerapp"
APPIUM_URL = os.environ.get("APPIUM_URL", "http://127.0.0.1:4723")
CAPTURE_DIR = Path("logs/app_capture")


def find_adb() -> str:
    """Locate adb: ADB_PATH env, then PATH, else fail with guidance."""
    if _DEFAULT_ADB and _DEFAULT_ADB.is_file():
        return str(_DEFAULT_ADB)
    from shutil import which
    found = which("adb")
    if found:
        return found
    sys.exit("adb not found. Set ADB_PATH to platform-tools/adb(.exe).")


def adb(*args: str) -> str:
    return subprocess.run([find_adb(), *args], capture_output=True, text=True).stdout.strip()


def list_devices() -> list[str]:
    out = adb("devices")
    devs = [ln.split("\t")[0] for ln in out.splitlines()[1:]
            if ln.strip() and ln.endswith("device")]
    return devs


def product_url(prid: str) -> str:
    return f"https://blinkit.com/prn/x/prid/{prid}"


def open_product(prid: str) -> None:
    """Deep-link straight to the product screen in the app (manifest: https host)."""
    adb("shell", "am", "start", "-a", "android.intent.action.VIEW",
        "-d", product_url(prid), PACKAGE)


def new_driver():
    """Attach Appium to the already-running app (noReset: never log out the user)."""
    from appium import webdriver
    from appium.options.android import UiAutomator2Options
    opts = UiAutomator2Options()
    opts.platform_name = "Android"
    opts.automation_name = "UiAutomator2"
    opts.app_package = PACKAGE
    opts.no_reset = True
    opts.new_command_timeout = 300
    return webdriver.Remote(APPIUM_URL, options=opts)


def capture(prid: str) -> int:
    """Open the product in-app and dump the UI tree + screenshot for selector work."""
    if not list_devices():
        sys.exit("No device. Connect a phone with USB debugging and run --devices.")
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    open_product(prid)
    time.sleep(6)  # let the product screen render
    driver = new_driver()
    try:
        stamp = CAPTURE_DIR / f"{int(time.time())}_{prid}"
        Path(f"{stamp}.xml").write_text(driver.page_source, encoding="utf-8")
        driver.get_screenshot_as_file(f"{stamp}.png")
        print(f"Captured:\n  {stamp}.xml\n  {stamp}.png")
        # Surface the obvious candidates so the next step is quick.
        import re
        for m in re.findall(r'(text|content-desc)="([^"]{2,40})"', driver.page_source):
            if re.search(r"add|cart|notify|coming|out of|buy|checkout|pay|wallet",
                         m[1], re.I):
                print(f"   {m[0]}={m[1]!r}")
    finally:
        driver.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Blinkit Appium app-buyer")
    ap.add_argument("--devices", action="store_true", help="list connected phones")
    ap.add_argument("--capture", metavar="PRID", help="dump the app UI for a product id")
    args = ap.parse_args(argv)

    if args.devices:
        devs = list_devices()
        print("Connected devices:", devs or "(none)")
        return 0 if devs else 1
    if args.capture:
        return capture(args.capture)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
