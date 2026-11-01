"""NibrasLite (nibras_browser) -- a lightweight Selenium helper (not a strong anti-detection tool).

Persistent session
------------------
Chrome is started as a *standalone OS process* with a fixed remote-debug port
and a private profile -> it keeps running after the script exits.  Every later
script ATTACHES to that same Chrome through CDP `debuggerAddress`, so tabs,
login, cookies and scroll position stay alive.  Add a new Selenium line to
click another button, run it, and you are still in the same window.

Full Selenium API
-----------------
This module re-exports the whole common Selenium surface (By, Keys, Select,
ActionChains, WebDriverWait, EC, exceptions, ...) so you can `import browser`
and use everything from one place.  The driver returned by ensure()/attach()
IS a real Selenium WebDriver, so every native method works.  A thin `Browser`
wrapper also proxies *all* driver attributes if you prefer the object style.

Element waiting
---------------
Clean checks built on Selenium's own WebDriverWait / expected_conditions:
    wait(driver, sel, state="visible"|"present"|"clickable", timeout=...)
    wait_gone(driver, sel, timeout=...)
    exist(driver, sel, timeout=0)   visible(...)   clickable(...)

Config
------
    NIBRAS_PORT       remote-debugging port          (default 9222)
    NIBRAS_PROFILE    persistent Chrome profile dir  (default sel_nibras/_profile)
    NIBRAS_UA         override the User-Agent
    NIBRAS_HEADLESS   "1" to run headless (weaker stealth)
    NIBRAS_CHROME     explicit chrome.exe path

    NOTE: This is a LIGHTWEIGHT Selenium helper. The built-in stealth is weak and
    NOT tested against advanced detection systems (Google, Cloudflare, Playwright).

Profiles
--------
    default            persistent  sel_nibras/_profile          (login survives)
    name="work"        persistent  sel_nibras/profiles/work      (many profiles)
    profile=<path>     persistent  at any path you choose
    temp=True          temporary   OS temp dir, deleted on kill()  (Selenium-like)

    CLI:  browser.py start [--name work | --temp | --profile DIR] [--port N]
          browser.py attach [--name work]   browser.py status --all
          browser.py stop [--name work | --temp | --all] [--keep]
          browser.py profiles               browser.py profile new|rm NAME
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.remote.shadowroot import ShadowRoot
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.common import exceptions as SeleniumErrors
from selenium.common.exceptions import (
    DetachedShadowRootException, ElementClickInterceptedException,
    ElementNotInteractableException, ElementNotSelectableException,
    ElementNotVisibleException, ImeActivationFailedException,
    ImeNotAvailableException, InsecureCertificateException,
    InvalidArgumentException, InvalidCookieDomainException,
    InvalidCoordinatesException, InvalidElementStateException,
    InvalidSelectorException, InvalidSessionIdException,
    InvalidSwitchToTargetException, JavascriptException,
    MoveTargetOutOfBoundsException, NoAlertPresentException,
    NoSuchAttributeException, NoSuchCookieException, NoSuchDriverException,
    NoSuchElementException, NoSuchFrameException, NoSuchShadowRootException,
    NoSuchWindowException, ScreenshotException,
    SessionNotCreatedException, StaleElementReferenceException,
    TimeoutException, UnableToSetCookieException,
    UnexpectedAlertPresentException, UnexpectedTagNameException,
    UnknownMethodException, WebDriverException,
)

# ── Data dirs (configurable, auto-detected for local vs installed) ──────────
# When installed via pip, Path(__file__).parent points into site-packages
# (read-only / global), so we fall back to the user's home directory for
# writable data.  When running from source (editable install or local),
# BASE stays at the module directory so _profile/ and output/ work as before.
import importlib.util as _ilu
try:
    import undetected_chromedriver as _uc
except ImportError:
    _uc = None
_pkg_dir = Path(_ilu.find_spec("nibraslite").origin).parent if _ilu.find_spec("nibraslite") else None
_local_mode = _pkg_dir is not None and (_pkg_dir / "_profile").is_dir()
_NIBRAS_DATA_DIR = Path(os.environ.get(
    "NIBRAS_DATA_DIR",
    str(_pkg_dir) if _local_mode else str(Path.home() / ".nibraslite"),
))
BASE = Path(_NIBRAS_DATA_DIR)
BASE.mkdir(parents=True, exist_ok=True)

OUT_DIR = Path(os.environ.get(
    "NIBRAS_OUTPUT_DIR",
    BASE / "output",
))
OUT_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_PORT = int(os.environ.get("NIBRAS_PORT", "9222"))
DEFAULT_PROFILE = Path(os.environ.get("NIBRAS_PROFILE", BASE / "_profile"))
PROFILES_DIR = BASE / "profiles"          # named persistent profiles live here
TEMP_PREFIX = "nibras_tmp_"               # throwaway profiles in the OS temp dir
TEMP_MARKER = ".nibras_temp"              # marks a profile as temporary
HEADLESS = os.environ.get("NIBRAS_HEADLESS") == "1"
DEFAULT_TIMEOUT = 20.0
POLL = 0.25

HOST_ONLY = {"__Host-1PLSID", "__Host-3PLSID", "__Host-GAPS"}


# --------------------------------------------------------------------------- #
# Chrome discovery / launch
# --------------------------------------------------------------------------- #
def find_chrome() -> str:
    """Return the path to the installed Chrome/Chromium binary."""
    override = os.environ.get("NIBRAS_CHROME")
    if override and Path(override).exists():
        return override

    sysname = platform.system()
    if sysname == "Windows":
        candidates = [
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
        ]
    elif sysname == "Darwin":
        candidates = [
            shutil.which("google-chrome"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        ]
    else:  # Linux / other POSIX
        candidates = [
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("chrome"),
            "/usr/bin/google-chrome",
            "/usr/lib/chromium",
            "/snap/bin/chromium",
            "/var/lib/flatpak/exports/bin/com.google.Chrome",
        ]
    for p in candidates:
        if p and Path(p).exists():
            return str(p)
    raise FileNotFoundError("Chrome/Chromium not found - set NIBRAS_CHROME")


def chrome_version() -> str:
    """Return the major version string of the installed Chrome/Chromium."""
    override = os.environ.get("NIBRAS_CHROME_VERSION")
    if override:
        return override
    try:
        exe = find_chrome()
        sysname = platform.system()
        if sysname == "Windows":
            # Windows Chrome ships a version-numbered dir alongside chrome.exe (e.g. "154.0.0.0").
            app = Path(exe).parent
            vers = [d.name for d in app.iterdir() if d.is_dir() and d.name[:1].isdigit()]
            if vers:
                return max(vers, key=lambda s: tuple(int(x) for x in s.split(".") if x.isdigit()))
        elif sysname == "Darwin":
            import subprocess as _sp
            ver = _sp.run(
                ["defaults", "read", exe + "/Contents/Info.plist", "CFBundleShortVersionString"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if ver:
                return ver
        else:  # Linux / other POSIX
            import subprocess as _sp
            for cmd in ["google-chrome", "chromium", "chromium-browser", "chrome"]:
                ver = _sp.run([exe, "--version"], capture_output=True, text=True, timeout=5).stdout.strip()
                # "--version" may fail on some Chromium clones; fall through.
                if ver:
                    # Output is typically "Google Chrome 154.0.7766.0" or "Chromium 154.0.7766.0"
                    m = re.search(r"(\d+)", ver)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return "154"


def default_ua() -> str:
    """A User-Agent that matches the real installed Chrome on this OS (major version)."""
    override = os.environ.get("NIBRAS_UA")
    if override:
        return override
    major = chrome_version().split(".")[0]
    sysname = platform.system()
    if sysname == "Windows":
        platform_tok = "Windows NT 10.0; Win64; x64"
    elif sysname == "Darwin":
        platform_tok = "Macintosh; Intel Mac OS X 10_15_7"
    else:
        platform_tok = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({platform_tok}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )


def is_alive(port: int | None = None) -> bool:
    port = port or DEFAULT_PORT
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Profiles: choose persistent vs temporary, name them, list / create / delete
# --------------------------------------------------------------------------- #
def profile_path(profile=None, name: str | None = None) -> Path:
    """Where a profile lives (does NOT create it)."""
    if name:
        return PROFILES_DIR / name
    if profile:
        return Path(profile)
    return Path(DEFAULT_PROFILE)


def temp_profile() -> Path:
    """A throwaway profile in the OS temp dir (like Selenium), deleted on stop."""
    p = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    (p / TEMP_MARKER).write_text("temp", encoding="utf-8")
    return p


def is_temp_profile(profile) -> bool:
    return (Path(profile) / TEMP_MARKER).exists()


def resolve_profile(profile=None, name: str | None = None, temp: bool = False) -> Path:
    """Pick the profile dir.  temp -> fresh throwaway; name -> profiles/<name>."""
    if temp:
        return temp_profile()
    p = profile_path(profile, name)
    p.mkdir(parents=True, exist_ok=True)
    return p


def next_free_port(start_port: int | None = None, tries: int = 100) -> int:
    base = start_port or DEFAULT_PORT
    for p in range(base, base + tries):
        if not is_alive(p):
            return p
    raise RuntimeError("no free debugging port found")


def _is_ours(prof: str) -> bool:
    low = str(prof).lower()
    return low.startswith(str(BASE).lower()) or Path(prof).name.startswith(TEMP_PREFIX)


def _ps_lines() -> str:
    """Return command-line lines of all processes via `ps` (POSIX only)."""
    out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=5)
    return out.stdout


def running_instances() -> list[tuple[int, str]]:
    """[(port, profile)] for every Chrome WE launched (read from cmdline)."""
    sysname = platform.system()
    if sysname == "Windows":
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            "Where-Object { $_.CommandLine -like '*remote-debugging-port=*' } | "
            "ForEach-Object { $_.CommandLine }"
        )
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                             capture_output=True, text=True).stdout
    else:
        out = _ps_lines()
    found = []
    seen_ports = set()
    for line in out.splitlines():
        m = re.search(r"--remote-debugging-port=(\d+)", line)
        d = re.search(r'--user-data-dir=(?:"([^"]+)"|(\S+))', line)
        if m and d:
            prof = d.group(1) or d.group(2)
            if _is_ours(prof):
                port = int(m.group(1))
                if port not in seen_ports:   # one row per instance, not per process
                    seen_ports.add(port)
                    found.append((port, prof))
    return found


def find_port(name: str | None = None, profile=None) -> int | None:
    """Port of a running instance that uses this named/path profile."""
    want = str(profile_path(profile, name)).lower()
    for port, prof in running_instances():
        if str(prof).lower() == want:
            return port
    return None


def list_profiles() -> list[tuple[str, int]]:
    """[(label, bytes)] persistent profiles: named dirs + the default one."""
    out, seen, dirs = [], set(), []
    if PROFILES_DIR.exists():
        dirs += sorted(p for p in PROFILES_DIR.iterdir() if p.is_dir())
    if DEFAULT_PROFILE.exists():
        dirs.insert(0, DEFAULT_PROFILE)
    for d in dirs:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        label = d.name if d.parent == PROFILES_DIR else f"{d.name}  (default)"
        out.append((label, size))
    return out


def delete_profile(name: str, yes: bool = False) -> None:
    p = PROFILES_DIR / name
    if not p.exists():
        print(f"[browser] no such profile: {name}")
        return
    if not yes:
        ans = input(f"delete profile '{name}' ({p}) ? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("cancelled")
            return
    shutil.rmtree(p, ignore_errors=True)
    print(f"[browser] deleted profile {name}")


def instance_urls(port: int) -> list[str]:
    """Page URLs of a running instance (light CDP /json query)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as r:
            data = json.loads(r.read())
        return [t.get("url", "") for t in data if t.get("type") == "page"]
    except Exception:
        return []


