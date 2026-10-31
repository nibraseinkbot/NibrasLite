"""selfcheck.py -- runnable proof that the FULL Selenium API works via browser.py.

    python sel_nibras\\selfcheck.py   # NibrasLite self-check

Starts/attaches the persistent Chrome, walks through every Selenium family
navigation, cookies, windows, JS, screenshots, all 8 locator strategies,
the WebElement API, Select/ActionChains/alerts/frames, WebDriverWait+EC,
and the Browser wrapper (native proxy + our helpers).

Never calls quit()/close() on the attached browser, so the session survives.
Exits non-zero if anything fails.
"""
from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import browser
from browser import (webdriver, By, Keys, Select, ActionChains, WebDriverWait, EC,
                     WebElement, Options, TimeoutException, NoSuchElementException,
                     WebDriverException, SeleniumErrors)

try:
    _ns: dict = {}
    exec("from browser import *", _ns)
    STAR_OK: object = all(k in _ns for k in ("By", "Keys", "Select", "ActionChains",
                                             "WebDriverWait", "EC", "webdriver", "Browser"))
except Exception as e:  # noqa: BLE001
    STAR_OK = f"{type(e).__name__}: {e}"

P = F = 0


def check(name, fn):
    global P, F
    try:
        r = fn()
        assert r is not False, "returned False"
        P += 1
        print(f"  [OK ] {name}")
        return r
    except Exception as e:  # noqa: BLE001
        F += 1
        print(f"  [XX ] {name}  -> {type(e).__name__}: {e}")
        return None


def _raise_ok():
    try:
        d.find_element(By.ID, "definitely_absent")
        return False
    except NoSuchElementException:
        return True


def _timeout_ok():
    try:
        WebDriverWait(d, 1).until(EC.presence_of_element_located((By.ID, "xxx")))
        return False
    except TimeoutException:
        return True


d = browser.ensure("about:blank")
print("attached:", d.current_url, "| driver class:", type(d).__name__)

print("\n== A) WebDriver: navigation / info ==")
check("driver.get", lambda: d.get("https://example.com/") or True)
check("driver.title", lambda: d.title)
check("driver.current_url", lambda: d.current_url)
check("driver.page_source", lambda: len(d.page_source) > 50)
check("driver.name", lambda: d.name)
check("driver.capabilities", lambda: bool(d.capabilities))
check("driver.session_id", lambda: bool(d.session_id))
check("driver.back/forward", lambda: (d.back(), d.forward(), True)[-1])
check("driver.refresh", lambda: d.refresh() or True)

print("\n== B) WebDriver: cookies (https) ==")
check("add_cookie", lambda: d.add_cookie({"name": "nb", "value": "1"}) or True)
check("get_cookie", lambda: d.get_cookie("nb")["value"] == "1")
check("get_cookies", lambda: len(d.get_cookies()) >= 1)
check("delete_cookie", lambda: d.delete_cookie("nb") or True)
check("delete_all_cookies", lambda: d.delete_all_cookies() or True)

print("\n== C) WebDriver: windows / tabs ==")
check("new_window(tab)", lambda: d.switch_to.new_window("tab"))
check("window_handles", lambda: len(d.window_handles) >= 1)
check("current_window_handle", lambda: bool(d.current_window_handle))
check("set_window_size", lambda: d.set_window_size(1200, 800) or True)
check("get_window_size", lambda: d.get_window_size())
check("maximize_window", lambda: d.maximize_window() or True)
check("get_window_rect", lambda: d.get_window_rect())
check("native close() [temp tab]", lambda: d.close() or True)
check("switch back", lambda: d.switch_to.window(d.window_handles[0]) or True)

print("\n== D) WebDriver: timeouts / js ==")
check("implicitly_wait", lambda: d.implicitly_wait(2) or True)
check("set_script_timeout", lambda: d.set_script_timeout(15) or True)
check("set_page_load_timeout", lambda: d.set_page_load_timeout(30) or True)
check("execute_script", lambda: d.execute_script("return 2+2") == 4)
check("execute_async_script", lambda: d.execute_async_script(
    "const cb=arguments[arguments.length-1]; setTimeout(()=>cb(7),50);") == 7)

print("\n== E) WebDriver: screenshots ==")
check("get_screenshot_as_png", lambda: len(d.get_screenshot_as_png()) > 100)
check("save_screenshot", lambda: bool(d.save_screenshot(str(BASE / "output" / "_selfcheck.png"))))
check("get_screenshot_as_base64", lambda: len(d.get_screenshot_as_base64()) > 100)

