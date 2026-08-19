"""Match Anjuke communities to government reference price data.

Uses government names as canonical standard.
Strategy: exact match first, then manual mapping for known correspondences.
"""

import csv
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
SCRAPER_DIR = Path(__file__).parent.parent / "scraper" / "output"
OUTPUT_DIR = Path(__file__).parent.parent / "app" / "public"

# Manual mapping: anjuke_id -> gov_name
# For 1:N cases (Anjuke has no phase, gov has multiple), pick the main/first one.
# For ambiguous 商务公寓/商品住房 splits, pick 商品住房 (residential).
MANUAL_MAP: dict[str, str] = {
    # Paren style: half-width () -> full-width （） or stripped
    "95377": "星海名城一期",
    "863352": "星海名城三期",
    "863355": "星海名城二期",
    "863354": "星海名城五期",
    "863353": "星海名城六期",
    "659772": "万科云城一期",
    "95595": "中山颐景花园一期",
    "95431": "南海玫瑰花园一期",
    "95346": "南海玫瑰花园三期",
    "95349": "南海玫瑰花园二期",
    "95533": "电力花园一期",
    "384285": "泛海拉菲花园二期",
    "323631": "英伦名苑一期",
    "98229": "英伦名苑三期",
    "95674": "英伦名苑二期",
    "401916": "海境界家园一期",
    "599051": "澳城花园北区",
    "842238": "澳城花园南区",
    "946148": "后海名苑居南区",
    "95733": "半岛花园A区",
    "296126": "半岛花园B区",
    "843448": "龙电花园A区",
    "120816": "龙电花园B区",
    "871576": "松坪村三期西区",
    "571111": "松坪村三期东区",
    "296310": "桃源村三期",
    # Anjuke adds prefix (波托菲诺, 招商, etc.), gov uses shorter name
    "185654": "纯水岸一期",
    "190914": "纯水岸七期",
    "323602": "纯水岸九期",
    "618858": "纯水岸十五期",
    "660198": "纯水岸十六期",
    "521459": "纯水岸十四期",
    "97538": "纯水岸四期",
    "97396": "海月华庭",
    "95608": "海月花园一期",
    "97382": "海月花园三期",
    "97542": "海月花园二期",
    "95594": "雍华府",
    "843111": "香瑞园",  # 佳兆业香瑞园(北区) - only one gov entry
    "97266": "香瑞园",  # 佳兆业香瑞园(南区) - same gov entry
    "191489": "翠岭居",  # 特发信息科技园翠岭居
    "95783": "海阔天空雅居",  # 中信海阔天空雅居
    "95429": "深圳湾畔花园",  # 中海深圳湾畔花园
    "95681": "方卉园",  # 马家龙方卉园
    "95760": "汀兰鹭榭花园",  # 瑞河耶纳(汀兰鹭榭花园)
    # Anjuke name is short form, gov adds suffix (花园/大厦/小区/家园 etc.)
    "97228": "一辉花园一期",
    "95403": "东方新地苑",
    "95380": "俊峰丽舍花园",
    "864687": "前海东岸花园",
    "791691": "前海丹华园",
    "907316": "地铁前海时代广场",
    "95479": "前海金岸大厦",
    "115319": "华府假日大厦",
    "98127": "华彩天成居",
    "95413": "南国丽城花园",
    "214623": "君汇新天花园",
    "370496": "四季丽晶公寓",
    "95614": "四海宜家大厦",
    "95762": "城市假日花园",
    "115357": "城市印象家园",
    "872674": "塘朗城广场",
    "364235": "岸芷汀兰花园",
    "872207": "海岸明珠园",
    "95468": "港湾丽都花园",
    "95795": "港湾生活小区",
    "97287": "皇庭港湾花园",
    "95588": "石云村小区",
    "95649": "红树西岸花园",
    "228075": "绿海湾花园",
    "95601": "绿茵丰和家园",
    "95397": "缤纷假日豪园",
    "95477": "缤纷年华家园",
    "370613": "翡翠海岸花园",
    "95502": "荔林春晓小区",
    "95452": "春树里小区",
    "653731": "曦湾天馥名苑",
    "95393": "欧陆经典花园",
    "95347": "金海岸大厦",
    "95437": "豪方天际花园一期",
    "440109": "鼎胜山邻居",
    "787008": "鼎胜金域世家豪园",
    "766403": "香山美墅花园",
    "251013": "颐安阅海台",
    "95426": "珠光花半里欣苑",
    "95686": "翠薇园住宅楼",
    # Gov uses different prefix or wrapper
    "95467": "南山汇金家园",  # 汇金家园
    "95375": "南油百富大厦",  # 百富大厦
    "95465": "南油福临苑",  # 福临苑
    "95696": "南油南海大厦",  # 南海大厦
    "97557": "荣超侨香诺园",  # 侨香诺园
    "95536": "前海天朗风清家园",  # 天朗风清
    "95642": "科苑学里揽翠居",  # 科苑学里
    "95539": "华采花园(华彩花园)",  # 华彩花园
    "95531": "悠然居",  # 豪方悠然居
    "95412": "后海花半里",  # 后海花半里雅居
    "843219": "金竹园大厦",  # 金竹园大厦(南座)
    "125655": "桃花园(南山)",  # 桃花园
    "95364": "花果山小区",  # 花果山小区(南山)
    "95401": "学府花园",  # 学府花园(南山)
    "843665": "南景苑",  # 南景苑大厦
    "1427827": "天鹅堡三期",  # 新天鹅堡(三期)
    # Flower city -> Shekou prefix
    "115083": "蛇口花园城一期",
    "234895": "蛇口花园城三期",
    "309199": "蛇口花园城五期",
    # 1:N ambiguous but gov only has one base entry
    "842394": "仓前锦福苑",  # 仓前锦福苑(北区) -> single gov entry
    "174353": "仓前锦福苑",  # 仓前锦福苑(南区) -> same
    "95434": "荔苑小区",  # 荔苑小区(北区) -> single gov entry
    "843393": "荔苑小区",  # 荔苑小区(南区) -> same
    "95336": "桃源村",  # 桃源村(一期) -> single gov entry 桃源村
    "95480": "桃源村",  # 桃源村(二期) -> same
    "189243": "爱榕园一二期",  # 爱榕园
    "925670": "康乐村",  # 康乐村小区
    # Ambiguous 商务公寓/商品住房 -> pick 商品住房
    "1025564": "万科蛇口公馆（商品住房）",
    "1070975": "京基御景峯（商品住房）",
    "1034006": "华润城润府二期（商品住房）",
    "125039": "南光城市花园（商品住房）",
    "370479": "向南瑞峰花园（商品住房）",
    "842298": "宝能城花园（东区）",  # 宝能城花园(东区) -> exact with full-width
    "370839": "湾厦泰福苑",  # 泰福苑
    "792428": "城脉深圳湾公馆",  # 深圳湾公馆
    "843736": "麒麟花园A区",  # 麒麟花园 -> pick A区
    # 宝能太古城 -> 太古城花园
    "331953": "太古城花园北区",
    "331950": "太古城花园南区",
    # 卓越维港 -> 卓越维港名苑
    "331961": "卓越维港名苑北区",
    "1035458": "卓越维港名苑南区",
    # 城市山林 -> 华联城市山林花园
    "95461": "华联城市山林花园一期",
    # 蔚蓝海岸 -> 蔚蓝海岸社区
    "115341": "蔚蓝海岸社区首期",
    "115348": "蔚蓝海岸社区三期",
    "115345": "蔚蓝海岸社区二期",
    "115350": "蔚蓝海岸社区四期",
    # 锦绣花园(南山) -> 华侨城锦绣花园
    "95678": "华侨城锦绣花园一期",
    "637195": "华侨城锦绣花园四期",
    # 南油生活区 -> 南油生活
    "942511": "南油生活A区",
    # 阳光粤海花园 -> pick 商品住房
    "844484": "阳光粤海花园一二期(商品住房)",
    # 半山海景兰溪谷(二期) -> 半山海景·兰溪谷二期
    "402708": "半山海景·兰溪谷二期",
    # 半山语林花园 -> 半山语林公寓
    "402568": "半山语林公寓",
    # 半岛城邦 -> 半岛城邦花园
    "97662": "半岛城邦花园一期",
    "315199": "半岛城邦花园二期",
    # 深圳湾一号 -> 深圳湾1号广场
    "370715": "深圳湾1号广场",
    # 水湾1979 -> 水湾壹玖柒玖广场
    # hard to pick which one, skip
    # 东方花园 -> 东方花园W区 (only one in gov)
    "147099": "东方花园W区",
    # 英达钰龙园 -> 英达·钰龙园
    "95343": "英达·钰龙园",
    # 玫瑰园 -> 玫瑰园小区
    "843582": "玫瑰园小区",
    # 宝能城花园(西区) -> 宝能城-西区
    "1279063": "宝能城-西区",
    # 科技园五十八区 -> 科技园58区
    "864187": "科技园58区",
    # 米兰第2季 -> 米兰第二季公寓
    "95584": "米兰第二季公寓",
    # 万科蛇口公馆(商住楼) -> 万科蛇口公馆（商务公寓）
    "1429052": "万科蛇口公馆（商务公寓）",
    # 新天鹅堡(一二期) -> 天鹅堡一期
    "910652": "天鹅堡一期",
    # 京基东堤园 -> 御景东方东堤园
    "97625": "御景东方东堤园",
    # 京基御景东方 -> 御景东方花园
    "95774": "御景东方花园",
    # 京武浪琴半岛 -> 浪琴半岛花园
    "97245": "浪琴半岛花园",
    # 田厦翡翠明珠花园 -> 翡翠明珠花园（商品住房）
    "339270": "翡翠明珠花园（商品住房）",
    # 阳光带海滨城 -> 阳光海滨花园 (best guess)
    # skip - not confident
    # 梦想家园 -> 现代城梦想家园
    "95366": "现代城梦想家园",
    # 南头海关宿舍楼 -> 南头海关宿舍区
    "924032": "南头海关宿舍区",
    # 招商桃花园 -> pick 一期
    "115354": "招商桃花园一期",
    # 天源大厦(南山) -> 南山天源大厦
    "122161": "南山天源大厦",
    # 海景花园(南山) -> 海景花园（商品住房）
    "95698": "海景花园（商品住房）",
    # 海欣花园(南山) -> 蛇口海欣花园
    "119638": "蛇口海欣花园",
    # 雷圳碧榕湾 -> 雷圳碧榕湾名苑 (pick first)
    "95630": "雷圳碧榕湾名苑",
    # 城市山谷(公寓住宅) -> 城市山谷花园
    "464752": "城市山谷花园",
    # 双玺花园 -> 海上世界双玺花园一期
    "616637": "海上世界双玺花园一期",
    # 蛇口碧涛苑 -> 碧涛苑多层
    "843908": "碧涛苑多层",
    # 博林天瑞 -> 博林天瑞花园一期
    "635418": "博林天瑞花园一期",
    # 三湘海尚 -> 三湘海尚花园一期
    "204690": "三湘海尚花园一期",
    # 东帝海景花园 -> 东帝海景家园
    "98200": "东帝海景家园",
    # 卓越浅水湾 -> 浅水湾花园
    "95775": "浅水湾花园",
    # 中信红树湾(北区/南区) -> 中信红树湾花城
    "97334": "中信红树湾花城",
    "323640": "中信红树湾花城",
    # 招商雍景湾 -> 雍景湾花园
    "370501": "雍景湾花园",
    # 深圳湾花园 -> check... no good match. skip
    # 桂园 -> 桂园小区一区
    "95414": "桂园小区一区",
    # 祥祺花园 -> 祥祺苑
    "125852": "祥祺苑",
    # 帝景园 -> 帝景园一期
    "95522": "帝景园一期",
    # 御海新苑 -> 御海新苑一期
    "95563": "御海新苑一期",
    # 十五峯花园 -> 十五峯花园一期
    "224857": "十五峯花园一期",
    # 阳光棕榈园 -> 阳光棕榈园一期
    "98032": "阳光棕榈园一期",
    # 海印长城 -> 海印长城小区一期
    "97227": "海印长城小区一期",
    # 榆园 -> 榆园一期
    "95734": "榆园一期",
    # 鸿瑞花园 -> 鸿瑞花园一期
    "95352": "鸿瑞花园一期",
    # 育德佳园 -> 育德佳园一期
    "181275": "育德佳园一期",
    # 山语海 -> 山语海苑一期
    "1021258": "山语海苑一期",
    # 金竹园 -> 金竹园小区
    "324773": "金竹园小区",
    # 名仕春天 -> 招商名仕花园 (close enough?)
    # skip - not confident
    # 栖游记 -> 栖游家园
    "529860": "栖游家园",
    # 波托菲诺天鹅堡 -> 天鹅堡二期
    "97413": "天鹅堡二期",
    # 波托菲诺香山里 -> 香山里花园一期
    "288315": "香山里花园一期",
    # 松坪村(二期) -> 松坪村梅苑 or similar... not confident. skip
    # 佳兆业前海广场 -> no match
    # 桑泰丹华府(二期) -> 桑泰丹华园二期
    "1050055": "桑泰丹华园二期",
    # 桑泰水木丹华 -> 水木丹华园
    "516153": "水木丹华园",
}


