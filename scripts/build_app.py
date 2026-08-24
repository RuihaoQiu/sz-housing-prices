"""Build app-layer data files from the base layer.

Reads data/base/* and produces app/public/* files for the frontend.

Outputs:
  data.json          — map dots (kept as-is, GCJ-02 coordinates)
  communities.json   — community index with inline rentals
  details.json       — anjuke community details (小区解读 etc.)
"""

import json
import logging
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


def build_communities(
    communities: list[dict],
    aj_rentals: list[dict],
    ly_rentals: list[dict],
    gcj02_coords: dict[str, tuple[float, float]],
) -> list[dict]:
    """Build community index with inline rentals."""
    # Group rentals by community_id
    aj_by_cid: dict[str, list[dict]] = {}
    for r in aj_rentals:
        aj_by_cid.setdefault(r["community_id"], []).append(r)

    ly_by_cid: dict[str, list[dict]] = {}
    for r in ly_rentals:
        ly_by_cid.setdefault(r["community_id"], []).append(r)

    RENTAL_FIELDS = ("price", "layout", "rooms", "area", "floor", "decoration", "price_sqm")
    result: list[dict] = []

    for c in communities:
        name = c["name"]

        # Collect rentals
        rentals: list[dict] = []
        for aid in c.get("anjuke_ids", []):
            for r in aj_by_cid.get(aid, []):
                rentals.append({k: r.get(k) for k in RENTAL_FIELDS})
        for lid in c.get("leyoujia_ids", []):
            for r in ly_by_cid.get(lid, []):
                rentals.append({k: r.get(k) for k in RENTAL_FIELDS})

        entry: dict = {
            "name": name,
            "matched": c["gov_match"],
        }
        if c.get("street"):
            entry["street"] = c["street"]

        # Use GCJ-02 coords from data.json when available, fall back to base layer
        if name in gcj02_coords:
            entry["lat"], entry["lng"] = gcj02_coords[name]
        elif c.get("lat"):
            entry["lat"] = c["lat"]
            entry["lng"] = c["lng"]

        if c.get("gov_prices"):
            for k, v in c["gov_prices"].items():
                entry[k] = v

        if c.get("details"):
            for k, v in c["details"].items():
                entry[k] = v

        if rentals:
            entry["rentals"] = rentals

        result.append(entry)

    return result


def main() -> None:
    communities = load_base("communities.json")
    aj_rentals = load_base("anjuke_rentals.json")
    ly_rentals = load_base("leyoujia_rentals.json")

    # data.json uses GCJ-02 coordinates — kept as-is, not regenerated
    data_path = OUTPUT_DIR / "data.json"
    if data_path.exists():
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
        log.info("data.json: %d entries (%.0f KB) [kept]", len(data), data_path.stat().st_size / 1024)
    else:
        log.warning("data.json not found — restore from git")
        data = []

    # GCJ-02 coordinate index from data.json
    gcj02_coords = {d["name"]: (d["lat"], d["lng"]) for d in data}

    # communities.json — full index with inline rentals
    comm = build_communities(communities, aj_rentals, ly_rentals, gcj02_coords)
    comm_path = OUTPUT_DIR / "communities.json"
    with open(comm_path, "w", encoding="utf-8") as f:
        json.dump(comm, f, ensure_ascii=False)
    with_rentals = sum(1 for c in comm if c.get("rentals"))
    total_listings = sum(len(c.get("rentals", [])) for c in comm)
    log.info(
        "communities.json: %d entries (%.1f MB), %d with rentals (%d listings)",
        len(comm), comm_path.stat().st_size / 1024 / 1024, with_rentals, total_listings,
    )

    # details.json — anjuke community details
    details = []
    for c in communities:
        if not c.get("details"):
            continue
        for aid in c.get("anjuke_ids", []):
            entry = {"id": aid, "name": c["name"]}
            entry.update(c["details"])
            details.append(entry)
            break
    details_path = OUTPUT_DIR / "details.json"
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False)
    log.info("details.json: %d entries (%.0f KB)", len(details), details_path.stat().st_size / 1024)


if __name__ == "__main__":
    main()