HTML = """<!doctype html><html><head><title>DataPage</title></head><body>
<h1 id="t" class="head">Title</h1>
<input id="inp" name="q" value="old" type="text">
<select id="sel"><option value="a">Alpha</option>
<option value="b" selected>Beta</option></select>
<input id="chk" type="checkbox">
<button id="btn">B</button>
<a id="lnk" href="https://example.org/">Go Link</a>
<iframe id="fr" srcdoc="<p id='inside'>inner</p>"></iframe>
</body></html>"""
DATA_URL = "data:text/html;charset=utf-8," + urllib.parse.quote(HTML)
d.get(DATA_URL)

print("\n== F) find_element: ALL 8 locator strategies ==")
check("By.ID", lambda: d.find_element(By.ID, "t").text == "Title")
check("By.CLASS_NAME", lambda: d.find_element(By.CLASS_NAME, "head").tag_name == "h1")
check("By.NAME", lambda: d.find_element(By.NAME, "q").get_attribute("value") == "old")
check("By.TAG_NAME", lambda: d.find_element(By.TAG_NAME, "select"))
check("By.XPATH", lambda: d.find_element(By.XPATH, "//input[@id='inp']"))
check("By.CSS_SELECTOR", lambda: d.find_element(By.CSS_SELECTOR, "#sel"))
check("By.LINK_TEXT", lambda: d.find_element(By.LINK_TEXT, "Go Link"))
check("By.PARTIAL_LINK_TEXT", lambda: d.find_element(By.PARTIAL_LINK_TEXT, "Go"))
check("find_elements", lambda: len(d.find_elements(By.TAG_NAME, "input")) == 2)
check("NoSuchElementException", _raise_ok)

print("\n== G) WebElement API ==")
el = d.find_element(By.ID, "inp")
check("clear", lambda: el.clear() or True)
check("send_keys + Keys", lambda: el.send_keys("hello", Keys.END, "!") or True)
check("get_attribute value", lambda: el.get_attribute("value") == "hello!")
check("is_displayed", lambda: el.is_displayed() is True)
check("is_enabled", lambda: el.is_enabled() is True)
check("tag_name", lambda: el.tag_name == "input")
check("size", lambda: bool(el.size))
check("location", lambda: bool(el.location))
check("rect", lambda: bool(el.rect))
check("value_of_css_property", lambda: el.value_of_css_property("display") != "")
check("click", lambda: d.find_element(By.ID, "chk").click() or True)
check("is_selected", lambda: d.find_element(By.ID, "chk").is_selected() is True)

print("\n== H) Select / ActionChains / Alerts / Frames ==")
check("Select.select_by_value", lambda: Select(d.find_element(By.ID, "sel")
      ).select_by_value("a") or True)
check("Select.first_selected_option", lambda:
      Select(d.find_element(By.ID, "sel")).first_selected_option.text == "Alpha")
check("ActionChains.move+click", lambda: ActionChains(d).move_to_element(
    d.find_element(By.ID, "btn")).click().perform() or True)
check("switch_to.frame + back", lambda: (d.switch_to.frame(0),
      d.find_element(By.ID, "inside").text == "inner",
      d.switch_to.default_content(), True)[-1])
check("alert accept", lambda: (d.execute_script("alert('hi')") or True,
      d.switch_to.alert.text == "hi", d.switch_to.alert.accept(), True)[-1])

print("\n== I) WebDriverWait + expected_conditions ==")
check("EC.presence_of_element_located", lambda: WebDriverWait(d, 5).until(
    EC.presence_of_element_located((By.ID, "t"))))
check("EC.visibility_of_element_located", lambda: WebDriverWait(d, 5).until(
    EC.visibility_of_element_located((By.ID, "t"))))
check("EC.element_to_be_clickable", lambda: WebDriverWait(d, 5).until(
    EC.element_to_be_clickable((By.ID, "btn"))))
check("EC.text_to_be_present_in_element", lambda: WebDriverWait(d, 5).until(
    EC.text_to_be_present_in_element((By.ID, "t"), "Title")))
check("TimeoutException raised", _timeout_ok)

print("\n== J) Browser wrapper proxies native + helpers ==")
b = browser.Browser(d)
check("native b.execute_script", lambda: b.execute_script("return 1+1") == 2)
check("native b.find_element", lambda: b.find_element(By.ID, "t").text == "Title")
b.get("https://example.com/")
check("native b.title", lambda: b.title == "Example Domain")
check("native b.add_cookie", lambda: b.add_cookie({"name": "w", "value": "9"}) or True)
check("native b.get_cookies", lambda: any(c["name"] == "w" for c in b.get_cookies()))
check("native b.get_screenshot_as_png", lambda: len(b.get_screenshot_as_png()) > 100)
check("native b.switch_to", lambda: bool(b.switch_to))
check("proxy b.driver is d", lambda: b.driver is d)
b.get(DATA_URL)
check("helper b.wait", lambda: b.wait("#t", "visible", 5).text == "Title")
check("helper b.exist", lambda: b.exist("#t") is True)
check("helper b.eval", lambda: b.eval("document.querySelectorAll('input').length") == 2)
check("helper b.click", lambda: b.click("#chk") is b)

