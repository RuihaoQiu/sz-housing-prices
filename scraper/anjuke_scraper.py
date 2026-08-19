# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "beautifulsoup4"]
# ///
"""
安居客 深圳南山区 小区信息 + 租房信息 爬虫

Usage:
    1. Open Chrome, navigate to shenzhen.anjuke.com, solve any captcha
    2. Export cookies to cookies.json (or use the --manual flag to paste cookies)
    3. Run: python anjuke_scraper.py

Steps:
    1. Crawl all 小区 IDs from /community/nanshan/ (paginated)
    2. For each 小区, scrape detail page for property info + 小区解读
    3. For each 小区, scrape rental listings and individual rental details
"""

import json
import logging
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

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

# Rental detail fields
RENTAL_FIELDS = ["户型", "面积", "朝向", "楼层", "装修", "类型", "小区"]


def load_cookies(path: str = "cookies.json") -> dict:
    """Load cookies from a JSON file exported from browser."""
    cookie_path = Path(__file__).parent / path
    if not cookie_path.exists():
        log.warning("No cookies.json found — requests may be blocked by anti-bot.")
        return {}
    with open(cookie_path) as f:
        cookies_list = json.load(f)
    # Handle both [{name, value}] and {name: value} formats
    if isinstance(cookies_list, list):
        return {c["name"]: c["value"] for c in cookies_list}
    return cookies_list


def fetch(session: requests.Session, url: str) -> BeautifulSoup | None:
    """Fetch a page and return parsed soup, with retry and delay."""
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


def get_community_ids(session: requests.Session, district: str = "nanshan") -> list[dict]:
    """Crawl paginated community list, saving incrementally."""
    communities_file = OUTPUT_DIR / f"{district}_communities.json"

    # Resume from saved progress
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

        # Find community links: /community/view/{id}
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

        # Save after every page
        save_progress(communities, f"{district}_communities.json")

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


def scrape_community_detail(session: requests.Session, community_id: str) -> dict | None:
    """Scrape 小区 detail page for property info and 小区解读."""
    url = f"{BASE_URL}/community/view/{community_id}"
    log.info("Scraping community detail: %s", url)
    soup = fetch(session, url)
    if not soup:
        return None

    info = {"id": community_id, "url": url}

    # Extract name from h1
    h1 = soup.select_one("h1.title")
    if h1:
        info["name"] = h1.get_text(strip=True)

    # Extract property info: div.label → next sibling → .value
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

    # Extract 小区解读 from the main page (li.expert-list-item)
    jiedu_items = soup.select("li.expert-list-item")
    if jiedu_items:
        entries = []
        for item in jiedu_items:
            title_el = item.select_one("p.expert-list-item-title")
            label = title_el.get_text(strip=True) if title_el else ""
            full = item.get_text(strip=True)
            # Remove label from full text to get content
            content = full.replace(label, "", 1).strip() if label else full
            if label and content:
                entries.append(f"{label}: {content}")
        if entries:
            info["小区解读"] = "\n".join(entries)

    return info


def get_rental_links(session: requests.Session, community_id: str) -> list[str]:
    """Get all rental listing URLs for a community."""
    rental_urls = []
    page = 1
    while True:
        url = (
            f"{BASE_URL}/community/props/rent/{community_id}/p{page}/"
            if page > 1
            else f"{BASE_URL}/community/props/rent/{community_id}"
        )
        log.info("Fetching rental list page %d for community %s", page, community_id)
        soup = fetch(session, url)
        if not soup:
            break

        # Find rental listing links: sz.zu.anjuke.com/fangyuan/{id}
        links = soup.find_all("a", href=re.compile(r"zu\.anjuke\.com/fangyuan/\d+"))
        page_urls = set()
        for link in links:
            href = link["href"]
            if href not in page_urls:
                page_urls.add(href)
                rental_urls.append(href)

        next_link = soup.find("a", string=re.compile(r"下一页"))
        if not next_link:
            # Fallback: search by text content (handles child elements)
            next_link = next(
                (a for a in soup.find_all("a") if "下一页" in a.get_text()),
                None,
            )
        if not next_link:
            break
        page += 1

    log.info("Found %d rental listings for community %s", len(rental_urls), community_id)
    return list(set(rental_urls))