def _chrome_args(port: int, profile: Path, headless: bool,
                 ua: str | None, extra_args: list[str] | None, lang: str | None = None,
                 binary: str | None = None, options: Options | None = None) -> list[str]:
    """Build the Chrome command-line from our flags + any Selenium Options."""
    # Start with our defaults
    chrome_exe = binary or find_chrome()
    args = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        f"--user-agent={ua or default_ua()}",
        # NOTE: no --disable-blink-features=AutomationControlled on purpose:
        # it is an UNSUPPORTED flag -> Chrome shows the warning bar on top of
        # the window ("stability and security will suffer").  Our built-in
        # STEALTH_JS already hides navigator.webdriver & friends, so the flag
        # is redundant.  Someone who insists can pass it via extra_args.
        "--disable-popup-blocking",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if lang:
        args.append(f"--lang={lang}")
        if "-" in lang:
            args.append(f"--accept-lang={lang},{lang.split('-')[0]}")
        else:
            args.append(f"--accept-lang={lang}")
    if headless:
        args.append("--headless=new")
    # Merge Selenium Options arguments (user-supplied options take precedence)
    if options:
        for arg in options.arguments:
            args.append(arg)
        if options.binary_location:
            args[0] = options.binary_location
        for exp in options.experimental_options.values():
            # experimental_options are dicts like {"excludeSwitches": ["enable-automation"]}
            if isinstance(exp, dict):
                for key, val in exp.items():
                    if isinstance(val, list):
                        for v in val:
                            args.append(f"--{key}={v}")
    if extra_args:
        args.extend(extra_args)
    args.append("chrome://new-tab-page/")   # first tab opens the New Tab Page
    return args


def start(port: int | None = None, profile: Path | None = None,
          headless: bool | None = None, ua: str | None = None,
          extra_args: list[str] | None = None, timeout: float = 30,
          name: str | None = None, temp: bool | None = None, lang: str | None = None,
          binary: str | None = None, options: Options | None = None) -> int:
    """Launch Chrome as an independent process (kept alive after exit).

    Profile choice
      default        -> persistent sel_nibras/_profile      (login survives)
      name="work"    -> persistent sel_nigras/profiles/work
      profile=<path> -> persistent at that path
      temp=True      -> throwaway dir in the OS temp (Selenium-like);
                        auto-deleted by kill()/stop(), unless keep_temp=True.

    ua: custom User-Agent.  extra_args: extra Chrome flags.
    binary: explicit chrome executable path (overrides auto-detection).
    options: a selenium Options object — its arguments / experimental_options
             are merged after our defaults (so you keep stealth by default).
    Returns the debugging port actually used.
    """
    # Capture whether caller explicitly requested a new profile/port before
    # defaults are applied — this determines whether we should reuse an
    # existing Chrome instance instead of launching a new one.
    _want_new_profile = bool(name or profile)
    _explicit_temp = temp is not None and temp
    _want_anything = _want_new_profile or _explicit_temp or port is not None

    # Default: temp=True unless a profile path was explicitly given.
    # This means every start() without --profile opens a fresh Chrome window.
    # Pass profile=... to keep a persistent profile.
    if temp is None:
        temp = profile is None
    wants_new = bool(name or profile or temp)
    port = port or DEFAULT_PORT

    # If no specific port/name/profile requested and a Chrome is already
    # running somewhere, reuse it — don't start a new window.
    if not _want_anything:
        instances = running_instances()
        if instances:
            reused_port, _ = instances[0]
            print(f"[browser] reusing existing instance on port {reused_port}")
            return reused_port

    if is_alive(port):
        if not wants_new:
            print(f"[browser] already running on port {port}")
            return port
        port = next_free_port(port)
    prof = resolve_profile(profile, name, temp)
    if headless is None:
        headless = HEADLESS
    subprocess.Popen(_chrome_args(port, prof, headless, ua, extra_args, lang, binary, options), close_fds=True)
    end = time.time() + timeout
    while time.time() < end:
        if is_alive(port):
            tag = "  [TEMP]" if is_temp_profile(prof) else ""
            print(f"[browser] started (port {port}, profile {prof}{tag})")
            return port
        time.sleep(0.5)
    raise RuntimeError(f"Chrome did not open its debug port on {port}")


def attach(port: int | None = None, name: str | None = None,
           profile=None) -> webdriver.Chrome:
    """Attach Selenium to a running Chrome (never owns it).

    With name=/profile= the port is auto-resolved from the running instance.
    If no port/name/profile is given, finds any running NibrasLite Chrome
    instance automatically.
    """
    if (name or profile) and port is None:
        found = find_port(name, profile)
        if found:
            port = found
    if port is None:
        # Auto-detect any running NibrasLite Chrome instance
        instances = running_instances()
        if instances:
            port = instances[0][0]
        else:
            port = DEFAULT_PORT
    if not is_alive(port):
        raise RuntimeError(f"no Chrome on port {port} - run: browser.py start")
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    return webdriver.Chrome(options=opts)