def clean_anjuke_name(raw: str) -> str:
    """Extract clean community name from Anjuke's junk-filled name field."""
    m = re.match(r"^(.+?)(?:\d{4}年|数据由)", raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


def load_gov_data() -> list[dict]:
    """Load government reference price data for Nanshan."""
    with open(DATA_DIR / "xiaoqu_geocoded.csv", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["district"] == "南山区"]


def load_anjuke_details() -> list[dict]:
    """Load Anjuke community details with cleaned names."""
    with open(SCRAPER_DIR / "nanshan_details.json", encoding="utf-8") as f:
        details = json.load(f)
    for d in details:
        d["name"] = clean_anjuke_name(d["name"])
    return details


def build_gov_index(gov_records: list[dict]) -> dict[str, dict]:
    """Build name -> record index. Only keeps unique names (no duplicates)."""
    by_name: dict[str, list[dict]] = {}
    for g in gov_records:
        by_name.setdefault(g["name"], []).append(g)
    return {name: recs[0] for name, recs in by_name.items() if len(recs) == 1}


def load_rentals() -> dict[str, list[dict]]:
    """Load rental listings grouped by community_id."""
    with open(SCRAPER_DIR / "nanshan_rentals.json", encoding="utf-8") as f:
        rentals = json.load(f)

    by_community: dict[str, list[dict]] = {}
    for r in rentals:
        # Parse area
        area = None
        area_str = r.get("面积", "")
        m = re.search(r"([\d.]+)", area_str)
        if m:
            area = float(m.group(1))

        # Parse rooms from 户型 (e.g. "3室2厅1卫")
        rooms = None
        layout = r.get("户型", "")
        m = re.match(r"(\d+)室", layout)
        if m:
            rooms = int(m.group(1))

        listing = {
            "price": r["price"],
            "layout": layout,
            "rooms": rooms,
            "area": area,
            "floor": r.get("楼层", ""),
            "decoration": r.get("装修", ""),
        }
        # Price per sqm
        if r["price"] and area:
            listing["price_sqm"] = round(r["price"] / area, 1)

        by_community.setdefault(r["community_id"], []).append(listing)

    return by_community


def main() -> None:
    gov = load_gov_data()
    anjuke = load_anjuke_details()
    gov_index = build_gov_index(gov)
    rentals = load_rentals()

    # Validate manual mappings point to real gov names
    gov_name_set = set(r["name"] for r in gov)
    bad_mappings = {k: v for k, v in MANUAL_MAP.items() if v not in gov_name_set}
    if bad_mappings:
        print("ERROR: Manual mappings point to non-existent gov names:")
        for k, v in bad_mappings.items():
            print(f"  {k} -> {v}")
        return

    matched_count = 0
    unmatched_names = []
    with_rentals = 0
    merged = []

    for a in anjuke:
        gov_rec = None

        # Try exact match first
        if a["name"] in gov_index:
            gov_rec = gov_index[a["name"]]

        # Then try manual mapping
        if not gov_rec and a["id"] in MANUAL_MAP:
            mapped_name = MANUAL_MAP[a["id"]]
            if mapped_name in gov_index:
                gov_rec = gov_index[mapped_name]

        entry = {
            "anjuke_id": a["id"],
            "name": gov_rec["name"] if gov_rec else a["name"],
            "matched": gov_rec is not None,
        }

        if gov_rec:
            matched_count += 1
            entry["street"] = gov_rec["street"]
            entry["address"] = gov_rec["address"]
            entry["lat"] = float(gov_rec["lat"])
            entry["lng"] = float(gov_rec["lng"])
            for field in ("multi_rent", "high_rent", "low_rent"):
                val = gov_rec[field]
                entry[field] = float(val) if val else None
        else:
            unmatched_names.append(a["name"])

        # Anjuke details
        for field in ("竣工时间", "总户数", "建筑类型", "所属商圈", "物业费", "绿化率", "容积率"):
            entry[field] = a.get(field)

        # Rental listings
        community_rentals = rentals.get(a["id"], [])
        if community_rentals:
            with_rentals += 1
            entry["rentals"] = community_rentals

        merged.append(entry)

    out_path = OUTPUT_DIR / "communities.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Gov Nanshan entries: {len(gov)}")
    print(f"Anjuke entries: {len(anjuke)}")
    print(f"Matched: {matched_count}/{len(anjuke)} ({matched_count*100//len(anjuke)}%)")
    print(f"With rentals: {with_rentals}")
    print(f"Unmatched: {len(unmatched_names)}")
    print()
    if unmatched_names:
        print("Unmatched Anjuke names:")
        for n in sorted(unmatched_names):
            print(f"  {n}")

    print(f"\nWrote {len(merged)} entries to {out_path}")


if __name__ == "__main__":
    main()
