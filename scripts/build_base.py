"""Build the base data layer from raw sources.

Reads government CSVs, scraper output, and manual mappings to produce
normalized base files that downstream applications consume.

Outputs (in data/base/):
  gov.json              — government reference price records
  communities.json      — unified community registry
  anjuke_rentals.json   — normalized anjuke listings (active + removed)
  leyoujia_rentals.json — normalized leyoujia listings (active + removed)
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
SCRAPER_DIR = ROOT / "scraper" / "output"
BASE_DIR = DATA_DIR / "base"

DISTRICT = "南山区"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_anjuke_name(raw: str) -> str:
    """Extract clean community name from Anjuke's junk-filled name field."""
    m = re.match(r"^(.+?)(?:\d{4}年|数据由)", raw)
    return m.group(1).strip() if m else raw.strip()


def parse_anjuke_area(area_str: str) -> float | None:
    m = re.search(r"([\d.]+)", area_str)
    return float(m.group(1)) if m else None


def parse_anjuke_rooms(layout: str) -> int | None:
    m = re.match(r"(\d+)室", layout)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_gov() -> list[dict]:
    """Load government reference price data for the target district."""
    rows = []
    with open(DATA_DIR / "xiaoqu_geocoded.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["district"] != DISTRICT:
                continue
            rows.append({
                "name": r["name"],
                "street": r["street"],
                "address": r["address"],
                "lat": float(r["lat"]),
                "lng": float(r["lng"]),
                "multi_rent": float(r["multi_rent"]) if r["multi_rent"] else None,
                "high_rent": float(r["high_rent"]) if r["high_rent"] else None,
                "low_rent": float(r["low_rent"]) if r["low_rent"] else None,
            })
    return rows


def load_manual_map() -> dict[str, str]:
    """Load anjuke_id -> gov_name manual mappings."""
    path = DATA_DIR / "manual_map.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v["gov_name"] for k, v in data["anjuke"].items()}


def load_anjuke_communities() -> list[dict]:
    """Load Anjuke community details with cleaned names."""
    with open(SCRAPER_DIR / "anjuke_communities.json", encoding="utf-8") as f:
        details = json.load(f)
    for d in details:
        d["name"] = clean_anjuke_name(d["name"])
    return details


def load_anjuke_rentals() -> list[dict]:
    """Load and normalize all anjuke rentals (active + removed)."""
    records = []
    for filename, active in [("anjuke_rentals.json", True), ("anjuke_rentals_removed.json", False)]:
        with open(SCRAPER_DIR / filename, encoding="utf-8") as f:
            raw = json.load(f)
        for r in raw:
            cid = r.get("community_id")
            if not cid:
                continue
            layout = r.get("户型", "")
            area = parse_anjuke_area(r.get("面积", ""))
            rooms = parse_anjuke_rooms(layout)
            price = r["price"]
            listing: dict = {
                "community_id": cid,
                "price": price,
                "layout": layout,
                "rooms": rooms,
                "area": area,
                "floor": r.get("楼层", ""),
                "decoration": r.get("装修", ""),
                "active": active,
            }
            if price and area:
                listing["price_sqm"] = round(price / area, 1)
            records.append(listing)
    return records


def load_leyoujia_rentals() -> list[dict]:
    """Load and normalize all leyoujia rentals (active + removed)."""
    records = []
    for filename, active in [("leyoujia_rentals.json", True), ("leyoujia_rentals_removed.json", False)]:
        path = SCRAPER_DIR / filename
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        for r in raw:
            cid = str(r["community_id"])
            price = r.get("price")
            if not price:
                continue
            layout = r.get("layout", "")
            area = r.get("area")
            rooms = r.get("rooms")
            listing: dict = {
                "community_id": cid,
                "community_name": r.get("community", ""),
                "price": price,
                "layout": layout,
                "rooms": rooms,
                "area": area,
                "floor": r.get("floor", ""),
                "decoration": r.get("decoration", ""),
                "active": active,
            }
            if price and area:
                listing["price_sqm"] = round(price / area, 1)
            records.append(listing)
    return records


# ---------------------------------------------------------------------------
# Community registry builder
# ---------------------------------------------------------------------------

def build_communities(
    gov: list[dict],
    anjuke: list[dict],
    manual_map: dict[str, str],
    anjuke_rentals: list[dict],
    leyoujia_rentals: list[dict],
) -> list[dict]:
    """Build unified community registry.

    Each entry represents one physical community with cross-references
    to gov data, anjuke IDs, and leyoujia IDs.
    """
    # Gov index: name -> record (unique names only)
    gov_by_name: dict[str, list[dict]] = {}
    for g in gov:
        gov_by_name.setdefault(g["name"], []).append(g)
    gov_index = {name: recs[0] for name, recs in gov_by_name.items() if len(recs) == 1}

    # Validate manual mappings
    gov_name_set = {g["name"] for g in gov}
    bad = {k: v for k, v in manual_map.items() if v not in gov_name_set}
    if bad:
        log.error("Manual mappings point to non-existent gov names:")
        for k, v in bad.items():
            log.error("  %s -> %s", k, v)
        raise SystemExit(1)

    # Collect anjuke rental community names (for orphans)
    anjuke_rental_names: dict[str, str] = {}
    for r in anjuke_rentals:
        cid = r["community_id"]
        if cid not in anjuke_rental_names:
            anjuke_rental_names[cid] = cid  # fallback

    # Re-derive from raw data for proper name extraction
    for filename in ("anjuke_rentals.json", "anjuke_rentals_removed.json"):
        with open(SCRAPER_DIR / filename, encoding="utf-8") as f:
            for r in json.load(f):
                cid = r.get("community_id")
                if cid and cid not in anjuke_rental_names and r.get("小区"):
                    anjuke_rental_names[cid] = re.sub(r"\(.*\)", "", r["小区"]).strip()

    # Anjuke rental counts by community_id
    aj_rental_cids = set(r["community_id"] for r in anjuke_rentals)

    # Leyoujia: build name -> community_ids index
    ly_name_to_ids: dict[str, set[str]] = {}
    for r in leyoujia_rentals:
        name = r.get("community_name", "")
        if name:
            ly_name_to_ids.setdefault(name, set()).add(r["community_id"])

    # Track which communities we've registered
    communities: list[dict] = []
    registered_names: dict[str, int] = {}  # name -> index in communities
    seen_anjuke_ids: set[str] = set()

    def resolve_gov(name: str, anjuke_id: str | None) -> dict | None:
        """Try to find gov record by name or manual mapping."""
        rec = gov_index.get(name)
        if not rec and anjuke_id and anjuke_id in manual_map:
            rec = gov_index.get(manual_map[anjuke_id])
        return rec

    def make_entry(
        name: str,
        gov_rec: dict | None,
        anjuke_ids: list[str],
        leyoujia_ids: list[str],
        details: dict | None = None,
    ) -> dict:
        entry: dict = {
            "name": gov_rec["name"] if gov_rec else name,
            "gov_match": gov_rec is not None,
            "anjuke_ids": anjuke_ids,
            "leyoujia_ids": leyoujia_ids,
        }
        if gov_rec:
            entry["street"] = gov_rec["street"]
            entry["address"] = gov_rec["address"]
            entry["lat"] = gov_rec["lat"]
            entry["lng"] = gov_rec["lng"]
            entry["gov_prices"] = {
                "multi_rent": gov_rec["multi_rent"],
                "high_rent": gov_rec["high_rent"],
                "low_rent": gov_rec["low_rent"],
            }
        if details:
            entry["details"] = details
        return entry

    # 1) Register anjuke communities (with detail pages)
    for a in anjuke:
        aid = a["id"]
        seen_anjuke_ids.add(aid)
        gov_rec = resolve_gov(a["name"], aid)
        canonical = gov_rec["name"] if gov_rec else a["name"]

        details = {}
        for field in ("竣工时间", "总户数", "建筑类型", "所属商圈", "物业费", "绿化率", "容积率"):
            details[field] = a.get(field)

        # Check for leyoujia match by name
        ly_ids = sorted(ly_name_to_ids.get(a["name"], set()))

        if canonical in registered_names:
            # Merge into existing (e.g. multiple anjuke IDs → same gov name)
            idx = registered_names[canonical]
            if aid not in communities[idx]["anjuke_ids"]:
                communities[idx]["anjuke_ids"].append(aid)
            for lid in ly_ids:
                if lid not in communities[idx]["leyoujia_ids"]:
                    communities[idx]["leyoujia_ids"].append(lid)
            if not communities[idx].get("details"):
                communities[idx]["details"] = details
        else:
            entry = make_entry(canonical, gov_rec, [aid], ly_ids, details)
            registered_names[canonical] = len(communities)
            communities.append(entry)

    # 2) Add orphan anjuke communities (appear in rentals but no detail page)
    orphan_ids = aj_rental_cids - seen_anjuke_ids
    for cid in sorted(orphan_ids):
        name = anjuke_rental_names.get(cid, f"unknown-{cid}")
        gov_rec = resolve_gov(name, cid)
        canonical = gov_rec["name"] if gov_rec else name

        ly_ids = sorted(ly_name_to_ids.get(name, set()))

        if canonical in registered_names:
            idx = registered_names[canonical]
            if cid not in communities[idx]["anjuke_ids"]:
                communities[idx]["anjuke_ids"].append(cid)
        else:
            entry = make_entry(canonical, gov_rec, [cid], ly_ids)
            registered_names[canonical] = len(communities)
            communities.append(entry)

    # 3) Add leyoujia-only communities (no anjuke match by name)
    for ly_name, ly_cids in sorted(ly_name_to_ids.items()):
        if ly_name in registered_names:
            # Already matched via anjuke name overlap
            idx = registered_names[ly_name]
            for lid in sorted(ly_cids):
                if lid not in communities[idx]["leyoujia_ids"]:
                    communities[idx]["leyoujia_ids"].append(lid)
            continue

        # Try gov match by name (no manual map for leyoujia yet)
        gov_rec = gov_index.get(ly_name)
        canonical = gov_rec["name"] if gov_rec else ly_name

        if canonical in registered_names:
            idx = registered_names[canonical]
            for lid in sorted(ly_cids):
                if lid not in communities[idx]["leyoujia_ids"]:
                    communities[idx]["leyoujia_ids"].append(lid)
        else:
            entry = make_entry(canonical, gov_rec, [], sorted(ly_cids))
            registered_names[canonical] = len(communities)
            communities.append(entry)

    return communities


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    # Load sources
    gov = load_gov()
    manual_map = load_manual_map()
    anjuke = load_anjuke_communities()
    aj_rentals = load_anjuke_rentals()
    ly_rentals = load_leyoujia_rentals()

    # Build community registry
    communities = build_communities(gov, anjuke, manual_map, aj_rentals, ly_rentals)

    # Write outputs
    def write_json(name: str, data: object) -> None:
        path = BASE_DIR / name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        size_mb = path.stat().st_size / 1024 / 1024
        log.info("  %s (%.1f MB)", path.relative_to(ROOT), size_mb)

    log.info("Writing base layer:")
    write_json("gov.json", gov)
    write_json("communities.json", communities)
    write_json("anjuke_rentals.json", aj_rentals)
    write_json("leyoujia_rentals.json", ly_rentals)

    # Stats
    gov_matched = sum(1 for c in communities if c["gov_match"])
    with_aj = sum(1 for c in communities if c["anjuke_ids"])
    with_ly = sum(1 for c in communities if c["leyoujia_ids"])
    with_both = sum(1 for c in communities if c["anjuke_ids"] and c["leyoujia_ids"])
    ly_only = sum(1 for c in communities if c["leyoujia_ids"] and not c["anjuke_ids"])

    log.info("")
    log.info("Communities: %d", len(communities))
    log.info("  Gov matched: %d", gov_matched)
    log.info("  With anjuke IDs: %d", with_aj)
    log.info("  With leyoujia IDs: %d", with_ly)
    log.info("  Both platforms: %d", with_both)
    log.info("  Leyoujia only: %d", ly_only)
    log.info("Anjuke rentals: %d", len(aj_rentals))
    log.info("Leyoujia rentals: %d", len(ly_rentals))


if __name__ == "__main__":
    main()
