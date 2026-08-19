# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Export anjuke cookies from Chrome for use by the scraper.

Usage:
    1. Open Chrome, go to shenzhen.anjuke.com, solve any captcha
    2. Open DevTools (F12) → Application → Cookies → shenzhen.anjuke.com
    3. In Console, run:
         copy(document.cookie)
    4. Paste when prompted by this script
"""

import json
from pathlib import Path


def main() -> None:
    print("Paste your cookies from Chrome DevTools console (document.cookie):")
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

    output = Path(__file__).parent / "cookies.json"
    with open(output, "w") as f:
        json.dump(cookies, f, indent=2)

    print(f"Saved {len(cookies)} cookies to {output}")


if __name__ == "__main__":
    main()