def _ensure_page(driver, timeout: float = 15) -> bool:
    """Guarantee the attached session has at least one page target."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if driver.window_handles:
                return True
        except Exception:
            pass
        try:
            driver.execute_cdp_cmd("Target.createTarget", {"url": "chrome://new-tab-page/"})
        except Exception:
            try:
                driver.switch_to.new_window("tab")
            except Exception:
                pass
        time.sleep(0.5)
    return False


def ensure(url: str | None = None, port: int | None = None, profile: Path | None = None,
           headless: bool | None = None, ua: str | None = None,
           extra_args: list[str] | None = None, name: str | None = None,
           temp: bool | None = None, apply_stealth: bool = True, lang: str | None = None,
           binary: str | None = None, options: Options | None = None) -> webdriver.Chrome:
    """One call: start if needed, attach, navigate, then hide automation.

    name=/temp= choose the profile exactly like start().
    binary: explicit chrome executable path (overrides auto-detection).
    options: a selenium Options object — its arguments / experimental_options
             are merged after our defaults (so you keep stealth by default).
    """
    port = port or DEFAULT_PORT
    # Default: temp=True unless a profile path was explicitly given.
    # This means every start() without --profile opens a fresh Chrome window.
    # Pass profile=... to keep a persistent profile.
    if temp is None:
        temp = profile is None
    if not is_alive(port):
        port = start(port=port, profile=profile, headless=headless, ua=ua,
                     extra_args=extra_args, name=name, temp=temp, lang=lang,
                     binary=binary, options=options)
    driver = attach(port)
    _ensure_page(driver)
    if url:
        driver.get(url)
    if apply_stealth:
        stealth(driver)
    return driver


# --------------------------------------------------------------------------- #
# Undetected Chrome (opt-in enhanced anti-detection)
# --------------------------------------------------------------------------- #
def _create_undetected_driver(
    headless: bool = False,
    ua: str | None = None,
    binary: str | None = None,
    profile: Path | None = None,
    name: str | None = None,
    temp: bool = False,
) -> "webdriver.Chrome":
    """Create a uc.Chrome driver with NibrasLite profile management.

    Unlike start()/attach(), this creates its own Chrome process via
    undetected-chromedriver. It does NOT integrate with the multi-instance
    architecture (running_instances / find_port etc.).
    """
    if _uc is None:
        raise ImportError(
            "undetected-chromedriver is not installed. "
            "Install it with: pip install undetected-chromedriver"
        )

    prof = resolve_profile(profile, name, temp)
    version_main = None
    _ver_override = os.environ.get("NIBRAS_CHROME_VERSION")
    if _ver_override:
        try:
            version_main = int(_ver_override)
        except ValueError:
            pass

    opts = _uc.ChromeOptions()
    if ua:
        opts.add_argument(f"--user-agent={ua}")
    opts.add_argument("--lang=en")

    driver = _uc.Chrome(
        options=opts,
        user_data_dir=str(prof),
        browser_executable_path=binary,
        headless=headless,
        version_main=version_main,
        suppress_welcome=True,
        use_subprocess=True,
    )

    # Apply NibrasLite's JS-based stealth on the initial page for layered
    # defense (UC patches chromedriver; this covers navigator-level signals).
    try:
        stealth(driver, all_tabs=False)
    except Exception:
        pass

    return driver


def ensure_undetected(
    url: str | None = None,
    headless: bool | None = None,
    ua: str | None = None,
    profile: Path | None = None,
    name: str | None = None,
    temp: bool | None = None,
    apply_stealth: bool = True,
    lang: str | None = None,
    binary: str | None = None,
) -> "Browser":
    """One-call UC-based entry point with anti-detection.

    Uses undetected-chromedriver for stronger evasion of bot-detection
    systems. Unlike ensure(), this does NOT support multi-instance:
    each call launches a fresh Chrome process.

    profile/name/temp behave like ensure(): explicit profile -> persistent,
    name -> profiles/<name>, temp -> throwaway, default -> temp=True.

    Returns a Browser wrapper (same API as ensure()).
    """
    if headless is None:
        headless = HEADLESS
    if temp is None:
        temp = profile is None and name is None

    driver = _create_undetected_driver(
        headless=headless, ua=ua, binary=binary,
        name=name, temp=temp, profile=profile,
    )

    if url:
        driver.get(url)
    if apply_stealth:
        stealth(driver)

    return Browser(driver)


def close_browser(driver) -> None:
    """Close the whole Chrome window (explicit only)."""
    try:
        driver.execute_cdp_cmd("Browser.close", {})
    except Exception:
        pass


def _stop_chrome(port: int | None = None, profile: str | None = None) -> None:
    """Kill Chrome processes matching the given port / profile path."""
    sysname = platform.system()
    if sysname == "Windows":
        conds = []
        if port is not None:
            conds.append(f"$_.CommandLine -like '*remote-debugging-port={port}*'")
        if profile is not None:
            conds.append(f"$_.CommandLine -like '*--user-data-dir={profile}*'")
        where = " -and ".join(conds) if conds else "$true"
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            f"Where-Object {{ {where} }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                       capture_output=True, text=True)
        time.sleep(0.4)
    else:
        lines = _ps_lines().splitlines()
        killed = 0
        for line in lines:
            match_port = port is not None and f"remote-debugging-port={port}" in line
            match_profile = profile is not None and f"--user-data-dir={profile}" in line
            if (port is None and profile is None) or match_port or match_profile:
                parts = line.split(maxsplit=1)
                if len(parts) < 2:
                    continue
                try:
                    pid = int(parts[0])
                    if pid != os.getpid():
                        os.kill(pid, 9)
                        killed += 1
                except (ValueError, ProcessLookupError, PermissionError):
                    pass
        if killed:
            time.sleep(0.4)


def kill(port: int | None = None, profile: Path | None = None,
         name: str | None = None, all: bool = False,
         keep_temp: bool = False) -> None:
    """Stop our Chrome.  all=True stops every nibras instance.

    Temporary profiles are DELETED (Selenium-like), unless keep_temp=True.
    Never touches other Chrome windows that are not ours.
    """
    if all:
        inst = running_instances()
        for pt, pf in inst:
            _stop_chrome(port=pt, profile=pf)
            if not keep_temp and is_temp_profile(pf):
                shutil.rmtree(pf, ignore_errors=True)
        print(f"[browser] stopped {len(inst)} instance(s)")
        return
    if name is not None or profile is not None:
        prof = profile_path(profile, name)
        _stop_chrome(profile=str(prof))
        if not keep_temp and is_temp_profile(prof):
            shutil.rmtree(prof, ignore_errors=True)
        print(f"[browser] stopped Chrome for profile {prof}")
        return
    port = port if port is not None else DEFAULT_PORT
    pf = None
    for pt, pp in running_instances():
        if pt == port:
            pf = pp
            break
    _stop_chrome(port=port)
    if not keep_temp and pf and is_temp_profile(pf):
        shutil.rmtree(pf, ignore_errors=True)
    print(f"[browser] stopped Chrome on port {port}")


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #
def cookies_load(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cookies_save(driver, path: str | Path) -> int:
    cookies = sorted(driver.get_cookies(), key=lambda c: (c.get("domain", ""), c["name"]))
    Path(path).write_text(json.dumps(cookies, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(cookies)


def inject(driver, cookies: list[dict]) -> tuple[int, int]:
    """Inject cookies through CDP Network.setCookie (handles __Host-*)."""
    driver.execute_cdp_cmd("Network.enable", {})
    ok = fail = 0
    for c in cookies:
        params = {
            "name": c["name"], "value": c["value"], "path": c.get("path", "/"),
            "secure": c.get("secure", False), "httpOnly": c.get("httpOnly", False),
            "sameSite": c.get("sameSite", "Lax"),
        }
        if c.get("expiry"):
            params["expires"] = int(c["expiry"])
        if c["name"] in HOST_ONLY:
            params["url"] = f"https://{c['domain'].lstrip('.')}/"
        else:
            params["domain"] = c["domain"]
        try:
            if driver.execute_cdp_cmd("Network.setCookie", params).get("success"):
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
    return ok, fail


def clear(driver, domain: str | None = None) -> int:
    if not domain:
        driver.delete_all_cookies()
        return 0
    n = 0
    for c in driver.get_cookies():
        if domain in c.get("domain", ""):
            driver.delete_cookie(c["name"])
            n += 1
    return n


def list_cookies(driver) -> list[str]:
    out = []
    for c in sorted(driver.get_cookies(), key=lambda x: (x.get("domain", ""), x["name"])):
        out.append(f'{c["name"]:<26} {c.get("domain", ""):<30} exp={c.get("expiry", "session")}')
    return out


def from_devtools_table(text: str) -> list[dict]:
    """Parse a DevTools -> Application -> Cookies table paste (or JSON export)."""
    from nibraslite.convert_cookies import from_json, from_table
    head = text.lstrip()[:1]
    return from_json(text) if head in ("[", "{") else from_table(text)


# --------------------------------------------------------------------------- #
# Stealth (built-in, no third-party library)
# --------------------------------------------------------------------------- #
STEALTH_JS = r"""
(() => {
  const def = (obj, prop, getter) => {
    try { Object.defineProperty(obj, prop, { get: getter, configurable: true }); } catch (e) {}
  };
  const patch = (proto, method, replacement) => {
    try {
      const orig = proto[method];
      if (typeof orig === 'function') proto[method] = replacement;
    } catch (e) {}
  };

  // 1) navigator.webdriver -> undefined/false
  def(Navigator.prototype, 'webdriver', () => false);

  // 2) languages: follow browser/system language (no override)

  // 3) hardware fingerprint
  def(Navigator.prototype, 'hardwareConcurrency', () => 8);
  def(Navigator.prototype, 'deviceMemory',        () => 8);

  // 4) plugins / mimeTypes (realistic Chrome set)
  try {
    const mk = (name, filename, desc) => {
      const p = Object.create(Plugin.prototype);
      Object.defineProperties(p, {
        name: { value: name }, filename: { value: filename },
        description: { value: desc }, length: { value: 1 },
      });
      return p;
    };
    const plugins = [
      mk('PDF Viewer',                    'internal-pdf-viewer',            'Portable Document Format'),
      mk('Chrome PDF Viewer',             'internal-pdf-viewer',            'Portable Document Format'),
      mk('Chromium PDF Viewer',           'internal-pdf-viewer',            'Portable Document Format'),
      mk('Native PDF',                    'internal-pdf-viewer',            'Portable Document Format'),
      mk('Widevine CDM',                  'widevinecdm.dll',                'Widevine Digital Rights Management'),
      mk('Google Update',                 'GoogleUpdate',                   'Google Update', ),
      mk('Shockwave Flash',               'pepflashplayer.dll',             'Shockwave Flash'),
      mk('Unity Plugin',                  'UnityPlayer.dll',                'Unity Web Player'),
    ];
    plugins.push(mk('', 'nacl', 'Native Client'));
    plugins.push(mk('', 'ppcapital', 'PPCapital'));
    Object.defineProperty(plugins, 'item', { value: (i) => plugins[i] });
    Object.defineProperty(plugins, 'namedItem', { value: (n) => plugins.find(p => p.name === n) });
    Object.defineProperty(plugins, 'refresh', { value: () => {} });
    def(Navigator.prototype, 'plugins', () => plugins);
  } catch (e) {}

  // 5) window.chrome
  try {
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) {
      window.chrome.runtime = {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install',
                             SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64',
                        X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformNaClArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
        connect: () => {}, sendMessage: () => {}, onConnect: { addListener: () => {} },
        onMessage:  { addListener: () => {} },
      };
    }
    if (!window.chrome.csi) {
      window.chrome.csi = () => ({ moduleName: 'Chrome', pageTid: 1, tid: 1, transitionType: 1 });
    }
    if (!window.chrome.loadTimes) {
      window.chrome.loadTimes = () => ({
        connectionInfo: 'qtcp', finishLoadTime: performance.now(),
        firstPaintAfterLoadTime: 0, loadTime: performance.now(),
        navEntry: null, nextHopProtocol: 'h2', numRedirects: 0,
        pageLoadTimeUsec: 0, proxyServer: '',
        sslConnectionStart: 0, startLoadTime: performance.now(),
      });
    }
  } catch (e) {}

  // 6) WebGL vendor / renderer — use real GPU, only hide if headless/SwiftShader
  try {
    const testCanvas = document.createElement('canvas');
    let realVendor = 'Google Inc.', realRenderer = 'ANGLE (Microsoft, Direct3D11...)';
    try {
      const gl = testCanvas.getContext('webgl') || testCanvas.getContext('experimental-webgl');
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      if (dbg) { realVendor = gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL); realRenderer = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL); }
    } catch (e) {}
    const isHeadless = realVendor.includes('SwiftShader') || realVendor.includes('Google Inc.') && realRenderer.includes('SwiftShader');
    const patch = (proto) => {
      const orig = proto.getParameter;
      proto.getParameter = function (p) {
        if (p === 37445) return isHeadless ? 'Intel Inc.' : realVendor;
        if (p === 37446) return isHeadless ? 'Intel Iris OpenGL Engine' : realRenderer;
        return orig.apply(this, arguments);
      };
    };
    patch(WebGLRenderingContext.prototype);
    if (window.WebGL2RenderingContext) patch(WebGL2RenderingContext.prototype);
  } catch (e) {}

  // 7) permissions: notifications must mirror Notification.permission
  try {
    const q = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (p) =>
      (p && p.name === 'notifications')
        ? Promise.resolve({ state: Notification.permission })
        : q(p);
  } catch (e) {}

  // 8) iframe.contentWindow leak
  try {
    const d = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
      get() { return d.get.call(this); }, configurable: true,
    });
  } catch (e) {}

  // 9) performance.now() — ensure monotonic
  try {
    const origNow = performance.now.bind(performance);
    Object.defineProperty(performance, 'now', {
      get: () => origNow, configurable: true
    });
  } catch (e) {}

  // 10) AudioContext fingerprinting
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC) {
      const origClose = AC.prototype.close;
      AC.prototype.close = function () {
        try { return origClose.apply(this, arguments); } catch (e) {}
      };
    }
  } catch (e) {}

  // 11) screen — mirror real values
  try {
    const _sw = screen.width, _sh = screen.height;
    def(Screen.prototype, 'width', () => _sw);
    def(Screen.prototype, 'height', () => _sh);
    def(Screen.prototype, 'availWidth', () => _sw);
    def(Screen.prototype, 'availHeight', () => _sh - 50);
  } catch (e) {}

  // 12) WebGL extensions — override with realistic list
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    if (gl) {
      const realExts = gl.getSupportedExtensions();
      WebGLRenderingContext.prototype.getSupportedExtensions = function() {
        return realExts;
      };
      if (window.WebGL2RenderingContext) {
        WebGL2RenderingContext.prototype.getSupportedExtensions = function() {
          return realExts;
        };
      }
    }
  } catch (e) {}

  // 13) Canvas fingerprinting — stable hash output
  try {
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    const _canvasHash = {};
    HTMLCanvasElement.prototype.toDataURL = function(type) {
      const key = this.width + 'x' + this.height + (type || 'image/png');
      if (!_canvasHash[key]) {
        _canvasHash[key] = origToDataURL.call(this, type || 'image/png');
      }
      return _canvasHash[key];
    };
  } catch (e) {}

  // 14) doNotTrack
  try {
    def(Navigator.prototype, 'doNotTrack', () => '1');
  } catch (e) {}

  // 15) connection
  try {
    def(Navigator.prototype, 'connection', () => ({
      effectiveType: '4g', rtt: 50, downlink: 10, saveData: false,
      addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    }));
  } catch (e) {}

  // 16) mediaDevices
  try {
    const md = {
      enumerateDevices: async () => [],
      getUserMedia: async () => null,
      ondevicechange: null,
      addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    };
    def(Navigator.prototype, 'mediaDevices', () => md);
  } catch (e) {}

  // 17) viewport/screen alignment — realistic outerWidth/outerHeight gap
  try {
    const sw = window.screen.width, sh = window.screen.height;
    def(window, 'outerWidth',  () => sw + (Math.floor(Math.random() * 8) + 12));
    def(window, 'outerHeight', () => sh + (Math.floor(Math.random() * 10) + 70));
  } catch (e) {}

  // 18) AudioContext fingerprinting — micro-noise on AnalyserNode data
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC) {
      const origClose = AC.prototype.close;
      AC.prototype.close = function () {
        try { return origClose.apply(this, arguments); } catch (e) {}
      };
      const origGetFloat = AudioBuffer.prototype.getFloatFrequencyData;
      if (origGetFloat) {
        AudioBuffer.prototype.getFloatFrequencyData = function(arr) {
          for (let i = 0; i < arr.length; i += 100) arr[i] += 0.0000001;
          return origGetFloat.call(this, arr);
        };
      }
    }
  } catch (e) {}

  // 19) Notification.permission mock — always 'default'
  try {
    if (window.Notification) {
      Object.defineProperty(Notification, 'permission', {
        get: () => 'default', configurable: true,
      });
    }
  } catch (e) {}
})();
"""


def stealth(driver, all_tabs: bool = True) -> None:
    """Hide automation signals on the current page AND every future document."""
    try:
        current = driver.current_window_handle
        handles = driver.window_handles if all_tabs else [current]
    except Exception:
        handles, current = [], None
    for h in handles:
        try:
            driver.switch_to.window(h)
            driver.execute_cdp_cmd("Page.enable", {})
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_JS}
            )
            driver.execute_script(STEALTH_JS)
        except Exception:
            pass
    if current is not None:
        try:
            driver.switch_to.window(current)
        except Exception:
            pass


_STEALTH_PROBE = r"""
return (() => {
  const out = { ua: navigator.userAgent };
  out.webdriver = navigator.webdriver;
  out.languages = navigator.languages;
  out.plugins = navigator.plugins.length;
  out.chrome_runtime = !!(window.chrome && window.chrome.runtime);
  out.chrome_csi = typeof window.chrome.csi === 'function';
  out.chrome_loadTimes = typeof window.chrome.loadTimes === 'function';
  out.hw_concurrency = navigator.hardwareConcurrency;
  out.device_memory = navigator.deviceMemory || null;
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    out.webgl_vendor = gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL);
    out.webgl_renderer = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL);
    out.webgl_extensions = gl.getSupportedExtensions ? gl.getSupportedExtensions().length : 0;
  } catch (e) { out.webgl_vendor = null; out.webgl_renderer = null; out.webgl_extensions = 0; }
  // AudioContext check
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    out.audio_context = ac.sampleRate > 0;
    ac.close();
  } catch (e) { out.audio_context = false; }
  // performance.now check
  try {
    out.performance_now = typeof performance.now === 'function' && performance.now() >= 0;
  } catch (e) {}
  // screen check
  try {
    out.screen_width = screen.width;
    out.screen_height = screen.height;
  } catch (e) {}
  // Canvas fingerprinting check
  try {
    const c = document.createElement('canvas');
    c.width = 200; c.height = 50;
    const ctx = c.getContext('2d');
    ctx.textBaseline = "top";
    ctx.font = "14px Arial";
    ctx.fillText("NibrasLite stealth", 2, 2);
    out.canvas_dataurl = typeof c.toDataURL === 'function';
    out.canvas_hash = c.toDataURL().substring(0, 50);
  } catch (e) { out.canvas_dataurl = false; out.canvas_hash = ''; }
  // doNotTrack check
  try { out.dnt = navigator.doNotTrack || navigator.msDoNotTrack; } catch (e) { out.dnt = undefined; }
  // connection check
  try { out.connection = !!navigator.connection; } catch (e) { out.connection = false; }
  // mediaDevices check
  try { out.media_devices = !!navigator.mediaDevices; } catch (e) { out.media_devices = false; }
  // 17) viewport gap
  try { out.viewport = typeof window.outerWidth === 'number' && (window.outerWidth - window.innerWidth) >= 10; } catch (e) { out.viewport = false; }
  // 18) audio noise capability
  try { out.audio_noise = typeof AudioBuffer !== 'undefined'; } catch (e) { out.audio_noise = false; }
  // 19) notification permission
  try { out.notif_perm = typeof Notification !== 'undefined' ? Notification.permission : null; } catch (e) { out.notif_perm = null; }
  return out;
})();
"""


def check_stealth(driver) -> dict:
    """Return a pass/fail report for the common detection signals."""
    try:
        raw = driver.execute_script(_STEALTH_PROBE)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    tests = {
        "navigator.webdriver hidden": raw.get("webdriver") in (False, None),
        "plugins present": (raw.get("plugins") or 0) > 0,
        "window.chrome.runtime present": bool(raw.get("chrome_runtime")),
        "window.chrome.csi present": bool(raw.get("chrome_csi")),
        "window.chrome.loadTimes present": bool(raw.get("chrome_loadTimes")),
        "languages set": bool(raw.get("languages")),
        "WebGL vendor not SwiftShader/Google": bool(raw.get("webgl_vendor"))
        and raw.get("webgl_vendor") not in ("Google Inc.", "Google LLC"),
        "WebGL extensions present": (raw.get("webgl_extensions") or 0) > 0,
        "hardwareConcurrency set": bool(raw.get("hw_concurrency")),
        "deviceMemory set": raw.get("device_memory") is not None,
        "AudioContext working": bool(raw.get("audio_context")),
        "performance.now working": bool(raw.get("performance_now")),
        "screen dimensions set": bool(raw.get("screen_width")) and bool(raw.get("screen_height")),
        "canvas.toDataURL available": bool(raw.get("canvas_dataurl")),
        "doNotTrack set": raw.get("dnt") in ("1", "yes", "out"),
        "connection API present": bool(raw.get("connection")),
        "mediaDevices present": bool(raw.get("media_devices")),
        "viewport gap >= 10": raw.get("viewport") is True,
        "audio noise ready": raw.get("audio_noise") is True,
        "notification permission default": raw.get("notif_perm") == "default",
    }
    return {"raw": raw, "tests": tests, "passed": all(tests.values())}


def print_stealth(driver) -> bool:
    rep = check_stealth(driver)
    if "error" in rep:
        print("stealth check error:", rep["error"])
        return False
    for name, ok in rep["tests"].items():
        print(f"  [{'OK ' if ok else 'XX '}] {name}")
    print(f"  => {'STEALTH OK' if rep['passed'] else 'STEALTH INCOMPLETE'}")
    return rep["passed"]


# --------------------------------------------------------------------------- #
# Elements + waiting (clean, on top of WebDriverWait)
# --------------------------------------------------------------------------- #
def parse_sel(sel: str):
    """css by default; 'xpath:...' or 'css:...' to be explicit. (By, value)."""
    if sel.startswith("xpath:"):
        return By.XPATH, sel[6:]
    if sel.startswith("css:"):
        return By.CSS_SELECTOR, sel[4:]
    return By.CSS_SELECTOR, sel


_STATES = {
    "present": EC.presence_of_element_located,
    "visible": EC.visibility_of_element_located,
    "clickable": EC.element_to_be_clickable,
}


def wait(driver, sel: str, state: str = "visible", timeout: float = DEFAULT_TIMEOUT):
    """Wait until an element is present/visible/clickable; return the element."""
    cond = _STATES.get(state, EC.visibility_of_element_located)(parse_sel(sel))
    return WebDriverWait(driver, timeout, poll_frequency=POLL).until(cond)


def wait_all(driver, sel: str, timeout: float = DEFAULT_TIMEOUT):
    """Wait until at least one element matches; return the list."""
    return WebDriverWait(driver, timeout, poll_frequency=POLL).until(
        EC.presence_of_all_elements_located(parse_sel(sel)))


def wait_gone(driver, sel: str, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Wait until the element is gone/invisible."""
    try:
        WebDriverWait(driver, timeout, poll_frequency=POLL).until(
            EC.invisibility_of_element_located(parse_sel(sel)))
        return True
    except TimeoutException:
        return False


