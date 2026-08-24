"""Build app-layer data files from the base layer.

Reads data/base/* and produces app/public/* files optimized for the frontend.

Outputs:
  data.json           — map dots (gov xiaoqu + chengzhongcun)
  communities.json    — slim community index (no inline rentals)
  details.json        — anjuke community details
  rentals/{name}.json — per-community rental listings (loaded on demand)
"""

import csv
import json
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BASE_DIR = DATA_DIR / "base"
OUTPUT_DIR = ROOT / "app" / "public"


def load_base(name: str) -> list | dict:
    with open(BASE_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def build_data_json() -> list[dict]:
    """Build map dot data from gov CSVs (xiaoqu + chengzhongcun)."""
    rows = []
    # Xiaoqu
    with open(DATA_DIR / "xiaoqu_geocoded.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["district"] != "南山区":
                continue
            rows.append({
                "name": r["name"],
                "district": r["district"],
                "street": r["street"],
                "address": r["address"],
                "lng": float(r["lng"]),
                "lat": float(r["lat"]),
                "type": "xiaoqu",
                "high_rent": float(r["high_rent"]) if r["high_rent"] else None,
                "low_rent": float(r["low_rent"]) if r["low_rent"] else None,
                "multi_rent": float(r["multi_rent"]) if r["multi_rent"] else None,
            })
    # Chengzhongcun
    with open(DATA_DIR / "chengzhongcun_geocoded.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["district"] != "南山区":
                continue
            def fv(k: str) -> float | None:
                return float(r[k]) if r.get(k) else None
            rows.append({
                "name": r["name"],
                "district": r["district"],
                "street": r["street"],
                "address": r.get("address", ""),
                "lng": float(r["lng"]),
                "lat": float(r["lat"]),
                "type": "chengzhongcun",
                "single_room": fv("single_room"),
                "one_bed": fv("one_bed"),
                "two_bed": fv("two_bed"),
                "three_plus": fv("three_plus"),
            })
    return rows


def build_communities_and_rentals(
    communities: list[dict],
    aj_rentals: list[dict],
    ly_rentals: list[dict],
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Build slim community index and per-community rental files.

    Returns (community_index, rentals_by_name).
    """
    # Group anjuke rentals by community_id
    aj_by_cid: dict[str, list[dict]] = {}
    for r in aj_rentals:
        aj_by_cid.setdefault(r["community_id"], []).append(r)

    # Group leyoujia rentals by community_id
    ly_by_cid: dict[str, list[dict]] = {}
    for r in ly_rentals:
        ly_by_cid.setdefault(r["community_id"], []).append(r)

    index: list[dict] = []
    rentals_by_name: dict[str, list[dict]] = {}

    for c in communities:
        name = c["name"]

        # Collect all rentals for this community
        all_rentals: list[dict] = []
        for aid in c.get("anjuke_ids", []):
            for r in aj_by_cid.get(aid, []):
                all_rentals.append({
                    "price": r["price"],
                    "layout": r["layout"],
                    "rooms": r["rooms"],
                    "area": r["area"],
                    "floor": r["floor"],
                    "decoration": r["decoration"],
                    "price_sqm": r.get("price_sqm"),
                    "source": "anjuke",
                })
        for lid in c.get("leyoujia_ids", []):
            for r in ly_by_cid.get(lid, []):
                all_rentals.append({
                    "price": r["price"],
                    "layout": r["layout"],
                    "rooms": r["rooms"],
                    "area": r["area"],
                    "floor": r["floor"],
                    "decoration": r["decoration"],
                    "price_sqm": r.get("price_sqm"),
                    "source": "leyoujia",
                })

        # Slim community entry (no rental arrays)
        entry: dict = {
            "name": name,
            "matched": c["gov_match"],
        }
        if c.get("street"):
            entry["street"] = c["street"]
        if c.get("lat"):
            entry["lat"] = c["lat"]
            entry["lng"] = c["lng"]
        if c.get("gov_prices"):
            for k, v in c["gov_prices"].items():
                entry[k] = v

        # Community details
        if c.get("details"):
            for k, v in c["details"].items():
                entry[k] = v

        # Rental summary stats
        if all_rentals:
            prices_sqm = sorted(r["price_sqm"] for r in all_rentals if r.get("price_sqm"))
            entry["rental_count"] = len(all_rentals)
            if prices_sqm:
                entry["rental_median_sqm"] = prices_sqm[len(prices_sqm) // 2]
            rentals_by_name[name] = all_rentals

        index.append(entry)

    return index, rentals_by_name


def sanitize_filename(name: str) -> str:
    """Convert community name to a safe filename."""
    # Replace problematic chars
    return re.sub(r'[/\\:*?"<>|\n]', "_", name)


def main() -> None:
    communities = load_base("communities.json")
    aj_rentals = load_base("anjuke_rentals.json")
    ly_rentals = load_base("leyoujia_rentals.json")

    # 1. data.json — map dots
    # data.json uses GCJ-02 coordinates (for Leaflet with Chinese tiles).
    # It is maintained manually and NOT regenerated from the CSV (which is WGS-84).
    data_path = OUTPUT_DIR / "data.json"
    if data_path.exists():
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
        log.info("data.json: %d entries (%.0f KB) [kept]", len(data), data_path.stat().st_size / 1024)
    else:
        log.warning("data.json not found — run build_data_json() or restore from git")
        data = []

    # Build GCJ-02 coordinate index from data.json (the authoritative map coords)
    gcj02_coords: dict[str, tuple[float, float]] = {}
    for d in data:
        gcj02_coords[d["name"]] = (d["lat"], d["lng"])

    # 2. communities.json + rentals/
    comm_index, rentals_by_name = build_communities_and_rentals(
        communities, aj_rentals, ly_rentals,
    )
    # Patch coordinates to GCJ-02 (matching data.json / map tiles)
    for c in comm_index:
        if c["name"] in gcj02_coords:
            c["lat"], c["lng"] = gcj02_coords[c["name"]]
    comm_path = OUTPUT_DIR / "communities.json"
    with open(comm_path, "w", encoding="utf-8") as f:
        json.dump(comm_index, f, ensure_ascii=False)
    log.info(
        "communities.json: %d entries (%.0f KB), %d with rentals",
        len(comm_index), comm_path.stat().st_size / 1024,
        sum(1 for c in comm_index if c.get("rental_count")),
    )

    # 3. Per-community rental files
    rentals_dir = OUTPUT_DIR / "rentals"
    rentals_dir.mkdir(exist_ok=True)
    # Clean old files
    for old in rentals_dir.glob("*.json"):
        old.unlink()
    total_size = 0
    for name, rentals in rentals_by_name.items():
        fname = sanitize_filename(name) + ".json"
        path = rentals_dir / fname
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rentals, f, ensure_ascii=False)
        total_size += path.stat().st_size
    log.info(
        "rentals/: %d files (%.1f MB total)",
        len(rentals_by_name), total_size / 1024 / 1024,
    )

    # 4. details.json — anjuke community details (for backward compat)
    details = []
    for c in communities:
        if not c.get("details"):
            continue
        for aid in c.get("anjuke_ids", []):
            entry = {"id": aid, "name": c["name"]}
            entry.update(c["details"])
            details.append(entry)
            break  # one entry per community
    details_path = OUTPUT_DIR / "details.json"
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False)
    log.info("details.json: %d entries (%.0f KB)", len(details), details_path.stat().st_size / 1024)


if __name__ == "__main__":
    main()
