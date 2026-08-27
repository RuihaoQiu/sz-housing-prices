---
description: Recommend rental apartments from leyoujia data based on user preferences
user_invocable: true
---

# Apartment Recommendation Skill

You are an apartment recommendation assistant for Shenzhen rentals. You help users find the best rental listings from the scraped 乐有家 (leyoujia.com) data.

## Data Sources

- **Listings**: `scraper/output/leyoujia_rentals.json` — all Nanshan rental listings
- **Communities**: `scraper/output/leyoujia_communities.json` — community summary
- **Government reference prices**: `data/xiaoqu_geocoded.csv` — official reference rent prices with geocoding

## Steps

### 1. Parse user preferences

If the user provided preferences as skill args, use those. Otherwise use the default preferences below.

**Default user preferences:**
- 地铁：2号线 登良、海月、湾厦站，11号线 后海、南山、红树湾南站，≤500m
- 户型：2-4房，面积≥80㎡，价格8000-13000元/月
- 小区年龄：2000年之后建成
- 朝向：不要朝北
- 楼层：倾向高层
- 装修：倾向精装
- 偏好小区：蔚蓝海岸、观海台、后海公馆、海印长城、海境界、后海理想雅园（偏好小区不受地铁过滤限制）

### 2. Filter and rank with Python

Filter by metro station proximity first, then rank by preference factors.

```python
import json
from datetime import date

with open("scraper/output/leyoujia_rentals.json") as f:
    data = json.load(f)

# --- Hard filters ---
MIN_ROOMS = 2
MAX_ROOMS = 4
MIN_PRICE = 6000
MAX_PRICE = 15000
MIN_AREA = 80
MIN_YEAR = 2000

# Primary location filter: metro stations
TARGET_STATIONS = {
    "登良", "海月", "湾厦",           # 2号线
    "后海", "南山站", "红树湾南",      # 11号线
}

# Preferred communities always pass the metro filter
PREFERRED_COMMUNITIES = {"蔚蓝海岸", "观海台", "后海公馆", "海印长城", "海境界", "后海理想雅园"}

# --- Ranking factors (soft preferences) ---
MAX_METRO_DIST = 500
BAD_ORIENTATION = {"北"}
IDEAL_FLOOR = "高楼层"
IDEAL_DECORATION = "精装"
IDEAL_PRICE_RANGE = (8000, 13000)

today = date.today().isoformat()
filtered = []

for item in data:
    rooms = item.get("rooms", 0)
    price = item.get("price", 0)
    area = item.get("area", 0)
    year = item.get("year_built", 0)

    # Hard filters: rooms, price, area
    if not (MIN_ROOMS <= rooms <= MAX_ROOMS):
        continue
    if not (MIN_PRICE <= price <= MAX_PRICE):
        continue
    if area < MIN_AREA:
        continue
    if year and year < MIN_YEAR:
        continue

    # Location filter: near target metro station (≤500m) OR preferred community
    community = item.get("community", "")
    in_preferred = any(p in community for p in PREFERRED_COMMUNITIES)
    metro = item.get("metro_station", "")
    metro_dist = item.get("metro_distance", 9999)
    near_target = any(s in metro for s in TARGET_STATIONS)

    if in_preferred:
        pass  # always include
    elif near_target and metro_dist <= MAX_METRO_DIST:
        pass  # close enough to target station
    else:
        continue

    # Orientation hard filter: reject 朝北
    orientation = item.get("orientation", "")
    if orientation in BAD_ORIENTATION:
        continue

    # --- Match / mismatch analysis ---
    matches = []
    mismatches = []

    if in_preferred:
        matches.append("偏好小区")
    if near_target:
        matches.append(f"距{metro.split('站')[0].split('线')[-1]}站{metro_dist}m")

    floor = item.get("floor", "")
    if floor == IDEAL_FLOOR:
        matches.append("高楼层")
    elif floor:
        mismatches.append(f"{floor}(偏好高层)")

    lo, hi = IDEAL_PRICE_RANGE
    if lo <= price <= hi:
        matches.append("价格在预算内")
    elif price < lo:
        matches.append(f"低于预算({price}元)")
    else:
        mismatches.append(f"超预算({price}元, 上限{hi})")

    decoration = item.get("decoration", "")
    if decoration == IDEAL_DECORATION:
        matches.append("精装")
    elif decoration:
        mismatches.append(f"{decoration}(偏好精装)")

    if year >= 2010:
        matches.append(f"{year}年较新")
    elif year >= 2000:
        mismatches.append(f"{year}年略老")
    elif not year:
        mismatches.append("年份未知")

    # --- Score (ranking) ---
    score = 0
    if in_preferred:                        score += 50
    if near_target and metro_dist <= 200:   score += 15
    elif near_target and metro_dist <= 500: score += 10
    if floor == IDEAL_FLOOR:                score += 10
    if decoration == IDEAL_DECORATION:      score += 5
    if year >= 2010:                        score += 5
    if lo <= price <= hi:                   score += 5

    is_new = item.get("scraped_at") == today
    if is_new:
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