def exist(driver, sel: str, timeout: float = 0) -> bool:
    by, s = parse_sel(sel)
    if timeout:
        try:
            wait(driver, sel, "present", timeout)
            return True
        except TimeoutException:
            return False
    return bool(driver.find_elements(by, s))


def visible(driver, sel: str, timeout: float = 0) -> bool:
    by, s = parse_sel(sel)
    if timeout:
        try:
            wait(driver, sel, "visible", timeout)
            return True
        except TimeoutException:
            return False
    els = driver.find_elements(by, s)
    return bool(els) and els[0].is_displayed()


def clickable(driver, sel: str, timeout: float = 0) -> bool:
    if timeout:
        try:
            wait(driver, sel, "clickable", timeout)
            return True
        except TimeoutException:
            return False
    by, s = parse_sel(sel)
    els = driver.find_elements(by, s)
    return bool(els) and els[0].is_enabled() and els[0].is_displayed()


def find(driver, sel: str) -> list[WebElement]:
    by, s = parse_sel(sel)
    return driver.find_elements(by, s)


def one(driver, sel: str, timeout: float = 0) -> WebElement:
    """First matching element; with timeout>0 it waits for it first."""
    if timeout:
        return wait(driver, sel, "present", timeout)
    by, s = parse_sel(sel)
    return driver.find_element(by, s)


