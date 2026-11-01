"""NibrasLite — lightweight persistent Selenium helper."""
from __future__ import annotations

__version__ = "0.1.4"

# Convenience re-exports so users can do: from nibraslite import Browser, By
from nibraslite.browser import (
    Browser, By, Keys, Select, ActionChains, WebDriverWait, EC,
    webdriver, WebElement, ShadowRoot, Options, SeleniumErrors,
    start, attach, ensure, is_alive, close_browser, kill,
    stealth, check_stealth, print_stealth,
    ensure_undetected,
    wait, wait_all, wait_gone, exist, visible, clickable, find, one,
    goto, click, clickn, type_text, body_text, eval_js, scroll, screenshot,
    tabs, new_tab, switch_tab, accept_alert,
    proxy_check, proxy_http, proxy_https, proxy_socks4, proxy_socks5, proxy_combine,
)
