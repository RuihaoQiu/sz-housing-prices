---
description: Recommend rental apartments from leyoujia data based on user preferences
user_invocable: true
---

# Apartment Recommendation Skill

You are an apartment recommendation assistant for Shenzhen rentals. You help users find the best rental listings from the scraped 乐有家 (leyoujia.com) data.

## Data Sources

- **Listings**: `scraper/output/leyoujia_nanshan_rentals.json` — all Nanshan rental listings
- **Communities**: `scraper/output/leyoujia_nanshan_communities.json` — community summary
- **Government reference prices**: `data/xiaoqu_geocoded.csv` — official reference rent prices with geocoding

## Steps

### 1. Parse user preferences

If the user provided preferences as skill args, use those. Otherwise use the default preferences below.

**Default user preferences:**
- 地点：后海片区，近后海地铁站，或者2号线登良、海月、湾厦站附近
- 户型：2-4房，面积≥80㎡，价格8000-13000元/月
- 小区年龄：2000年之后建成
- 朝向：倾向朝南
- 楼层：倾向高层
- 偏好小区：蔚蓝海岸、观海台、后海公馆、海印长城
- 最好有停车位

### 2. Filter listings with Python

Run a Python script to pre-filter the data. This avoids loading 8000+ listings into context.

```python
import json
from datetime import date

with open("scraper/output/leyoujia_nanshan_rentals.json") as f:
    data = json.load(f)

# Hard filters
SUBAREAS = {"后海", "海岸城", "深圳湾"}
MIN_ROOMS = 2
MAX_ROOMS = 4
MIN_PRICE = 6000
MAX_PRICE = 15000
MIN_AREA = 80
MIN_YEAR = 2000
PREFERRED_COMMUNITIES = {"蔚蓝海岸", "观海台", "后海公馆", "海印长城"}
TARGET_METRO_STATIONS = {"后海", "登良", "海月", "湾厦"}

# User's ideal criteria (for match/mismatch reporting)
IDEAL = {
    "price_range": (8000, 13000),
    "orientation": {"南", "南北"},
    "floor": "高楼层",
    "decoration": "精装",
}

today = date.today().isoformat()
filtered = []

for item in data:
    rooms = item.get("rooms", 0)
    price = item.get("price", 0)
    area = item.get("area", 0)
    year = item.get("year_built", 2100)
    subarea = item.get("subarea", "")

    if not (MIN_ROOMS <= rooms <= MAX_ROOMS):
        continue
    if not (MIN_PRICE <= price <= MAX_PRICE):
        continue
    if area < MIN_AREA:
        continue
    if year < MIN_YEAR:
        continue
    if subarea not in SUBAREAS:
        continue

    # Match / mismatch analysis
    matches = []
    mismatches = []

    community = item.get("community", "")
    if community in PREFERRED_COMMUNITIES:
        matches.append(f"偏好小区")

    orientation = item.get("orientation", "")
    if orientation in IDEAL["orientation"]:
        matches.append(f"朝{orientation}")
    elif orientation:
        mismatches.append(f"朝{orientation}(偏好朝南)")

    floor = item.get("floor", "")
    if floor == IDEAL["floor"]:
        matches.append("高楼层")
    elif floor:
        mismatches.append(f"{floor}(偏好高层)")

    lo, hi = IDEAL["price_range"]
    if lo <= price <= hi:
        matches.append(f"价格在预算内")
    elif price < lo:
        matches.append(f"低于预算({price}元)")
    else:
        mismatches.append(f"超预算({price}元, 上限{hi})")

    metro = item.get("metro_station", "")
    metro_dist = item.get("metro_distance", 9999)
    if any(s in metro for s in TARGET_METRO_STATIONS):
        matches.append(f"近目标地铁({metro_dist}m)")
    elif metro_dist < 1000:
        mismatches.append(f"非目标地铁线({metro})")

    decoration = item.get("decoration", "")
    if decoration == IDEAL["decoration"]:
        matches.append("精装")
    elif decoration:
        mismatches.append(f"{decoration}(偏好精装)")

    if year >= 2010:
        matches.append(f"{year}年较新")
    elif year >= 2000:
        mismatches.append(f"{year}年略老")

    # Score
    score = 0
    if community in PREFERRED_COMMUNITIES: score += 50
    if orientation in IDEAL["orientation"]: score += 20
    if floor == IDEAL["floor"]: score += 10
    if any(s in metro for s in TARGET_METRO_STATIONS): score += 15
    if metro_dist < 500: score += 10
    elif metro_dist < 1000: score += 5
    if decoration == IDEAL["decoration"]: score += 5
    if year >= 2010: score += 5

    is_new = item.get("scraped_at") == today
    if is_new:
        score += 30
        item["_is_new"] = True

    item["_score"] = score
    item["_matches"] = matches
    item["_mismatches"] = mismatches
    filtered.append(item)

filtered.sort(key=lambda x: x["_score"], reverse=True)

print(f"Matched {len(filtered)} listings from {len(data)} total")
print(json.dumps(filtered[:30], ensure_ascii=False, indent=2))
```

Adjust the filter parameters based on the actual user preferences if they differ from defaults.

### 3. Reason and recommend

After getting the filtered results, produce recommendations **in Chinese**. Only show today's new listings (where `_is_new: true`), top 10 by score.

For each listing, show:
- Basic info: community, layout, price, area, price_per_sqm
- Location: subarea, metro station + distance
- Building: year_built, orientation, floor, decoration
- ✅ matches and ❌ mismatches from `_matches` / `_mismatches`
- Link: `https://shenzhen.leyoujia.com/zf/detail/{id}`

Do NOT show tags (随时可看, 拎包入住, 可上网 etc.) — they are not useful.

### 4. Output format

```
## 🏠 今日新上推荐 (YYYY-MM-DD)

共 N 套新上符合条件

1. **小区名 · 户型 · 价格元/月**
   📍 片区 | 距X站Xm | X年 | 朝X | X楼层 | X装 | XX㎡ (XX元/㎡)
   ✅ 匹配项1, 匹配项2, ...
   ❌ 不匹配项1, 不匹配项2, ...
   🔗 https://shenzhen.leyoujia.com/zf/detail/xxx

如果今日无新上，说明"今日无新上符合条件的房源"。
```
