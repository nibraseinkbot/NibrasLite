"""Generic page probe: attach to the running NibrasLite browser and dump its structure.

Works on ANY site (not just Crashlytics).  Run `browser.py start` first and
navigate where you want, then:

    python sel_nibras\\probe.py

Output: prints a summary and saves output/probe.txt with
  * current URL / title
  * every <a> : href + text
  * a couple of container selectors (handy examples)
  * the built-in stealth check report
"""
from __future__ import annotations

from selenium.webdriver.common.by import By

import browser

OUT = browser.OUT_DIR / "probe.txt"
CONTAINERS = ["div.row-wrapper", "c9s-issue-caption-metadata-row"]


def main() -> int:
    driver = browser.attach()
    lines = [f"URL: {driver.current_url}", f"TITLE: {driver.title}", ""]

    anchors = driver.find_elements(By.TAG_NAME, "a")
    lines.append(f"anchors: {len(anchors)}")
    for i, a in enumerate(anchors):
        href = a.get_attribute("href") or ""
        txt = (a.text or "").replace("\n", " | ")[:80]
        lines.append(f"  [{i:>3}] {href[-120:]}  ||  {txt}")

    lines.append("")
    for sel in CONTAINERS:
        lines.append(f"{sel}: {len(driver.find_elements(By.CSS_SELECTOR, sel))}")

    lines.append("")
    lines.append("-- stealth --")
    rep = browser.check_stealth(driver)
    for name, ok in rep.get("tests", {}).items():
        lines.append(f"  [{'OK' if ok else 'XX'}] {name}")
    lines.append(f"  => {'STEALTH OK' if rep.get('passed') else 'INCOMPLETE'}")

    browser.OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:80]))
    print(f"\n... full report -> {OUT}")
    return 0          # do NOT quit: Chrome stays open


if __name__ == "__main__":
    raise SystemExit(main())