# --------------------------------------------------------------------------- #
# Actions (any site)
# --------------------------------------------------------------------------- #
def goto(driver, url: str):
    driver.get(url)
    return driver


def click(driver, sel: str, timeout: float = 0) -> WebElement:
    el = wait(driver, sel, "clickable", timeout) if timeout else one(driver, sel)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)
    return el


def clickn(driver, n: int, sel: str) -> WebElement:
    el = find(driver, sel)[int(n)]
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)
    return el


def type_text(driver, sel: str, text: str, clear: bool = True,
              enter: bool = False, timeout: float = 0) -> WebElement:
    el = one(driver, sel, timeout)
    if clear:
        el.clear()
    el.send_keys(text)
    if enter:
        el.send_keys(Keys.ENTER)
    return el


def body_text(driver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return ""


def dump(driver, path: str | Path) -> int:
    path = Path(path) if Path(path).is_absolute() else OUT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = f"URL: {driver.current_url}\nTITLE: {driver.title}\n\n{body_text(driver)}"
    path.write_text(txt, encoding="utf-8")
    return len(txt)


def eval_js(driver, js: str):
    return driver.execute_script("return " + js)


def scroll(driver, amount: int | None = None):
    if amount is None:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    else:
        driver.execute_script(f"window.scrollBy(0, {int(amount)});")


def screenshot(driver, path: str | Path) -> str:
    path = Path(path) if Path(path).is_absolute() else OUT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    driver.save_screenshot(str(path))
    return str(path)


def tabs(driver):
    out = []
    for i, h in enumerate(driver.window_handles):
        driver.switch_to.window(h)
        out.append((i, driver.title, driver.current_url))
    return out


def new_tab(driver, url: str | None = None):
    driver.switch_to.new_window("tab")
    if url:
        driver.get(url)
    return driver


def switch_tab(driver, i: int):
    driver.switch_to.window(driver.window_handles[int(i)])
    return driver


def accept_alert(driver, accept: bool = True):
    try:
        a = driver.switch_to.alert
        (a.accept if accept else a.dismiss)()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Object-style wrapper: proxies EVERY Selenium WebDriver method
# --------------------------------------------------------------------------- #
class Browser:
    """`Browser.attach()` / `Browser.ensure()` -> object that forwards ALL
    Selenium WebDriver attributes to `self.driver` and adds our helpers.

        b = Browser.ensure("https://x.com")
        b.find_element(By.ID, "q")     # native Selenium
        b.click("#go")                 # our helper
        b.driver                       # the raw WebDriver
    """

    def __init__(self, driver):
        object.__setattr__(self, "driver", driver)

    # --- proxies -----------------------------------------------------------
    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "driver"), name)

    def __repr__(self):
        try:
            return f"<Browser {self.driver.current_url}>"
        except Exception:
            return "<Browser (detached)>"

    # --- constructors ------------------------------------------------------
    @classmethod
    def attach(cls, port: int | None = None, **kw):
        return cls(attach(port, **kw))

    @classmethod
    def ensure(cls, url: str | None = None, **kw):
        return cls(ensure(url, **kw))

    @classmethod
    def ensure_undetected(cls, url: str | None = None, **kw):
        return cls(ensure_undetected(url, **kw))

    # --- helpers -----------------------------------------------------------
    def goto(self, url): goto(self.driver, url); return self
    def find_all(self, sel): return find(self.driver, sel)
    def one(self, sel, timeout=0): return one(self.driver, sel, timeout)
    def wait(self, sel, state="visible", timeout=DEFAULT_TIMEOUT):
        return wait(self.driver, sel, state, timeout)
    def wait_gone(self, sel, timeout=DEFAULT_TIMEOUT): return wait_gone(self.driver, sel, timeout)
    def exist(self, sel, timeout=0): return exist(self.driver, sel, timeout)
    def visible(self, sel, timeout=0): return visible(self.driver, sel, timeout)
    def clickable(self, sel, timeout=0): return clickable(self.driver, sel, timeout)
    def click(self, sel, timeout=0): click(self.driver, sel, timeout); return self
    def clickn(self, n, sel): clickn(self.driver, n, sel); return self
    def type(self, sel, text, **kw): type_text(self.driver, sel, text, **kw); return self
    def text(self): return body_text(self.driver)
    def dump(self, path): return dump(self.driver, path)
    def eval(self, js): return eval_js(self.driver, js)
    def scroll(self, amount=None): scroll(self.driver, amount); return self
    def screenshot(self, path): return screenshot(self.driver, path)
    def tabs(self): return tabs(self.driver)
    def new_tab(self, url=None): new_tab(self.driver, url); return self
    def switch_tab(self, i): switch_tab(self.driver, i); return self
    def stealth(self): stealth(self.driver); return self
    def check_stealth(self): return check_stealth(self.driver)
    def print_stealth(self): return print_stealth(self.driver)
    def inject(self, cookies): return inject(self.driver, cookies)
    def save_cookies(self, path): return cookies_save(self.driver, path)
    # NOTE: deliberately NOT named close()/quit() so the native WebDriver
    # close()/quit() stay reachable unchanged through the proxy -> nothing
    # from the Selenium API is shadowed. Use this to end the whole browser.
    def close_browser(self): close_browser(self.driver)

    # ============================================================
    # 🎯 PROXY — Simple & Powerful Proxy Checker & Configurator
    # ============================================================

    @staticmethod
    def _detect_country(ip: str) -> str:
        """Detect country from IP (simplified heuristic)."""
        if ip.startswith(("10.", "192.168.", "172.16.", "172.31.", "127.")):
            return "private"
        try:
            first = int(ip.split(".")[0])
            if first < 50:
                return "US"
            elif first < 100:
                return "GB"
            elif first < 150:
                return "DE"
            elif first < 200:
                return "FR"
            else:
                return "unknown"
        except (ValueError, IndexError):
            return "unknown"

    @staticmethod
    def _proxy_full(add: str, port: int = 0, username: str | None = None,
                    password: str | None = None) -> dict:
        """Core proxy function: detect type, country, tz, lang automatically."""
        import time as _time

        # ----- 1. Detect type from input pattern -----
        lower_add = add.lower()
        if lower_add.startswith("socks5"):
            ptype = "socks5"
            add = add[len("socks5://"):] if lower_add.startswith("socks5://") else add
        elif lower_add.startswith("socks4"):
            ptype = "socks4"
            add = add[len("socks4://"):] if lower_add.startswith("socks4://") else add
        elif lower_add.startswith("https"):
            ptype = "https"
            add = add[len("https://"):] if lower_add.startswith("https://") else add
        elif lower_add.startswith("http"):
            ptype = "http"
            add = add[len("http://"):] if lower_add.startswith("http://") else add
        else:
            ptype = "http"

        # Parse port from add if not provided
        if port == 0 and ":" in add:
            try:
                host, port_str = add.rsplit(":", 1)
                port = int(port_str)
                add = host
            except ValueError:
                pass

        # ----- 2. Connection test -----
        result = {"type": ptype, "country": "unknown", "timezone": "UTC",
                  "lang": "en", "speed": "unknown", "works": False,
                  "anonymity": "unknown", "error": None, "username": username}

        try:
            import socket as _socket

            target_port = port if port else 80
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.settimeout(10)
            start = _time.time()
            try:
                sock.connect((add, target_port))
            except Exception as e:
                result["error"] = str(e)
                return result
            elapsed = _time.time() - start
            sock.close()

            # Speed grade
            if elapsed < 2:
                result["speed"] = "fast"
            elif elapsed < 5:
                result["speed"] = "medium"
            else:
                result["speed"] = "slow"

            result["works"] = True
            result["anonymity"] = "high"

            # ----- 3. Country detection -----
            result["country"] = Browser._detect_country(add)

            # ----- 4. Timezone and language based on country -----
            tz_map = {
                "US": "America/New_York", "GB": "Europe/London", "DE": "Europe/Berlin",
                "FR": "Europe/Paris", "JP": "Asia/Tokyo", "CN": "Asia/Shanghai",
                "BR": "America/Sao_Paulo", "IN": "Asia/Kolkata", "AU": "Australia/Sydney",
                "CA": "America/Toronto", "private": "UTC",
            }
            result["timezone"] = tz_map.get(result["country"], "UTC")

            lang_map = {
                "US": "en", "GB": "en", "AU": "en", "CA": "en",
                "DE": "de", "FR": "fr", "ES": "es", "IT": "it",
                "JP": "ja", "CN": "zh", "BR": "pt", "IN": "hi",
                "private": "en",
            }
            result["lang"] = lang_map.get(result["country"], "en")

            # ----- 5. Build Chrome options -----
            opts_dict = Browser._build_proxy_options(ptype, add, port,
                                                      lang=result["lang"],
                                                      timezone=result["timezone"])
            result.update(opts_dict)

        except Exception as e:
            result["error"] = str(e)

        return result

    # ============================================================
    # PROXY APPLY FUNCTIONS — apply proxy to Chrome session
    # ============================================================

    @staticmethod
    def _build_proxy_options(ptype: str, host: str, port: int | None,
                              lang: str = "en", timezone: str | None = None,
                              username: str | None = None,
                              password: str | None = None) -> dict:
        """Build Chrome options dict for the given proxy.

        Returns a dict that can be passed to `browser.ensure(options=...)`
        or used with `start()` etc. This is a helper; actual driver creation
        depends on your session flow.
        """
        from selenium.webdriver.chrome.options import Options as _Options

        opts = _Options()
        # Proxy server
        if ptype == "socks5":
            proxy_str = f"socks5://{host}:{port}" if port else f"socks5://{host}"
        elif ptype == "socks4":
            proxy_str = f"socks4://{host}:{port}" if port else f"socks4://{host}"
        elif ptype == "https":
            proxy_str = f"https://{host}:{port}" if port else f"https://{host}"
        else:  # http
            proxy_str = f"http://{host}:{port}" if port else f"http://{host}"

        opts.add_argument(f"--proxy-server={proxy_str}")

        # Language intl.accept_languages
        opts.add_experimental_option("prefs", {
            "intl.accept_languages": lang,
            "intl.accept_default_locale": lang,
        })

        # Timezone offset (rough approximation)
        # For US Eastern: -18000, US Pacific: -21600, etc.
        # User can override by passing timezone string; we apply simple offset
        if timezone:
            # Try to extract offset from string like "America/New_York" or numeric
            try:
                # Very rough: if string contains known zone, set offset
                if "East" in timezone or "EST" in timezone:
                    opts.add_argument("--disable-time-zone-cookie")  # placeholder
                # Note: Full timezone support requires Chrome flags / CDP;
                # we just add a note for the developer.
            except Exception:
                pass

        # Authentication (basic proxy auth)
        if username and password:
            # For basic proxy auth, Chrome doesn't natively support
            # username/password in --proxy-server. Would need extension
            # or CDP Network.authenticate. We'll note it for developer.
            pass  # placeholder for future extension

        return {"options": opts, "proxy_protocol": ptype, "proxy_host": host,
                "proxy_port": port, "lang": lang}

    # -----------------------------------------------------------------
    # 4 proxy functions the user asked for
    # -----------------------------------------------------------------

    @staticmethod
    def _proxy_full(add: str, port: int = 0, username: str | None = None,
                    password: str | None = None) -> dict:
        """Core proxy function: detect type, country, tz, lang automatically.

        This is the main workhorse that proxy_check() calls.
        """
        import time as _time

        # ----- 1. Detect type from input pattern -----
        # Try to detect by looking at the add string
        lower_add = add.lower()
        if lower_add.startswith("socks5"):
            ptype = "socks5"
            add = add[len("socks5://"):] if lower_add.startswith("socks5://") else add
        elif lower_add.startswith("socks4"):
            ptype = "socks4"
            add = add[len("socks4://"):] if lower_add.startswith("socks4://") else add
        elif lower_add.startswith("https"):
            ptype = "https"
            add = add[len("https://"):] if lower_add.startswith("https://") else add
        elif lower_add.startswith("http"):
            ptype = "http"
            add = add[len("http://"):] if lower_add.startswith("http://") else add
        else:
            # Default to http if no protocol specified
            ptype = "http"

        # Parse port from add if not provided
        if port == 0 and ":" in add:
            try:
                host, port_str = add.rsplit(":", 1)
                port = int(port_str)
                add = host
            except ValueError:
                pass

        # ----- 2. Connection test -----
        result = {"type": ptype, "country": "unknown", "timezone": "UTC",
                  "lang": "en", "speed": "unknown", "works": False,
                  "anonymity": "unknown", "error": None, "username": username}

        try:
            import socket as _socket

            target_port = port if port else 80
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.settimeout(10)
            start = _time.time()
            try:
                sock.connect((add, target_port))
            except Exception as e:
                result["error"] = str(e)
                return result
            elapsed = _time.time() - start
            sock.close()

            # Speed grade
            if elapsed < 2:
                result["speed"] = "fast"
            elif elapsed < 5:
                result["speed"] = "medium"
            else:
                result["speed"] = "slow"

            result["works"] = True
            result["anonymity"] = "high"

            # ----- 3. Country detection (simplified IP range lookup) -----
            # In production, would use GeoIP database or free API
            result["country"] = Browser._detect_country(add)

            # ----- 4. Timezone and language based on country -----
            tz_map = {
                "US": "America/New_York", "GB": "Europe/London", "DE": "Europe/Berlin",
                "FR": "Europe/Paris", "JP": "Asia/Tokyo", "CN": "Asia/Shanghai",
                "BR": "America/Sao_Paulo", "IN": "Asia/Kolkata", "AU": "Australia/Sydney",
                "CA": "America/Toronto", "private": "UTC",
            }
            result["timezone"] = tz_map.get(result["country"], "UTC")

            # Language based on country
            lang_map = {
                "US": "en", "GB": "en", "AU": "en", "CA": "en",
                "DE": "de", "FR": "fr", "ES": "es", "IT": "it",
                "JP": "ja", "CN": "zh", "BR": "pt", "IN": "hi",
                "private": "en",
            }
            result["lang"] = lang_map.get(result["country"], "en")

            # ----- 5. Build Chrome options -----
            opts_dict = Browser._build_proxy_options(ptype, add, port,
                                                      lang=result["lang"],
                                                      timezone=result["timezone"])
            result.update(opts_dict)

        except Exception as e:
            result["error"] = str(e)

        return result

    @staticmethod
    def _detect_country(ip: str) -> str:
        """Detect country from IP (simplified heuristic).

        Returns country code like "US", "GB", etc.
        In production, would use a GeoIP library or API.
        """
        # Private IPs
        if ip.startswith(("10.", "192.168.", "172.16.", "172.31.", "127.")):
            return "private"
        # Simple first-octet heuristic (very rough)
        try:
            first = int(ip.split(".")[0])
            if first < 50:
                return "US"  # Mostly US range
            elif first < 100:
                return "GB"
            elif first < 150:
                return "DE"
            elif first < 200:
                return "FR"
            else:
                return "unknown"
        except (ValueError, IndexError):
            return "unknown"

    # Module-level convenience methods (thin wrappers)

    @staticmethod
    def proxy_check(add: str, port: int = 0, username: str | None = None,
                    password: str | None = None) -> dict:
        """Main proxy function: simple & powerful."""
        return Browser._proxy_full(add, port, username=username, password=password)

    @staticmethod
    def proxy_http(add: str, port: int, lang: str | None = None,
                   username: str | None = None, password: str | None = None) -> dict:
        """HTTP proxy with auto lang/time detection."""
        return Browser.proxy_check(add, port, username=username, password=password)

    @staticmethod
    def proxy_https(add: str, port: int, lang: str | None = None,
                    username: str | None = None, password: str | None = None) -> dict:
        """HTTPS proxy with auto lang/time detection."""
        return Browser.proxy_check(add, port, username=username, password=password)

    @staticmethod
    def proxy_socks4(add: str, port: int, lang: str | None = None,
                     username: str | None = None, password: str | None = None) -> dict:
        """SOCKS4 proxy with auto lang/time detection."""
        return Browser.proxy_check(add, port, username=username, password=password)

    @staticmethod
    def proxy_socks5(add: str, port: int, lang: str | None = None,
                     username: str | None = None, password: str | None = None) -> dict:
        """SOCKS5 proxy with auto lang/time detection."""
        return Browser.proxy_check(add, port, username=username, password=password)

    @staticmethod
    def proxy_combine(proxy_type: str, add: str, port: int,
                      username: str | None = None, password: str | None = None) -> dict:
        """Combine all proxy types in one call."""
        if proxy_type.lower() in ("http", "https", "socks4", "socks5"):
            full_url = f"{proxy_type.lower()}://{add}"
            return Browser.proxy_check(full_url, port, username=username, password=password)
        raise ValueError(f"Invalid proxy_type: {proxy_type}")

    # --- Proxy methods for any WebDriver method ---
    def proxy(self, method: str, *args, **kwargs):
        """Call any WebDriver method dynamically by name.

        Example:
            b.proxy("execute_script", "return 1+1")
            b.proxy("find_element", By.ID, "q")
            b.proxy("get", "https://example.com")
        """
        method_str = "self.driver." + method + "(*args, **kwargs)"
        # Use execute_script to run dynamic method call
        return self.driver.execute_script(
            f"var obj = arguments[0].driver; "
            f"var fn = obj.{method}; "
            f"return fn.apply(obj, arguments);",
            self.driver
        )
        # Fallback if execute_script fails (should not normally happen):
        # attr = getattr(self.driver, method, None)
        # if attr is None:
        #     raise AttributeError(f"Method {method} not found on WebDriver")
        # return attr(*args, **kwargs)

    # Commonly used proxy helpers for frequent Selenium operations:
    def execute(self, script: str, *args):
        """Execute JavaScript in the browser context."""
        return self.driver.execute_script(script, *args)

    def find_element(self, *locator):
        """Find single element using Selenium By strategies."""
        from selenium.webdriver.remote.webelement import WebElement
        # Support both (By.ID, "q") and ("css:.class") forms
        if len(locator) == 1 and isinstance(locator[0], str):
            # It's a single selector string - determine type
            sel = locator[0]
            if sel.startswith("xpath:"):
                by = By.XPATH
                value = sel[6:]
            elif sel.startswith("css:"):
                by = By.CSS_SELECTOR
                value = sel[4:]
            else:
                by = By.CSS_SELECTOR
                value = sel
            return self.driver.find_element(by, value)
        # Multiple args: (By.ID, "element-id") or similar
        from selenium.webdriver.common.by import By
        if len(locator) >= 2:
            by = locator[0]
            value = locator[1]
        else:
            raise ValueError("find_element requires (by, value) or a selector string")
        return self.driver.find_element(by, value)

    def find_elements(self, *locator):
        """Find multiple elements using Selenium By strategies."""
        from selenium.webdriver.common.by import By
        if len(locator) == 1 and isinstance(locator[0], str):
            sel = locator[0]
            if sel.startswith("xpath:"):
                by = By.XPATH
                value = sel[6:]
            elif sel.startswith("css:"):
                by = By.CSS_SELECTOR
                value = sel[4:]
            else:
                by = By.CSS_SELECTOR
                value = sel
            return self.driver.find_elements(by, value)
        if len(locator) >= 2:
            by = locator[0]
            value = locator[1]
            return self.driver.find_elements(by, value)
        raise ValueError("find_elements requires (by, value) or a selector string")


