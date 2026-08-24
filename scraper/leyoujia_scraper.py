# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "beautifulsoup4"]
# ///
"""乐有家 深圳南山区 租房列表爬虫

Crawls rental listings from all 21 Nanshan sub-areas on leyoujia.com.
Only scrapes list pages — no detail page requests needed.

Usage:
    1. Login to shenzhen.leyoujia.com in Chrome
    2. Open DevTools Console, run: copy(document.cookie)
    3. Run: python export_cookies.py --leyoujia   (then paste)
    4. Run: python leyoujia_scraper.py

Daily usage:
    Re-run to detect new listings. The scraper compares against local data
    and reports any new listing IDs found.
"""

import argparse
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

BASE_URL = "https://shenzhen.leyoujia.com"
OUTPUT_DIR = Path(__file__).parent / "output"
DELAY = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://shenzhen.leyoujia.com/",
    "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "Connection": "keep-alive",
}

# Nanshan sub-areas: code -> name
NANSHAN_SUBAREAS = {
    "a3q1": "白石洲",
    "a3q2": "华润城",
    "a3q3": "大学城",
    "a3q4": "桂庙",
    "a3q5": "海岸城",
    "a3q6": "后海",
    "a3q7": "华侨城",
    "a3q8": "红树湾",
    "a3q9": "科技南",
    "a3q10": "科技北",
    "a3q11": "南山中心区",
    "a3q12": "南头",
    "a3q13": "南油",
    "a3q14": "前海南",
    "a3q15": "前海北",
    "a3q16": "麒麟",
    "a3q17": "蛇口",
    "a3q18": "深圳湾",
    "a3q19": "同乐",
    "a3q20": "桃源村",
    "a3q21": "西丽",
}


def load_cookies(path: str = "cookies_leyoujia.json") -> dict:
    cookie_path = Path(__file__).parent / path
    if not cookie_path.exists():
        return {}
    with open(cookie_path) as f:
        cookies_list = json.load(f)
    if isinstance(cookies_list, list):
        return {c["name"]: c["value"] for c in cookies_list}
    return cookies_list


def fetch(session: requests.Session, url: str) -> BeautifulSoup | None:
    for attempt in range(3):
        try:
            time.sleep(DELAY)
            resp = session.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 403:
                log.error("403 at %s — update cookies", url)
                return None
            if "login" in resp.url:
                log.error("Redirected to login — cookies expired or missing")
                return None
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            log.warning("Attempt %d failed for %s: %s", attempt + 1, url, e)
            time.sleep(DELAY * (attempt + 1))
    return None


