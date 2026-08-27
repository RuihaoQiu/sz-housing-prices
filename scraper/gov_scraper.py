"""Scraper for 深圳住建局 fdc.zjj.sz.gov.cn — per-unit area data.

Extracts per-unit area breakdowns (建筑面积, 分摊面积, 套内建筑面积) for
Nanshan district projects to calculate 得房率 (net-to-gross area ratio).

Uses Chrome CDP + Playwright to bypass bot protection, and intercepts
the site's encrypted API responses to extract structured data.

Requirements:
    pip install playwright && playwright install chromium

Usage:
    python gov_scraper.py                     # Scrape all Nanshan projects
    python gov_scraper.py --workers 4         # 4 concurrent tabs
    python gov_scraper.py --max-projects 5    # Test with first 5
    python gov_scraper.py --resume            # Resume from checkpoint
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path

from playwright.async_api import Page, Response, async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-6s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_URL = "https://fdc.zjj.sz.gov.cn/szfdcscjy"
LIST_URL = f"{BASE_URL}/#/foreignPublic/listApartmentHunting/listApartmentHuntingsj"
DETAIL_URL = f"{BASE_URL}/#/projectTable/projectTableDetails/projectTableDetails"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "gov_projects.json"
CHECKPOINT_FILE = OUTPUT_DIR / "gov_checkpoint.json"
CHROME_DATA_DIR = "/tmp/chrome-gov-scraper"
CDP_PORT = 9222

API_TIMEOUT = 15_000  # ms
PAGE_SETTLE = 3.0  # seconds


def _launch_chrome() -> subprocess.Popen:
    """Launch Chrome with remote debugging for CDP connection."""
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome",
        "chromium",
    ]
    chrome_bin = None
    for path in chrome_paths:
        if os.path.exists(path) or os.popen(f"which {path}").read().strip():
            chrome_bin = path
            break
    if not chrome_bin:
        raise RuntimeError("Chrome not found. Install Google Chrome.")

    proc = subprocess.Popen(
        [
            chrome_bin,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={CHROME_DATA_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    return proc


async def _wait_api(page: Page, endpoint: str, action) -> dict:
    """Perform an action and wait for a specific API response."""
    async with page.expect_response(
        lambda r: endpoint in r.url and r.status == 200,
        timeout=API_TIMEOUT,
    ) as resp_info:
        await action()
    response = await resp_info.value
    return await response.json()


class GovScraper:
    def __init__(self, workers: int = 1, max_projects: int = 0, resume: bool = False):
        self.workers = workers
        self.max_projects = max_projects
        self.resume = resume
        self._lock = asyncio.Lock()
        self._results: list[dict] = []
        self._scraped_ids: set[str] = set()
        self._projects: list[dict] = []
        self._done_count = 0
        self._total_remaining = 0

    # -- checkpoint / output -------------------------------------------

    def _load_checkpoint(self) -> dict:
        if CHECKPOINT_FILE.exists():
            return json.loads(CHECKPOINT_FILE.read_text())
        return {}

    async def _save_progress(self):
        async with self._lock:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            CHECKPOINT_FILE.write_text(
                json.dumps(
                    {"projects": self._projects, "scraped_ids": list(self._scraped_ids)},
                    ensure_ascii=False,
                )
            )
            OUTPUT_FILE.write_text(
                json.dumps(self._results, ensure_ascii=False, indent=2)
            )

    # -- phase 1: collect project list ---------------------------------

    async def _collect_projects(self, page: Page) -> list[dict]:
        """Collect all Nanshan project IDs by paginating the list API."""
        log.info("Phase 1: collecting Nanshan project list...")
        await page.goto(LIST_URL, wait_until="networkidle", timeout=30_000)
        await asyncio.sleep(PAGE_SETTLE)

        resp = await _wait_api(
            page,
            "getYsfYsPublicity",
            lambda: page.locator("span, a").filter(has_text="南山").first.click(),
        )
        data = resp["data"]
        total = data["total"]
        page_size = data["pageSize"]
        total_pages = (total + page_size - 1) // page_size

        all_projects = [self._parse_project(p) for p in data["list"]]
        log.info(f"  Page 1/{total_pages}: {len(data['list'])} projects (total={total})")

        for pg in range(2, total_pages + 1):
            try:
                resp = await _wait_api(
                    page,
                    "getYsfYsPublicity",
                    lambda: page.locator(".btn-next").click(),
                )
                items = resp["data"]["list"]
                all_projects.extend(self._parse_project(p) for p in items)
                if pg % 10 == 0:
                    log.info(f"  Page {pg}/{total_pages}: {len(all_projects)} projects so far")
                await asyncio.sleep(0.3)
            except Exception as e:
                log.error(f"  Page {pg} failed: {e}")
                break

        log.info(f"Collected {len(all_projects)} projects")
        return all_projects

    def _parse_project(self, raw: dict) -> dict:
        return {
            "name": raw.get("project", ""),
            "ys_project_id": raw.get("sypId"),
            "pre_sell_id": raw.get("id"),
            "permit_number": raw.get("strpreprojectid", ""),
            "permit_date": raw.get("passdate", ""),
            "developer": raw.get("name", ""),
            "address": raw.get("siteaddress", ""),
        }

    # -- phase 2: scrape project details -------------------------------

    async def _scrape_project(self, page: Page, project: dict) -> dict:
        """Navigate to a project's detail page and extract all building/unit data."""
        ys_id = project["ys_project_id"]
        ps_id = project["pre_sell_id"]
        url = f"{DETAIL_URL}?ysProjectId={ys_id}&preSellId={ps_id}"

        api_cache: dict[str, list] = {"buildings": [], "units": [], "building_info": []}

        async def capture(response: Response):
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                body = await response.json()
            except Exception:
                return
            resp_url = response.url
            if "getBuildingNameListToPublicity" in resp_url:
                api_cache["buildings"].append(body)
            elif "getHouseInfoListToPublicity" in resp_url:
                api_cache["units"].append(body)
            elif "getBuildingInfoToPublicity" in resp_url:
                api_cache["building_info"].append(body)

        page.on("response", capture)
        try:
            await page.goto("about:blank")
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(PAGE_SETTLE)

            bldg_list = []
            if api_cache["buildings"]:
                bldg_list = api_cache["buildings"][0].get("data", [])

            if not bldg_list:
                log.warning(f"  {project['name']}: no building data")
                return {**project, "buildings": [], "error": "no_buildings"}

            bldg_meta = {}
            if api_cache["building_info"]:
                for bi in api_cache["building_info"][0].get("data", []):
                    bldg_meta[str(bi.get("id"))] = bi

            # Wait for unit data if not yet arrived
            if not api_cache["units"]:
                try:
                    await page.wait_for_response(
                        lambda r: "getHouseInfoListToPublicity" in r.url,
                        timeout=10_000,
                    )
                    await asyncio.sleep(1)
                except Exception:
                    log.debug(f"  {project['name']}: unit API slow, reloading...")
                    api_cache["units"].clear()
                    await page.reload(wait_until="networkidle", timeout=30_000)
                    await asyncio.sleep(PAGE_SETTLE)

            buildings = []

            first_units = api_cache["units"][0]["data"] if api_cache["units"] else []
            buildings.append(
                self._build_building_record(bldg_list[0], first_units, bldg_meta)
            )

            for bldg in bldg_list[1:]:
                label = bldg["label"]
                try:
                    api_cache["building_info"].clear()
                    resp = await _wait_api(
                        page,
                        "getHouseInfoListToPublicity",
                        lambda lbl=label: page.get_by_role(
                            "radio", name=lbl, exact=True
                        ).click(),
                    )
                    await asyncio.sleep(0.5)
                    if api_cache["building_info"]:
                        for bi in api_cache["building_info"][-1].get("data", []):
                            bldg_meta[str(bi.get("id"))] = bi

                    buildings.append(
                        self._build_building_record(bldg, resp.get("data", []), bldg_meta)
                    )
                except Exception as e:
                    log.warning(f"  {project['name']}/{label} failed: {e}")
                    buildings.append({
                        "building_name": label,
                        "building_id": bldg.get("key"),
                        "units": [],
                        "error": str(e),
                    })

            project["buildings"] = buildings
            total_units = sum(len(b.get("units", [])) for b in buildings)
            return project
        finally:
            page.remove_listener("response", capture)

    def _build_building_record(
        self, bldg: dict, units_data: list[dict], bldg_meta: dict
    ) -> dict:
        bldg_id = bldg.get("key", "")
        meta = bldg_meta.get(bldg_id, {})

        units = []
        for floor_group in units_data:
            for unit in floor_group.get("list", []):
                gross = unit.get("ysbuildingarea", 0) or 0
                net = unit.get("ysinsidearea", 0) or 0
                shared = unit.get("ysexpandarea", 0) or 0
                ratio = round(net / gross, 4) if gross > 0 else None

                units.append({
                    "unit_id": unit.get("housenb", ""),
                    "floor": unit.get("floor", ""),
                    "section": unit.get("buildingbranch", ""),
                    "usage": unit.get("useage", ""),
                    "gross_area": gross,
                    "net_area": net,
                    "shared_area": shared,
                    "net_ratio": ratio,
                    "status": unit.get("lastStatusName", ""),
                    "price_per_sqm": unit.get("askpriceeachB"),
                    "total_price": unit.get("askpricetotalB"),
                })

        return {
            "building_name": bldg.get("label", ""),
            "building_id": bldg_id,
            "building_area": meta.get("buildingarea"),
            "unit_count": meta.get("unitsum"),
            "building_type": meta.get("type", ""),
            "structure": meta.get("structure", ""),
            "floors_above": meta.get("mainbuildingUnderfloor"),
            "floors_below": meta.get("mainbuildingUpfloor"),
            "units": units,
        }

    # -- worker --------------------------------------------------------

    async def _worker(self, worker_id: int, context, queue: asyncio.Queue):
        """Worker coroutine: takes projects from queue, scrapes them."""
        page = await context.new_page()
        try:
            while True:
                try:
                    idx, proj = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                name = proj.get("name", "?")
                self._done_count += 1
                log.info(f"[{self._done_count}/{self._total_remaining}] {name} (w{worker_id})")

                try:
                    data = await self._scrape_project(page, proj)
                    total_units = sum(len(b.get("units", [])) for b in data.get("buildings", []))
                    log.info(f"  {name}: {len(data.get('buildings', []))} bldg, {total_units} units")
                except Exception as e:
                    log.error(f"  {name} FAILED: {e}")
                    data = {**proj, "buildings": [], "error": str(e)}

                async with self._lock:
                    self._results.append(data)
                    self._scraped_ids.add(str(proj["ys_project_id"]))

                if self._done_count % 10 == 0:
                    await self._save_progress()
        finally:
            await page.close()

    # -- main -----------------------------------------------------------

    def run(self):
        asyncio.run(self._async_run())

    async def _async_run(self):
        chrome_proc = _launch_chrome()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
                context = browser.contexts[0]

                try:
                    await self._run_with_context(context)
                finally:
                    await browser.close()
        finally:
            chrome_proc.terminate()
            chrome_proc.wait(timeout=5)

    async def _run_with_context(self, context):
        ckpt = self._load_checkpoint() if self.resume else {}

        if ckpt.get("projects"):
            self._projects = ckpt["projects"]
            self._scraped_ids = set(ckpt.get("scraped_ids", []))
            log.info(
                f"Resumed: {len(self._projects)} projects, "
                f"{len(self._scraped_ids)} done"
            )
        else:
            page = await context.new_page()
            try:
                self._projects = await self._collect_projects(page)
            finally:
                await page.close()
            self._scraped_ids = set()
            await self._save_progress()

        remaining = [
            p for p in self._projects
            if str(p.get("ys_project_id")) not in self._scraped_ids
        ]
        if self.max_projects:
            remaining = remaining[: self.max_projects]

        self._total_remaining = len(remaining)
        self._done_count = 0
        log.info(f"Scraping {self._total_remaining} projects with {self.workers} worker(s)...")

        if OUTPUT_FILE.exists() and self.resume:
            self._results = json.loads(OUTPUT_FILE.read_text())

        # Fill queue
        queue: asyncio.Queue = asyncio.Queue()
        for i, proj in enumerate(remaining):
            queue.put_nowait((i, proj))

        # Launch workers
        workers = [
            self._worker(w, context, queue)
            for w in range(self.workers)
        ]
        await asyncio.gather(*workers)
        await self._save_progress()

        log.info(f"Done! {len(self._results)} projects saved to {OUTPUT_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Scrape 深圳住建局 per-unit area data")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent browser tabs")
    parser.add_argument("--max-projects", type=int, default=0, help="Limit projects (0=all)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()

    scraper = GovScraper(
        workers=args.workers,
        max_projects=args.max_projects,
        resume=args.resume,
    )
    scraper.run()


if __name__ == "__main__":
    main()