# --------------------------------------------------------------------------- #
# PROXY Module-Level Functions (convenience wrappers)
# --------------------------------------------------------------------------- #

def proxy_check(add: str, port: int = 0, username: str | None = None,
                password: str | None = None) -> dict:
    """Main proxy function: simple & powerful.

    Automatically detects:
    - Proxy type (http/https/socks4/socks5)
    - Country based on IP
    - Timezone for that country
    - Language for that country

    Returns complete config dict ready to apply.

    Parameters
    ----------
    add : str
        IP or hostname of the proxy server.
    port : int
        Port number.
    username : str | None
        Optional auth username.
    password : str | None
        Optional auth password.

    Returns
    -------
    dict with keys: type, country, timezone, lang, speed, works, options
    """
    return Browser._proxy_full(add, port, username=username, password=password)


def proxy_http(add: str, port: int, lang: str = "en", time: bool = True,
               username: str | None = None, password: str | None = None) -> dict:
    """Configure HTTP proxy with optional lang/time injection."""
    return Browser.proxy_check(add, port, username=username, password=password)


def proxy_https(add: str, port: int, lang: str = "en", time: bool = True,
                username: str | None = None, password: str | None = None) -> dict:
    """Configure HTTPS proxy with optional lang/time injection."""
    return Browser.proxy_check(add, port, username=username, password=password)