def parse_listing(item: Tag) -> dict | None:
    """Parse one <li class="item"> into a listing dict.

    HTML structure (verified from live page):
      <li class="item clearfix">
        <div class="text">
          <p class="tit"><a href="/zf/detail/{hash}">整租·小区名3室2厅-朝南</a></p>
          <p class="attr"><span>3室2厅1卫</span> | <span>朝南</span> | <span>建筑面积89㎡</span></p>
          <p class="attr"><span>精装</span> | <span>中楼层(共28层)</span> | <span>2004年建成</span></p>
          <p class="attr"><a href="/xq/detail/{id}">小区名</a> | <a>南山</a>-<a>海岸城</a></p>
          <p class="labs"><span class="lab">距2号线后海站369米</span> ...</p>
        </div>
        <div class="price">
          <p class="sup"><span class="salePrice">9000</span>元/月</p>
          <p class="sub">整租 | 押二付一</p>
          <div class="btn im-zixun" data-room="3" data-area="89" data-price="9000"
               data-lpid="124" data-forward="南" data-fitment="精装" .../>
        </div>
      </li>
    """
    # Detail link → listing hash ID
    detail_link = item.select_one('a[href*="/zf/detail/"]')
    if not detail_link:
        return None
    m = re.search(r"/zf/detail/(\w+)", detail_link["href"])
    if not m:
        return None

    listing: dict = {"id": m.group(1)}

    # --- Structured data from the consultation button (most reliable) ---
    btn = item.select_one("div.im-zixun[data-price]")
    if btn:
        listing["price"] = _int(btn.get("data-price"))
        listing["rooms"] = _int(btn.get("data-room"))
        listing["halls"] = _int(btn.get("data-hall"))
        listing["area"] = _float(btn.get("data-area"))
        listing["community_id"] = _int(btn.get("data-lpid"))
        listing["house_id"] = _int(btn.get("data-fid") or btn.get("data-houseid"))
        if btn.get("data-forward"):
            listing["orientation"] = btn["data-forward"]
        if btn.get("data-fitment"):
            listing["decoration"] = btn["data-fitment"]

    # --- Title ---
    tit = item.select_one("p.tit a")
    if tit:
        title = tit.get_text(strip=True)
        listing["title"] = title
        if title.startswith("整租"):
            listing["rental_type"] = "整租"
        elif title.startswith("合租"):
            listing["rental_type"] = "合租"

    # --- Community name from /xq/detail/ link ---
    xq_link = item.select_one('a[href*="/xq/detail/"]')
    if xq_link:
        listing["community"] = xq_link.get_text(strip=True)
        m = re.search(r"/xq/detail/(\d+)", xq_link["href"])
        if m:
            listing.setdefault("community_id", int(m.group(1)))

    # --- Attribute rows (p.attr) ---
    attr_rows = item.select("p.attr")
    full_text = " ".join(row.get_text(" ", strip=True) for row in attr_rows)

    # Layout: "3室2厅1卫"
    m = re.search(r"(\d+室\d+厅(?:\d+卫)?)", full_text)
    if m:
        listing["layout"] = m.group(1)
        listing.setdefault("rooms", _int(re.match(r"(\d+)", m.group(1)).group(1)))

    # Area from text (fallback if data-area missing)
    m = re.search(r"建筑面积([\d.]+)㎡", full_text)
    if m:
        listing.setdefault("area", float(m.group(1)))

    # Floor
    m = re.search(r"([低中高]楼层)\(共(\d+)层\)", full_text)
    if m:
        listing["floor"] = m.group(1)
        listing["total_floors"] = int(m.group(2))

    # Year built
    m = re.search(r"(\d{4})年建成", full_text)
    if m:
        listing["year_built"] = int(m.group(1))

    # --- Location (district / sub-area) ---
    district_link = item.select_one('a[href*="/zf/a"][href$="/"]')
    if district_link:
        href = district_link["href"]
        # Sub-area link: /zf/a3q5/  District link: /zf/a3/
        if re.match(r"/zf/a\d+q\d+/$", href):
            listing["subarea"] = district_link.get_text(strip=True)
        elif re.match(r"/zf/a\d+/$", href):
            listing["district"] = district_link.get_text(strip=True)

    # Also grab sub-area specifically
    subarea_link = item.select_one('a[href*="/zf/a3q"]')
    if subarea_link:
        listing["subarea"] = subarea_link.get_text(strip=True)

    # --- Metro and tags (p.labs) ---
    labs = item.select("p.labs span.lab")
    tags = []
    for lab in labs:
        text = lab.get_text(strip=True)
        m = re.search(r"距(.+?线.+?站)(\d+)米", text)
        if m:
            listing["metro_station"] = m.group(1)
            listing["metro_distance"] = int(m.group(2))
        else:
            tags.append(text)
    if tags:
        listing["tags"] = tags

    # --- Price from .salePrice (fallback) ---
    price_el = item.select_one("span.salePrice")
    if price_el:
        listing.setdefault("price", _int(price_el.get_text(strip=True)))

    # --- Payment terms ---
    sub = item.select_one("p.sub")
    if sub:
        text = sub.get_text(strip=True)
        m = re.search(r"(押[一二三]付[一二三])", text)
        if m:
            listing["payment"] = m.group(1)

    # Computed: price per sqm
    if listing.get("price") and listing.get("area"):
        listing["price_per_sqm"] = round(listing["price"] / listing["area"], 1)

    # Drop None values
    return {k: v for k, v in listing.items() if v is not None}


def scrape_subarea(session: requests.Session, code: str, name: str) -> list[dict]:
    """Scrape all listing pages for one sub-area."""
    listings = []
    page = 1

    while True:
        url = f"{BASE_URL}/zf/{code}/" if page == 1 else f"{BASE_URL}/zf/{code}n{page}/"

        log.info("Fetching %s page %d: %s", name, page, url)
        soup = fetch(session, url)
        if not soup:
            break

        items = soup.select("li.item")
        if not items:
            log.info("No listings on %s page %d, stopping", name, page)
            break

        page_count = 0
        for item in items:
            listing = parse_listing(item)
            if listing:
                listing.setdefault("district", "南山")
                listing.setdefault("subarea", name)
                listings.append(listing)
                page_count += 1

        log.info("Parsed %d listings from %s page %d", page_count, name, page)
        if page_count == 0:
            break

        # Check for next page
        next_link = soup.select_one("a.fy_nextpage") or soup.find(
            "a", string=re.compile(r"下一页")
        )
        if not next_link:
            break

        page += 1

    return listings