print("\n== K) re-exports / star-import ==")
check("__all__ every name exists", lambda: all(hasattr(browser, n) for n in browser.__all__))
check("__all__ no duplicates", lambda: len(browser.__all__) == len(set(browser.__all__)))
check("from browser import *", lambda: STAR_OK is True)
check("SeleniumErrors module", lambda: hasattr(SeleniumErrors, "NoSuchElementException"))

print(f"\n== L) exceptions coverage ==")
# Check all Selenium exceptions (not typing.Any) are re-exported from browser
from selenium.common import exceptions as SeleniumErrors_mod
_browser_exc_names = [
    "DetachedShadowRootException", "ElementClickInterceptedException",
    "ElementNotInteractableException", "ElementNotSelectableException",
    "ElementNotVisibleException", "ImeActivationFailedException",
    "ImeNotAvailableException", "InsecureCertificateException",
    "InvalidArgumentException", "InvalidCookieDomainException",
    "InvalidCoordinatesException", "InvalidElementStateException",
    "InvalidSelectorException", "InvalidSessionIdException",
    "InvalidSwitchToTargetException", "JavascriptException",
    "MoveTargetOutOfBoundsException", "NoAlertPresentException",
    "NoSuchAttributeException", "NoSuchCookieException",
    "NoSuchDriverException", "NoSuchElementException", "NoSuchFrameException",
    "NoSuchShadowRootException", "NoSuchWindowException", "ScreenshotException",
    "SessionNotCreatedException", "StaleElementReferenceException",
    "UnableToSetCookieException", "UnexpectedAlertPresentException",
    "UnexpectedTagNameException", "UnknownMethodException", "WebDriverException",
]
# Check module availability
_exc_module_ok = all(hasattr(browser, name) for name in _browser_exc_names)
check("all Selenium exceptions in browser module", lambda: _exc_module_ok)
# Check __all__ coverage
__all_exc_ok = all(name in browser.__all__ for name in _browser_exc_names)
check("all Selenium exceptions in __all__", lambda: __all_exc_ok)
# Specific critical ones to highlight
_critical_missing = [n for n in _browser_exc_names if n not in browser.__all__]
if _critical_missing:
    print(f"  Critical missing from __all__: {_critical_missing}")
else:
    print("  No critical exceptions missing from __all__")

print("\n== M) ShadowRoot coverage ==")
# Check ShadowRoot
_sr_ok = hasattr(browser, "ShadowRoot") and "ShadowRoot" in browser.__all__
check("ShadowRoot re-exported in browser module", lambda: _sr_ok)
# Verify it's the right class
try:
    from selenium.webdriver.remote.shadowroot import ShadowRoot as _RealShadowRoot
    _sr_is_real = browser.ShadowRoot is _RealShadowRoot
    check("ShadowRoot is correct selenium class", lambda: _sr_is_real)
except Exception:
    check("ShadowRoot is some class", lambda: hasattr(browser, "ShadowRoot"))

print(f"\n== N) proxy functions ==")
# proxy_check basic
check("proxy_check exists", lambda: callable(browser.proxy_check))
check("proxy_http exists", lambda: callable(browser.proxy_http))
check("proxy_https exists", lambda: callable(browser.proxy_https))
check("proxy_socks4 exists", lambda: callable(browser.proxy_socks4))
check("proxy_socks5 exists", lambda: callable(browser.proxy_socks5))
check("proxy_combine exists", lambda: callable(browser.proxy_combine))
# proxy_check returns dict with expected keys
r = browser.proxy_check("1.2.3.4", 8080)
_keys_ok = all(k in r for k in ("type", "country", "lang", "timezone", "speed", "works"))
check("proxy_check returns valid dict", lambda: _keys_ok)
# proxy_combine with explicit type
r2 = browser.proxy_combine("socks5", "5.6.7.8", 1080)
check("proxy_combine socks5 type", lambda: r2["type"] == "socks5")
check("proxy_combine http type", lambda: browser.proxy_combine("http", "1.1.1.1", 3128)["type"] == "http")

print("\n== O) stealth re-application ==")
browser.stealth(d)
rep = browser.check_stealth(d)
check("stealth re-applied OK", lambda: rep.get("passed") is True)
check("stealth 20/20 tests", lambda: len(rep.get("tests", {})) == 20)
for name, ok in rep.get("tests", {}).items():
    if not ok:
        print(f"  [XX] stealth: {name}")

print(f"\n================  PASSED {P}  |  FAILED {F}  ================")
sys.exit(1 if F else 0)
