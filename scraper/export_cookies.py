# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Export browser cookies for use by scrapers.

Usage:
    Anjuke:
        1. Open Chrome, go to shenzhen.anjuke.com, solve any captcha
        2. In Console, run: copy(document.cookie)
        3. Run: python export_cookies.py
    Leyoujia:
        1. Open Chrome, login to shenzhen.leyoujia.com
        2. In Console, run: copy(document.cookie)
        3. Run: python export_cookies.py --leyoujia
"""

import json
import sys
from pathlib import Path

TARGETS = {
    "anjuke": "cookies.json",
    "leyoujia": "cookies_leyoujia.json",
}


def main() -> None:
    target = "leyoujia" if "--leyoujia" in sys.argv else "anjuke"
    filename = TARGETS[target]

    print(f"[{target}] Paste cookies from Chrome console (document.cookie):")
    print("(Press Enter twice when done)")

    lines = []
    while True:
        line = input()
        if not line and lines:
            break
        lines.append(line)

    raw = " ".join(lines).strip()
    if not raw:
        print("No cookies provided.")
        return

    cookies = {}
    for pair in raw.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, value = pair.split("=", 1)
            cookies[name.strip()] = value.strip()

    output = Path(__file__).parent / filename
    with open(output, "w") as f:
        json.dump(cookies, f, indent=2)

    print(f"Saved {len(cookies)} cookies to {output}")


if __name__ == "__main__":
    main()
