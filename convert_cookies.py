"""Convert a browser cookie dump into Cookie-Editor / aviso style JSON.

Input  (default): sel_nibras/new_coc.txt  (NibrasLite project)
   - DevTools -> Application -> Cookies table paste (tab separated), OR
   - JSON exported by an extension (Cookie-Editor / EditThisCookie).
Output (default): sel_nibras/session_cookies.json

Usage:
   python convert_cookies.py
   python convert_cookies.py <src.txt> <out.json>
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "new_coc.txt"
OUT = BASE / "session_cookies.json"

PRIORITIES = ("High", "Medium", "Low")
SAME_SITES = ("None", "Strict", "Lax")


def to_unix(value: str):
    """Parse an ISO-8601 devtools date to unix seconds (None for session)."""
    v = (value or "").strip()
    if not v or v.lower() in ("session", "0", "-1", "none"):
        return None
    try:
        return int(_dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def norm_samesite(raw):
    table = {
        "no_restriction": "None",
        "unspecified": "Lax",
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
    }
    if isinstance(raw, str):
        return table.get(raw.lower(), "Lax")
    return "Lax"


def from_json(text: str):
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("cookies", data.get("Cookies", []))
    cookies = []
    for c in data:
        item = {
            "domain": c.get("domain", c.get("Domain", "")),
            "httpOnly": bool(c.get("httpOnly", c.get("HttpOnly", False))),
            "name": c.get("name", c.get("Name", "")),
            "path": c.get("path", c.get("Path", "/")),
            "sameSite": norm_samesite(c.get("sameSite", c.get("SameSite"))),
            "secure": bool(c.get("secure", c.get("Secure", False))),
            "value": c.get("value", c.get("Value", "")),
        }
        exp = c.get("expiry", c.get("expirationDate", c.get("Expires")))
        if exp:
            item["expiry"] = int(float(exp))
        cookies.append(item)
    return cookies


def from_table(text: str):
    tokens = []
    for line in text.splitlines():
        tokens.extend(line.rstrip("\r").split("\t"))

    cookies = []
    i, n = 0, len(tokens)
    while i < n:
        while i < n and tokens[i] == "":
            i += 1
        if i >= n:
            break
        name = tokens[i]; i += 1
        if i >= n:
            break
        value = tokens[i]; i += 1

        # domain, path, expires, size (skip blank tokens produced by line wraps)
        fields = []
        while len(fields) < 4:
            while i < n and tokens[i] == "":
                i += 1
            if i >= n:
                break
            fields.append(tokens[i]); i += 1
        if len(fields) < 4:
            break
        domain, path, date, _size = fields

        flags = []
        while i < n and tokens[i] not in PRIORITIES:
            flags.append(tokens[i]); i += 1
        if i < n:
            i += 1  # consume priority token

        item = {
            "domain": domain,
            "httpOnly": bool(flags) and flags[0].strip() == "\u2713",
            "name": name,
            "path": path,
            "sameSite": next((f for f in flags[2:] if f in SAME_SITES), "Lax"),
            "secure": len(flags) > 1 and flags[1].strip() == "\u2713",
            "value": value,
        }
        exp = to_unix(date)
        if exp:
            item["expiry"] = exp
        cookies.append(item)
    return cookies


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT

    if not src.exists():
        print(f"[!] source not found: {src}")
        print("    put the cookie dump there, or pass a path:")
        print("    python convert_cookies.py <src.txt> <out.json>")
        return 1

    text = src.read_text(encoding="utf-8-sig")
    head = text.lstrip()[:1]
    try:
        cookies = from_json(text) if head in ("[", "{") else from_table(text)
    except Exception as exc:  # noqa: BLE001
        print(f"[!] parse failed: {exc}")
        return 1

    if not cookies:
        print("[!] no cookies parsed - check the dump format")
        return 1

    print(f"source : {src}")
    print(f"count  : {len(cookies)}")
    for c in cookies:
        print(
            f'  {c["name"]:<24} {c["domain"]:<28} '
            f'h={int(c["httpOnly"])} s={int(c["secure"])} '
            f'ss={c["sameSite"]:<6} exp={c.get("expiry", "session")}'
        )

    out.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
