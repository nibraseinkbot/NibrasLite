"""EInkBot - Crashlytics reader (one session).

Plain Selenium (temp profile) + CDP Network.setCookie injection of the fresh
Firebase/Google session cookies, then:
  1. dump the Crashlytics issues list (custom window),
  2. open every issue detail page and dump its text (device/OS breakdown).

Cookies source : sel_nibras/session_cookies.json (NibrasLite project, gitignored)
Output         : sel_nibras/output/issues-list.txt
                 sel_nibras/output/issue-<n>-<id>.txt
                 sel_nibras/output/issues.json
"""
import json
import re
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

BASE = Path(__file__).resolve().parent
COOKIES = BASE / "session_cookies.json"
OUT_DIR = BASE / "output"
OUT_LIST = OUT_DIR / "issues-list.txt"

ROOT = "https://console.firebase.google.com"
TARGET_URL = (
    ROOT + "/project/einkbot-37f4c/crashlytics/app/android:app.einkbot/issues"
    "?time=1791417600000:1791590399000&versions=1.5%20(6)"
    "&state=open&tag=all&sort=eventCount"
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)

HOST_ONLY = {"__Host-1PLSID", "__Host-3PLSID", "__Host-GAPS"}
SIGNIN_MARKERS = ("sign in", "email or phone", "choose an account", "use another account")
ISSUE_RE = re.compile(r"/issues/([0-9a-f]{16,})")
# Issue rows are <a href="#"> SPA links; the nav links never carry an exception text.
ROW_XPATH = "//a[contains(., 'java.lang') or contains(., 'android.app')]"
MAX_ISSUES = 15


def make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument(f"--user-agent={UA}")
    # no --disable-blink-features=AutomationControlled: unsupported flag -> Chrome
    # warning bar; excludeSwitches enable-automation below hides automation instead
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--start-maximized")
    opts.add_argument("--window-size=1600,1000")
    return webdriver.Chrome(options=opts)


def inject_cookies(driver, cookies):
    driver.execute_cdp_cmd("Network.enable", {})
    ok = fail = 0
    for c in cookies:
        params = {
            "name": c["name"], "value": c["value"], "path": c.get("path", "/"),
            "secure": c.get("secure", False), "httpOnly": c.get("httpOnly", False),
            "sameSite": c.get("sameSite", "Lax"),
        }
        if "expiry" in c:
            params["expires"] = c["expiry"]
        if c["name"] in HOST_ONLY:
            params["url"] = f"https://{c['domain'].lstrip('.')}/"
        else:
            params["domain"] = c["domain"]
        try:
            if driver.execute_cdp_cmd("Network.setCookie", params).get("success"):
                ok += 1
            else:
                fail += 1
                print(f"  setCookie rejected: {c['name']}")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  setCookie error: {c['name']}: {e}")
    return ok, fail


def body_text(driver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception:  # noqa: BLE001
        return ""


def signed_out(driver) -> bool:
    if "accounts.google.com" in driver.current_url:
        return True
    hay = (driver.title or "").lower() + "\n" + body_text(driver)[:2000].lower()
    return any(m in hay for m in SIGNIN_MARKERS)


def wait_ready(driver, timeout=90) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(2)
        if signed_out(driver):
            return False
        txt = body_text(driver)
        if "crashlytics" in (driver.title or "").lower() and len(txt) > 1500:
            return True
    return True


def scroll_through(driver, rounds=4):
    try:
        for _ in range(rounds):
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight/2);")
            time.sleep(1.5)
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:  # noqa: BLE001
        pass


def issue_anchors(driver):
    return driver.find_elements(By.XPATH, ROW_XPATH)


def click_el(driver, el):
    try:
        el.click()
    except Exception:  # noqa: BLE001
        driver.execute_script("arguments[0].click();", el)


def main():
    cookies = json.loads(COOKIES.read_text(encoding="utf-8"))
    print(f"cookies loaded: {len(cookies)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    driver = make_driver()
    try:
        driver.get("https://www.google.com/")
        time.sleep(2)
        ok, fail = inject_cookies(driver, cookies)
        print(f"cookies injected: ok={ok} fail={fail}")

        driver.get(TARGET_URL)
        if not wait_ready(driver):
            print("RESULT: SIGNED-OUT on issues list -> STOP")
            return
        scroll_through(driver)
        list_text = body_text(driver)
        OUT_LIST.write_text(
            f"URL: {driver.current_url}\nTITLE: {driver.title}\n\n{list_text}",
            encoding="utf-8",
        )
        print(f"list: {len(list_text)} chars -> {OUT_LIST}")

        titles = [(a.text or "").strip().splitlines()[0] for a in issue_anchors(driver)]
        print(f"issue rows found: {len(titles)}")
        for i, t in enumerate(titles, 1):
            print(f"  [{i}] {t}")

        meta = []
        for i in range(min(len(titles), MAX_ISSUES)):
            driver.get(TARGET_URL)
            if not wait_ready(driver):
                print("RESULT: SIGNED-OUT (reload) -> STOP")
                break
            scroll_through(driver, rounds=2)
            anchors = issue_anchors(driver)
            if i >= len(anchors):
                print(f"  [{i + 1}] row vanished, stop")
                break
            click_el(driver, anchors[i])
            time.sleep(3)
            if not wait_ready(driver):
                print("RESULT: SIGNED-OUT (issue page) -> STOP")
                break
            scroll_through(driver)
            txt = body_text(driver)
            m = ISSUE_RE.search(driver.current_url)
            iid = m.group(1) if m else f"n{i + 1}"
            name = f"issue-{i + 1}-{iid}.txt"
            (OUT_DIR / name).write_text(
                f"URL: {driver.current_url}\nTITLE: {driver.title}\n\n{txt}",
                encoding="utf-8",
            )
            meta.append({
                "n": i + 1, "title": titles[i], "id": iid,
                "detail_url": driver.current_url, "file": name, "chars": len(txt),
            })
            print(f"  [{i + 1}/{min(len(titles), MAX_ISSUES)}] {iid} {len(txt)} chars -> {name}")

        (OUT_DIR / "issues.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print("RESULT: OK")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
