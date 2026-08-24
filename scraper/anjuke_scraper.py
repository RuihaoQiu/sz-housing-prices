# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "beautifulsoup4"]
# ///
"""安居客 深圳南山区 小区信息 + 租房信息 爬虫

Usage:
    Full run:  uv run python anjuke_scraper.py --workers 5
    Daily:     uv run python anjuke_scraper.py --rentals-only --workers 5

Steps (full run):
    1. Crawl all 小区 IDs from /community/nanshan/ (paginated)
    2. For each 小区, scrape detail page for property info + 小区解读
    3. Scrape rental listings from sub-area list pages (20 sub-areas)

Daily (--rentals-only):
    Only step 3. Scrapes ~80-100 list pages, ~5 min with 5 workers.

Daily diff:
    Compares against previous data. Reports new/removed.
    Archives removed listings to anjuke_rentals_removed.json.
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

BASE_URL = "https://shenzhen.anjuke.com"
RENT_BASE = "https://sz.zu.anjuke.com"
OUTPUT_DIR = Path(__file__).parent / "output"
DELAY = 3  # seconds between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://shenzhen.anjuke.com/",
    "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-site",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "Connection": "keep-alive",
}

# Property info fields to extract from 小区 detail page
PROPERTY_FIELDS = [
    "竣工时间", "产权年限", "总户数", "总建面积", "容积率",
    "绿化率", "建筑类型", "所属商圈", "统一供暖", "供水供电",
    "停车位", "物业费", "停车费",
]

# 20 Nanshan sub-areas for rental list-page scraping
NANSHAN_SUBAREAS = [
    ("baishizhou", "白石洲"),
    ("dachong", "大冲"),
    ("haishangshijie", "海上世界"),
    ("haiwangdasha", "南山地铁口"),
    ("houhai", "后海"),
    ("huaqiaocheng", "华侨城"),
    ("kejiyuan", "科技园"),
    ("nanshanyiyuan", "南山医院"),
    ("nanshanzhoubian", "海岸城"),
    ("nantou", "南头"),
    ("nanxinlukou", "桃园"),
    ("nanyou", "南油"),
    ("nszxqsz", "大学城"),
    ("qianhai", "前海"),
    ("shekou", "蛇口"),
    ("shendabeimen", "科苑"),
    ("shenzw", "深圳湾"),
    ("szzhongxinqu", "南山中心区"),
    ("taoyuancun", "桃源村"),
    ("xililu", "西丽"),
]

MAX_PAGES_PER_SUBAREA = 10

_progress_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def load_cookies(path: str = "cookies.json") -> dict:
    cookie_path = Path(__file__).parent / path
    if not cookie_path.exists():
        log.warning("No cookies.json found — requests may be blocked by anti-bot.")
        return {}
    with open(cookie_path) as f:
        cookies_list = json.load(f)
    if isinstance(cookies_list, list):
        return {c["name"]: c["value"] for c in cookies_list}
    return cookies_list


def make_session(cookies: dict) -> requests.Session:
    session = requests.Session()
    session.cookies.update(cookies)
    return session


def fetch(session: requests.Session, url: str) -> BeautifulSoup | None:
    for attempt in range(3):
        try:
            time.sleep(DELAY)
            resp = session.get(url, headers=HEADERS, timeout=15)
            if "verifycode" in resp.url or "antibot" in resp.url:
                log.error("Anti-bot triggered at %s — solve captcha and update cookies", url)
                return None
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            log.warning("Attempt %d failed for %s: %s", attempt + 1, url, e)
            time.sleep(DELAY * (attempt + 1))
    return None


def extract_listing_id(url: str) -> str | None:
    m = re.search(r"/fangyuan/(\d+)", url)
    return m.group(1) if m else None


def save_json(data: object, filename: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(filename: str) -> list | dict | None:
    path = OUTPUT_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Step 1: Community discovery
# ---------------------------------------------------------------------------


def get_community_ids(session: requests.Session, district: str = "nanshan") -> list[dict]:
    communities_file = OUTPUT_DIR / "anjuke_community_ids.json"

    if communities_file.exists():
        with open(communities_file) as f:
            communities = json.load(f)
        seen = {c["id"] for c in communities}
        log.info("Resuming with %d cached communities", len(communities))
    else:
        communities = []
        seen = set()

    page = 1
    empty_pages = 0
    while True:
        url = f"{BASE_URL}/community/{district}/p{page}/" if page > 1 else f"{BASE_URL}/community/{district}/"
        log.info("Fetching community list page %d: %s", page, url)
        soup = fetch(session, url)
        if not soup:
            break

        links = soup.find_all("a", href=re.compile(r"/community/view/\d+"))
        new_on_page = 0
        for link in links:
            match = re.search(r"/community/view/(\d+)", link["href"])
            if match:
                cid = match.group(1)
                if cid not in seen:
                    seen.add(cid)
                    name = link.get_text(strip=True)
                    if name and len(name) > 1:
                        communities.append({
                            "id": cid,
                            "name": name,
                            "url": f"{BASE_URL}/community/view/{cid}",
                        })
                        new_on_page += 1

        save_json(communities, "anjuke_community_ids.json")

        if new_on_page == 0:
            empty_pages += 1
            if empty_pages >= 2:
                log.info("2 consecutive empty pages, stopping at page %d", page)
                break
        else:
            empty_pages = 0

        next_link = soup.find("a", string=re.compile(r"下一页"))
        if not next_link:
            next_link = next(
                (a for a in soup.find_all("a") if "下一页" in a.get_text()),
                None,
            )
        if not next_link:
            log.info("No more pages after page %d", page)
            break
        page += 1

    log.info("Found %d unique communities in %s", len(communities), district)
    return communities


# ---------------------------------------------------------------------------
# Step 2: Community detail scraping
# ---------------------------------------------------------------------------


def scrape_community_detail(session: requests.Session, community_id: str) -> dict | None:
    url = f"{BASE_URL}/community/view/{community_id}"
    log.info("Scraping community detail: %s", url)
    soup = fetch(session, url)
    if not soup:
        return None

    info: dict = {"id": community_id, "url": url}

    h1 = soup.select_one("h1.title")
    if h1:
        # h1 may contain child spans (e.g. "数据由万科物业提供") — extract only
        # the community name by stripping known trailing noise.
        raw = h1.get_text(strip=True)
        info["name"] = re.split(r"数据由|\d{4}年竣工", raw)[0].strip()

    for label_el in soup.select("div.label"):
        field = label_el.get_text(strip=True)
        if field not in PROPERTY_FIELDS:
            continue
        sibling = label_el.find_next_sibling()
        if not sibling:
            continue
        val_el = sibling.select_one(".value, .value_2")
        if val_el:
            info[field] = val_el.get_text(strip=True)
        else:
            info[field] = sibling.get_text(strip=True)

    jiedu_items = soup.select("li.expert-list-item")
    if jiedu_items:
        entries = []
        for item in jiedu_items:
            title_el = item.select_one("p.expert-list-item-title")
            label = title_el.get_text(strip=True) if title_el else ""
            full = item.get_text(strip=True)
            content = full.replace(label, "", 1).strip() if label else full
            if label and content:
                entries.append(f"{label}: {content}")
        if entries:
            info["小区解读"] = "\n".join(entries)

    return info


def scrape_detail_task(
    cookies: dict, comm: dict, scraped_ids: set, all_details: list, total: int
) -> dict | None:
    session = make_session(cookies)
    detail = scrape_community_detail(session, comm["id"])

    with _progress_lock:
        if detail:
            if "name" not in detail:
                detail["name"] = comm["name"]
            all_details.append(detail)
        scraped_ids.add(comm["id"])
        save_json(all_details, "anjuke_communities.json")
        log.info("Detail progress: %d/%d communities", len(scraped_ids), total)

    return detail


# ---------------------------------------------------------------------------
# Step 3: Rental scraping via sub-area list pages
# ---------------------------------------------------------------------------


def parse_listing(item: Tag) -> dict | None:
    """Parse one zu-itemmod div from a sub-area list page."""
    # ID from link URL
    link = item.select_one('a[href*="fangyuan"]')
    if not link:
        return None
    lid = extract_listing_id(link.get("href", ""))
    if not lid:
        return None

    url = link["href"].split("?")[0]

    info: dict = {
        "id": lid,
        "url": f"{RENT_BASE}/fangyuan/{lid}",
    }

    # Title
    title_el = item.select_one("h3 b.strongbox")
    if title_el:
        info["title"] = title_el.get_text(strip=True)

    # Price
    price_el = item.select_one(".zu-side strong.price, .zu-side .price")
    if price_el:
        m = re.search(r"(\d+)", price_el.get_text(strip=True))
        if m:
            info["price"] = int(m.group(1))

    # Layout / area / floor from first <p> in zu-info
    info_div = item.select_one(".zu-info")
    if info_div:
        ps = info_div.select("p")

        # p[0]: "1室1厅 | 40平米 | 高层(共54层)"
        if ps:
            line = ps[0].get_text(strip=True)
            rm = re.search(r"(\d+)室(\d+)厅", line)
            if rm:
                info["户型"] = f"{rm.group(1)}室{rm.group(2)}厅"
            am = re.search(r"([\d.]+)平米", line)
            if am:
                info["面积"] = f"{am.group(1)}平米"
            fm = re.search(r"(高|中|低)层\(共(\d+)层\)", line)
            if fm:
                info["楼层"] = f"{fm.group(1)}层(共{fm.group(2)}层)"

        # Tags from bot-tag <p>
        tag_p = info_div.select_one("p.bot-tag")
        if tag_p:
            tags = [s.get_text(strip=True) for s in tag_p.select("span")]
            for t in tags:
                if re.match(r"朝[东西南北]+", t):
                    info["朝向"] = t.replace("朝", "")
                elif t in ("整租", "合租"):
                    info["rent_type"] = t

    # Address block: community name + subarea
    addr = item.select_one("address")
    if addr:
        comm_link = addr.select_one('a[href*="community"]')
        if comm_link:
            info["小区"] = comm_link.get_text(strip=True)
            cm = re.search(r"/community/view/(\d+)", comm_link.get("href", ""))
            if cm:
                info["community_id"] = cm.group(1)

        # Parse subarea from address text: "小区名 南山 - 大学城 - 长源二街15号"
        addr_text = addr.get_text(strip=True)
        sm = re.search(r"南山-(.+?)(?:-|$)", addr_text)
        if sm:
            info["subarea"] = sm.group(1)

    return info


def scrape_subarea(session: requests.Session, code: str, name: str) -> list[dict]:
    """Scrape all pages of one sub-area. Returns parsed listings."""
    listings: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(1, MAX_PAGES_PER_SUBAREA + 1):
        url = (
            f"{RENT_BASE}/fangyuan/nanshan-q-{code}/p{page}/"
            if page > 1
            else f"{RENT_BASE}/fangyuan/nanshan-q-{code}/"
        )
        soup = fetch(session, url)
        if not soup:
            break

        items = soup.select("div.zu-itemmod")
        if not items:
            break

        for item in items:
            parsed = parse_listing(item)
            if parsed and parsed["id"] not in seen_ids:
                seen_ids.add(parsed["id"])
                listings.append(parsed)

        # Check for next page
        next_link = soup.find("a", string=re.compile(r"下一页"))
        if not next_link:
            next_link = next(
                (a for a in soup.find_all("a") if "下一页" in a.get_text()),
                None,
            )
        if not next_link:
            break

    return listings


def scrape_subarea_task(
    cookies: dict,
    code: str,
    name: str,
    today: str,
    all_listings: list[dict],
    completed: list[str],
    total: int,
) -> None:
    """Worker: scrape one sub-area, update shared state."""
    session = make_session(cookies)
    listings = scrape_subarea(session, code, name)

    for item in listings:
        item["scraped_at"] = today

    with _progress_lock:
        all_listings.extend(listings)
        completed.append(code)
        log.info(
            "Progress: %d/%d sub-areas | %s (%s): %d listings",
            len(completed), total, name, code, len(listings),
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="安居客南山区爬虫")
    parser.add_argument("--workers", type=int, default=1, help="concurrent workers (default: 1)")
    parser.add_argument(
        "--rentals-only", action="store_true",
        help="skip community discovery/detail, scrape rentals only (for daily runs)",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cookies = load_cookies()
    if not cookies:
        log.warning("No cookies — requests may fail. Export with: python export_cookies.py")

    today = date.today().isoformat()

    # --- Steps 1-2: Community discovery + details (full run only) ---
    if not args.rentals_only:
        session = make_session(cookies)
        communities = get_community_ids(session, "nanshan")
        log.info("Processing %d communities", len(communities))

        details_file = OUTPUT_DIR / "anjuke_communities.json"
        if details_file.exists():
            with open(details_file) as f:
                all_details = json.load(f)
            scraped_ids = {d["id"] for d in all_details}
        else:
            all_details = []
            scraped_ids = set()

        remaining = [c for c in communities if c["id"] not in scraped_ids]
        if remaining:
            log.info("Scraping details for %d remaining communities", len(remaining))
            total = len(scraped_ids) + len(remaining)

            if args.workers <= 1:
                for comm in remaining:
                    scrape_detail_task(cookies, comm, scraped_ids, all_details, total)
            else:
                log.info("Starting %d workers for community details", args.workers)
                with ThreadPoolExecutor(max_workers=args.workers) as executor:
                    futures = {
                        executor.submit(
                            scrape_detail_task, cookies, comm, scraped_ids, all_details, total
                        ): comm
                        for comm in remaining
                    }
                    for future in as_completed(futures):
                        comm = futures[future]
                        try:
                            future.result()
                        except Exception:
                            log.exception("Failed detail for %s (%s)", comm["id"], comm["name"])

            save_json(all_details, "anjuke_communities.json")

    # --- Step 3: Rental listings via sub-area pages ---
    log.info("Scraping rentals from %d sub-areas", len(NANSHAN_SUBAREAS))

    # Load previous data for diff
    prev_rentals = load_json("anjuke_rentals.json") or []
    prev_by_id: dict[str, dict] = {}
    for r in prev_rentals:
        lid = r.get("id") or extract_listing_id(r.get("url", ""))
        if lid:
            r.setdefault("id", lid)
            r.setdefault("scraped_at", today)
            prev_by_id[lid] = r
    prev_ids = set(prev_by_id.keys())
    log.info("Previous data: %d listings (%d unique IDs)", len(prev_rentals), len(prev_ids))

    # Scrape all sub-areas
    all_listings: list[dict] = []
    completed: list[str] = []
    total = len(NANSHAN_SUBAREAS)

    if args.workers <= 1:
        for code, name in NANSHAN_SUBAREAS:
            scrape_subarea_task(cookies, code, name, today, all_listings, completed, total)
    else:
        log.info("Starting %d workers for %d sub-areas", args.workers, total)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    scrape_subarea_task, cookies, code, name, today,
                    all_listings, completed, total,
                ): (code, name)
                for code, name in NANSHAN_SUBAREAS
            }
            for future in as_completed(futures):
                code, name = futures[future]
                try:
                    future.result()
                except Exception:
                    log.exception("Failed sub-area %s (%s)", code, name)

    # --- Dedup and merge with previous data ---
    seen: set[str] = set()
    merged: list[dict] = []

    for listing in all_listings:
        lid = listing["id"]
        if lid in seen:
            continue
        seen.add(lid)

        if lid in prev_by_id:
            # Known listing — keep richer previous record
            merged.append(prev_by_id[lid])
        else:
            # New listing — use list-page data
            merged.append(listing)

    # Safety: never overwrite with 0 results when previous data exists
    if prev_ids and len(merged) == 0:
        log.error("No listings collected — refusing to overwrite previous data")
        return

    save_json(merged, "anjuke_rentals.json")

    # --- Diff report ---
    current_ids = {r["id"] for r in merged}
    new_ids = current_ids - prev_ids
    removed_ids = prev_ids - current_ids
    new_today = [r for r in merged if r.get("id") in new_ids]

    # Archive removed listings
    if removed_ids:
        archive = load_json("anjuke_rentals_removed.json") or []
        archived_ids = {item["id"] for item in archive if "id" in item}
        for rid in removed_ids:
            if rid not in archived_ids and rid in prev_by_id:
                entry = prev_by_id[rid].copy()
                entry["removed_at"] = today
                archive.append(entry)
        save_json(archive, "anjuke_rentals_removed.json")
        log.info("Archived %d removed listings (%d total in archive)", len(removed_ids), len(archive))

    log.info("=" * 60)
    log.info("Total: %d listings (deduped)", len(merged))
    if prev_ids:
        log.info("New: %d | Removed: %d | Kept: %d", len(new_ids), len(removed_ids), len(current_ids - new_ids))
        if new_today:
            log.info("New listings today:")
            for r in new_today[:20]:
                log.info(
                    "  + %s | %s | %s | %d元/月",
                    r.get("小区", r.get("title", "?")),
                    r.get("户型", "?"),
                    r.get("面积", "?"),
                    r.get("price", 0),
                )
            if len(new_today) > 20:
                log.info("  ... and %d more", len(new_today) - 20)
    else:
        log.info("First run — no previous data to compare")

    log.info("Done!")


if __name__ == "__main__":
    main()