def scrape_rental_detail(session: requests.Session, url: str) -> dict | None:
    """Scrape a single rental listing page for 房屋信息."""
    log.info("Scraping rental detail: %s", url)
    soup = fetch(session, url)
    if not soup:
        return None

    info = {"url": url}

    # Extract title from <title> tag (h3 is often empty in SSR)
    title_tag = soup.find("title")
    if title_tag:
        # Format: "【多图】前海花园，前海租房，标题。，南山租房-深圳58安居客"
        raw = title_tag.get_text(strip=True)
        raw = re.sub(r"^【.*?】", "", raw)  # remove 【多图】prefix
        raw = raw.split("，南山")[0].split("，福田")[0].split("，宝安")[0]
        raw = raw.split("，龙岗")[0].split("，龙华")[0].split("，罗湖")[0]
        info["title"] = raw.strip().rstrip("，。")

    # Extract price from div.price
    price_el = soup.select_one(".price")
    if price_el:
        match = re.search(r"(\d+)\s*元/月", price_el.get_text())
        if match:
            info["price"] = int(match.group(1))

    # Extract fields from li elements matching "field：value" pattern
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)
        for field in RENTAL_FIELDS:
            if text.startswith(field + "：") or text.startswith(field + ":"):
                value = re.split(r"[：:]", text, maxsplit=1)[1].strip()
                if value:
                    info[field] = value
                break

    return info


def save_progress(data: dict, filename: str) -> None:
    """Save data to JSON, creating output dir if needed."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved %s", path)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    cookies = load_cookies()
    if cookies:
        session.cookies.update(cookies)
        log.info("Loaded %d cookies", len(cookies))

    # Step 1: Get all community IDs for 南山区
    communities = get_community_ids(session, "nanshan")
    log.info("Processing %d communities", len(communities))

    # Step 2: Scrape each community detail (saves after each one)
    details_file = OUTPUT_DIR / "nanshan_details.json"
    if details_file.exists():
        with open(details_file) as f:
            all_details = json.load(f)
        scraped_ids = {d["id"] for d in all_details}
    else:
        all_details = []
        scraped_ids = set()

    for i, comm in enumerate(communities):
        if comm["id"] in scraped_ids:
            continue

        detail = scrape_community_detail(session, comm["id"])
        if detail:
            if "name" not in detail:
                detail["name"] = comm["name"]
            all_details.append(detail)
            scraped_ids.add(comm["id"])
            save_progress(all_details, "nanshan_details.json")
            log.info("Detail progress: %d/%d communities", len(scraped_ids), len(communities))

    save_progress(all_details, "nanshan_details.json")

    # Step 3: Scrape rental listings for each community
    rentals_file = OUTPUT_DIR / "nanshan_rentals.json"
    progress_file = OUTPUT_DIR / "nanshan_rental_progress.json"
    if rentals_file.exists():
        with open(rentals_file) as f:
            all_rentals = json.load(f)
    else:
        all_rentals = []
    if progress_file.exists():
        with open(progress_file) as f:
            scraped_rental_ids = set(json.load(f))
    else:
        scraped_rental_ids = set()

    for i, comm in enumerate(communities):
        if comm["id"] in scraped_rental_ids:
            log.info("Skipping rentals for %s (%s)", comm["id"], comm["name"])
            continue

        rental_urls = get_rental_links(session, comm["id"])
        for url in rental_urls:
            rental = scrape_rental_detail(session, url)
            if rental:
                rental["community_id"] = comm["id"]
                all_rentals.append(rental)

        scraped_rental_ids.add(comm["id"])
        save_progress(all_rentals, "nanshan_rentals.json")
        save_progress(list(scraped_rental_ids), "nanshan_rental_progress.json")
        log.info("Rentals progress: %d/%d communities, %d total listings", i + 1, len(communities), len(all_rentals))

    save_progress(all_rentals, "nanshan_rentals.json")
    log.info("Done! %d communities, %d rentals", len(all_details), len(all_rentals))


if __name__ == "__main__":
    main()