def save_json(data: object, filename: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved %s", path)


def load_json(filename: str) -> list | dict | None:
    path = OUTPUT_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def make_session(cookies: dict) -> requests.Session:
    """Create a new session with shared cookies (one per thread)."""
    session = requests.Session()
    session.cookies.update(cookies)
    return session


# Lock for thread-safe progress updates
_progress_lock = threading.Lock()


def scrape_subarea_task(
    cookies: dict, code: str, name: str, completed: list[str], all_listings: list[dict]
) -> list[dict]:
    """Worker: scrape one sub-area, update shared progress."""
    session = make_session(cookies)
    listings = scrape_subarea(session, code, name)

    with _progress_lock:
        all_listings.extend(listings)
        completed.append(code)
        save_json(
            {"completed": completed, "listings": all_listings},
            "leyoujia_progress.json",
        )
        log.info(
            "Progress: %d/%d sub-areas, %d listings total",
            len(completed), len(NANSHAN_SUBAREAS), len(all_listings),
        )

    return listings


def main() -> None:
    parser = argparse.ArgumentParser(description="乐有家南山租房爬虫")
    parser.add_argument("--workers", type=int, default=1, help="concurrent workers (default: 1)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cookies = load_cookies()
    if not cookies:
        log.error(
            "No cookies found. Login to shenzhen.leyoujia.com in Chrome, "
            "then run: python export_cookies.py --leyoujia"
        )
        return
    log.info("Loaded %d cookies", len(cookies))

    # Verify cookies work
    test_session = make_session(cookies)
    test_resp = test_session.get(
        f"{BASE_URL}/zf/a3q5/", headers=HEADERS, timeout=15, allow_redirects=False
    )
    if test_resp.status_code == 302 or "login" in test_resp.headers.get("Location", ""):
        log.error("Cookies expired — login again and re-export")
        return
    log.info("Cookie check passed")

    # Load previous data for diff and scraped_at preservation
    prev_listings = load_json("leyoujia_rentals.json") or []
    prev_ids = {item["id"] for item in prev_listings}
    prev_scraped_at = {
        item["id"]: item["scraped_at"] for item in prev_listings if "scraped_at" in item
    }
    today = date.today().isoformat()

    # Load progress (resume interrupted runs)
    progress = load_json("leyoujia_progress.json") or {}
    completed_areas: list[str] = progress.get("completed", [])
    current_listings: list[dict] = progress.get("listings", [])

    # Filter to remaining sub-areas
    remaining = {
        code: name for code, name in NANSHAN_SUBAREAS.items() if code not in completed_areas
    }

    if not remaining:
        log.info("All sub-areas already completed")
    elif args.workers <= 1:
        # Sequential mode
        for code, name in remaining.items():
            scrape_subarea_task(cookies, code, name, completed_areas, current_listings)
    else:
        # Parallel mode
        log.info("Starting %d workers for %d sub-areas", args.workers, len(remaining))
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    scrape_subarea_task, cookies, code, name, completed_areas, current_listings
                ): (code, name)
                for code, name in remaining.items()
            }
            for future in as_completed(futures):
                code, name = futures[future]
                try:
                    future.result()
                except Exception:
                    log.exception("Failed to scrape %s (%s)", code, name)

    # Dedup by listing ID, add scraped_at
    seen: set[str] = set()
    deduped = []
    for listing in current_listings:
        if listing["id"] not in seen:
            seen.add(listing["id"])
            listing["scraped_at"] = prev_scraped_at.get(listing["id"], today)
            deduped.append(listing)

    save_json(deduped, "leyoujia_rentals.json")

    # Collect unique communities
    communities: dict[str, dict] = {}
    for listing in deduped:
        cname = listing.get("community", "unknown")
        if cname not in communities:
            communities[cname] = {
                "id": listing.get("community_id"),
                "subarea": listing.get("subarea"),
                "count": 0,
            }
        communities[cname]["count"] += 1

    save_json(communities, "leyoujia_communities.json")

    # Report
    current_ids = {item["id"] for item in deduped}
    new_ids = current_ids - prev_ids
    removed_ids = prev_ids - current_ids

    # Archive removed listings
    if removed_ids:
        prev_by_id = {item["id"]: item for item in prev_listings}
        archive = load_json("leyoujia_rentals_removed.json") or []
        archived_ids = {item["id"] for item in archive}
        for rid in removed_ids:
            if rid not in archived_ids and rid in prev_by_id:
                entry = prev_by_id[rid]
                entry["removed_at"] = today
                archive.append(entry)
        save_json(archive, "leyoujia_rentals_removed.json")
        log.info("Archived %d removed listings (%d total in archive)", len(removed_ids), len(archive))

    log.info("=" * 60)
    log.info("Total: %d listings, %d communities", len(deduped), len(communities))
    if prev_ids:
        log.info("New: %d | Removed: %d", len(new_ids), len(removed_ids))
        for nl in (l for l in deduped if l["id"] in new_ids):
            log.info(
                "  + %s | %s | %d元/月",
                nl.get("community", "?"),
                nl.get("layout", "?"),
                nl.get("price", 0),
            )

    # Clean up progress file
    progress_path = OUTPUT_DIR / "leyoujia_progress.json"
    if progress_path.exists():
        progress_path.unlink()


def _int(val: str | None) -> int | None:
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


if __name__ == "__main__":
    main()