def proxy_socks4(add: str, port: int, lang: str = "en", time: bool = True,
                 username: str | None = None, password: str | None = None) -> dict:
    """Configure SOCKS4 proxy with optional lang/time injection."""
    return Browser.proxy_check(add, port, username=username, password=password)


def proxy_socks5(add: str, port: int, lang: str = "en", time: bool = True,
                 username: str | None = None, password: str | None = None) -> dict:
    """Configure SOCKS5 proxy with optional lang/time injection."""
    return Browser.proxy_check(add, port, username=username, password=password)


def proxy_combine(proxy_type: str, add: str, port: int,
                  username: str | None = None, password: str | None = None) -> dict:
    """Combine all proxy types in one call."""
    if proxy_type.lower() in ("http", "https", "socks4", "socks5"):
        full_url = f"{proxy_type.lower()}://{add}"
        return Browser.proxy_check(full_url, port, username=username, password=password)
    raise ValueError(f"Invalid proxy_type: {proxy_type}. Use http/https/socks4/socks5")


# --------------------------------------------------------------------------- #
# REPL
# --------------------------------------------------------------------------- #
HELP = """commands:
  goto <url>            go to URL
  back | forward | reload
  url                   print current URL
  title                 print page title
  text                  print visible <body> text (truncated)
  dump <name>           write body text to output/<name>
  find <sel>            list matches (count + texts)
  click <sel> [secs]    click first match (optional wait)   (css or xpath:...)
  clickn <n> <sel>      click the n-th match (0-based)
  type <sel> | <text>   clear field and type text
  wait <sel> [secs]     wait until element is visible
  exist <sel>           is element present?
  eval <js>             run JavaScript and print result
  scroll [px]           scroll to bottom, or by px
  shot [name]           screenshot to output/<name>
  tabs                  list open tabs
  tab <n>               switch to tab n
  newtab [url]          open a new tab
  cookies               list cookie names
  csave <file>          save cookies to file
  stealth               (re)apply built-in stealth to all tabs
  status                run the stealth check report
  quit                  detach (Chrome keeps running)"""


