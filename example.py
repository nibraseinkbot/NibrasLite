"""Example -- how to drive a site with the NibrasLite toolkit.

A copy-paste template for ANY website: open a persistent session, inject your
cookies, wait for content, and interact.  The reusable library is browser.py.

    python sel_nibras\\example.py
"""
from __future__ import annotations

import json
from pathlib import Path

import browser

BASE = Path(__file__).resolve().parent
COOKIES = BASE / "session_cookies.json"

URL = "https://example.com"
GOOGLE = "https://www.google.com/"
SIGNIN = ("sign in", "email or phone", "choose an account", "use another account", "signed out")


def signed_out(driver) -> bool:
    if "accounts.google.com" in driver.current_url:
        return True
    hay = (driver.title or "").lower() + "\n" + browser.body_text(driver)[:2000].lower()
    return any(m in hay for m in SIGNIN)


def main() -> int:
    # 1) persistent session (start if needed) + stealth.  Custom UA is one kwarg:
    #    browser.ensure(URL, ua="Mozilla/5.0 (...) Chrome/154.0.0.0 Safari/537.36")
    driver = browser.ensure(apply_stealth=True)

    # 2) go somewhere on a Google domain before injecting Google cookies
    browser.goto(driver, GOOGLE)
    if COOKIES.exists():
        ok, fail = browser.inject(driver, json.loads(COOKIES.read_text(encoding="utf-8")))
        print(f"cookies: {ok} injected, {fail} failed")

    # 3) navigate + clean waits
    browser.goto(driver, URL)
    if not browser.exist(driver, "body", timeout=10):
        print("[!] page did not load")
        return 1
    if signed_out(driver):
        print("[!] SIGNED OUT - cookies are stale; re-paste new_coc.txt + convert_cookies.py")
        return 1

    print("opened:", driver.current_url)
    print("stealth:", "OK" if browser.check_stealth(driver).get("passed") else "INCOMPLETE")
    print("leave it open, then:  python sel_nibras\\browser.py attach")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