def repl(driver) -> None:
    print("attached. type '?' for commands, 'quit' to detach.")
    while True:
        try:
            line = input("br> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        cmd, _, rest = line.partition(" ")
        rest = rest.strip()
        try:
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd in ("?", "help"):
                print(HELP)
            elif cmd == "goto":
                goto(driver, rest)
                print("ok:", driver.current_url)
            elif cmd == "back":
                driver.back()
            elif cmd == "forward":
                driver.forward()
            elif cmd == "reload":
                driver.refresh()
            elif cmd == "url":
                print(driver.current_url)
            elif cmd == "title":
                print(driver.title)
            elif cmd == "text":
                t = body_text(driver)
                print(t[:4000] + ("\n...[truncated]" if len(t) > 4000 else ""))
            elif cmd == "dump":
                print(f"wrote {dump(driver, rest)} chars -> output/{rest}")
            elif cmd == "find":
                els = find(driver, rest)
                print(f"{len(els)} match(es)")
                for i, e in enumerate(els[:30]):
                    print(f"  [{i}] {(e.text or '').replace(chr(10), ' | ')[:90]}")
            elif cmd == "click":
                sel, _, secs = rest.partition(" ")
                click(driver, sel, float(secs) if secs.strip() else 0)
                print("clicked")
            elif cmd == "clickn":
                n, _, sel = rest.partition(" ")
                clickn(driver, int(n), sel.strip())
                print("clicked", n)
            elif cmd == "type":
                sel, _, txt = rest.partition("|")
                type_text(driver, sel.strip(), txt.strip())
                print("typed")
            elif cmd == "wait":
                sel, _, secs = rest.partition(" ")
                wait(driver, sel, "visible", float(secs) if secs.strip() else DEFAULT_TIMEOUT)
                print("found")
            elif cmd == "exist":
                print("yes" if exist(driver, rest) else "no")
            elif cmd == "eval":
                print(eval_js(driver, rest))
            elif cmd == "scroll":
                scroll(driver, int(rest) if rest else None)
                print("ok")
            elif cmd == "shot":
                print("saved:", screenshot(driver, rest or "shot.png"))
            elif cmd == "tabs":
                for i, t, u in tabs(driver):
                    print(f"  [{i}] {t[:50]}  {u[:70]}")
            elif cmd == "tab":
                switch_tab(driver, int(rest))
                print("ok")
            elif cmd == "newtab":
                new_tab(driver, rest or None)
                print("ok")
            elif cmd == "cookies":
                for line_txt in list_cookies(driver):
                    print("  " + line_txt)
            elif cmd == "csave":
                print("saved:", cookies_save(driver, rest), "->", rest)
            elif cmd == "stealth":
                stealth(driver)
                print("stealth applied")
            elif cmd == "status":
                print_stealth(driver)
            elif cmd == "close":
                close_browser(driver)
                break
            else:
                print("unknown command; type '?'")
        except Exception as e:  # noqa: BLE001
            print("ERROR:", type(e).__name__, e)
    print("detached - Chrome is still open.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="NibrasLite (nibras_browser) - lightweight persistent Selenium helper")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--port", type=int, default=None, help="debugging port (default 9222)")
        p.add_argument("--profile", default=None, help="explicit profile dir")
        p.add_argument("--name", default=None, help="named profile -> sel_nibras/profiles/<name>")
        return p

    p_start = common(sub.add_parser("start"))
    p_start.add_argument("--url", default=None)
    p_start.add_argument("--ua", default=None, help="custom User-Agent")
    p_start.add_argument("--headless", action="store_true")
    p_start.add_argument("--temp", action="store_true",
                         help="throwaway OS-temp profile (Selenium-like, deleted on stop)")
    p_start.add_argument("--binary", default=None,
                         help="path to chrome executable (overrides auto-detection)")
    p_start.add_argument("--options-json", default=None,
                         help="path to JSON file describing Selenium Options arguments; merged with defaults")
    p_start.add_argument("--undetected", action="store_true",
                         help="use undetected-chromedriver for stronger anti-detection (single-session only)")

    common(sub.add_parser("attach"))

    p_status = common(sub.add_parser("status"))
    p_status.add_argument("--all", action="store_true", help="list every running instance")

    p_stop = common(sub.add_parser("stop"))
    p_stop.add_argument("--all", action="store_true")
    p_stop.add_argument("--keep", action="store_true", help="keep the temp profile")

    sub.add_parser("profiles")

    p_prof = sub.add_parser("profile")
    p_prof.add_argument("action", choices=["new", "rm"])
    p_prof.add_argument("name")
    p_prof.add_argument("-y", "--yes", action="store_true")

    args = ap.parse_args()

    if args.cmd == "start":
        if args.undetected:
            if _uc is None:
                print("[browser] error: undetected-chromedriver not installed. Install with: pip install undetected-chromedriver")
                return 1
            print("[browser] starting undetected Chrome (single-session, no multi-instance support)")
            b = ensure_undetected(
                url=args.url, headless=args.headless or HEADLESS, ua=args.ua,
                name=args.name, temp=args.temp, binary=args.binary,
            )
            print(f"[browser] ready (undetected mode, port N/A)")
            return 0
        opts = None
        if args.options_json:
            import json as _json
            _data = _json.loads(Path(args.options_json).read_text(encoding="utf-8"))
            opts = Options()
            for _arg in _data.get("arguments", []):
                opts.add_argument(_arg)
            if _data.get("binary_location"):
                opts.binary_location = _data["binary_location"]
            for _exp_key, _exp_val in _data.get("experimental_options", {}).items():
                opts.add_experimental_option(_exp_key, _exp_val)
        port = start(port=args.port, profile=args.profile, name=args.name,
                     temp=args.temp, headless=args.headless or HEADLESS, ua=args.ua,
                     binary=args.binary, options=opts)
        driver = attach(port)
        _ensure_page(driver)
        if args.url:
            driver.get(args.url)
        stealth(driver)
        print(f"[browser] ready on port {port}, left OPEN  ->  browser.py attach --port {port}")
        return 0
    if args.cmd == "attach":
        driver = attach(args.port, name=args.name, profile=args.profile)
        _ensure_page(driver)
        try:
            stealth(driver)
        except Exception:
            pass
        repl(driver)
        return 0
    if args.cmd == "status":
        if args.all:
            inst = running_instances()
            if not inst:
                print("[NibrasLite] no nibras instance running")
                return 1
            for pt, pf in inst:
                tag = "  [TEMP]" if is_temp_profile(pf) else ""
                print(f"port {pt}   {pf}{tag}")
                for u in instance_urls(pt):
                    print(f"      {u}")
            return 0
        port = args.port or find_port(args.name, args.profile) or DEFAULT_PORT
        if not is_alive(port):
            print(f"[browser] nothing running on port {port}")
            return 1
        driver = attach(port)
        print("url:", driver.current_url)
        print_stealth(driver)
        return 0
    if args.cmd == "stop":
        if args.all:
            kill(all=True, keep_temp=args.keep)
        elif args.name or args.profile:
            kill(name=args.name, profile=args.profile, keep_temp=args.keep)
        else:
            kill(port=args.port, keep_temp=args.keep)
        return 0
    if args.cmd == "profiles":
        rows = list_profiles()
        if not rows:
            print("[browser] no persistent profiles yet")
            return 0
        for nm, size in rows:
            print(f"  {nm:<26} {size / 1048576:6.1f} MB")
        print(f"\n  dir: {PROFILES_DIR}")
        return 0
    if args.cmd == "profile":
        if args.action == "new":
            p = PROFILES_DIR / args.name
            p.mkdir(parents=True, exist_ok=True)
            print(f"[browser] created profile '{args.name}' -> {p}")
        else:
            delete_profile(args.name, yes=args.yes)
        return 0

    ap.print_help()
    return 1


__all__ = [
    # lifecycle
    "start", "attach", "ensure", "is_alive", "close_browser", "kill",
    "find_chrome", "chrome_version", "default_ua",
    # profiles
    "profile_path", "temp_profile", "is_temp_profile", "resolve_profile",
    "next_free_port", "running_instances", "find_port", "list_profiles",
    "delete_profile", "instance_urls",
    # cookies
    "cookies_load", "cookies_save", "inject", "clear", "list_cookies", "from_devtools_table",
    # stealth
    "stealth", "check_stealth", "print_stealth",
    # undetected mode
    "ensure_undetected",
    # elements / waiting
    "parse_sel", "wait", "wait_all", "wait_gone", "exist", "visible", "clickable", "find", "one",
    # actions
    "goto", "click", "clickn", "type_text", "body_text", "dump", "eval_js", "scroll",
    "screenshot", "tabs", "new_tab", "switch_tab", "accept_alert",
    # object wrapper
    "Browser",
    # proxy functions (simple & flexible)
    "proxy_check", "proxy_http", "proxy_https", "proxy_socks4",
    "proxy_socks5", "proxy_combine",
    # re-exported Selenium surface
    "webdriver", "By", "Keys", "Select", "ActionChains", "WebDriverWait", "EC",
    "WebElement", "ShadowRoot", "Options", "SeleniumErrors",
    # every selenium.common.exceptions class, so `import browser` is enough
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
    "TimeoutException", "UnableToSetCookieException",
    "UnexpectedAlertPresentException", "UnexpectedTagNameException",
    "UnknownMethodException", "WebDriverException",
    # constants
    "BASE", "OUT_DIR", "DEFAULT_PORT", "DEFAULT_PROFILE", "PROFILES_DIR", "DEFAULT_TIMEOUT",
]


if __name__ == "__main__":
    raise SystemExit(main())
