# 深圳南山租金地图

Make Shenzhen Nanshan's rental market transparent — government reference prices + real listings on one map.

## Why

- Rental prices in China are opaque; agencies (贝壳/链家) control the information
- Government reference prices exist but are buried in spreadsheets nobody reads
- This app puts both on a map so renters can compare what the government says vs what landlords actually charge

## Features

- **Interactive map** — 838 communities and urban villages (城中村) with color-coded government reference prices
- **Community detail page** — tap any dot to see:
  - Jitter strip of rental listings by room type, with filter chips
  - Area vs unit price scatter plot with P25–P75 band
  - Government reference vs market price dumbbell chart
  - Neighbor comparison (7 nearest communities ranked by median price)
  - Community description (小区解读) when available
- **Search** — find any community by name
- **4 color themes** — mono, porcelain, palm, wire (change `THEME_NAME` in `App.jsx` and `xiaoqu-detail.html`)

## Data

| Source | File | Description |
|---|---|---|
| 深圳住建局 | `data/xiaoqu_geocoded.csv` | Government rental reference prices with coordinates (789 Nanshan entries) |
| 深圳住建局 | `data/chengzhongcun_geocoded.csv` | Urban village reference prices |
| 安居客 | `scraper/output/nanshan_rentals.json` | 11,000+ actual rental listings |
| 安居客 | `scraper/output/nanshan_communities.json` | Community metadata (475 communities) |
| 安居客 | `scraper/output/nanshan_details.json` | Community descriptions (小区解读) |
| 乐有家 | `scraper/output/leyoujia_nanshan_rentals.json` | 8,000+ Nanshan rental listings with daily diff tracking |
| 乐有家 | `scraper/output/leyoujia_nanshan_communities.json` | 900+ communities with listing counts |

## Project Structure

```
data/               Government CSV data (geocoded)
scraper/            Scrapers (Python, requests + BeautifulSoup)
  leyoujia_scraper.py    乐有家 scraper — concurrent workers, daily diff detection
  export_cookies.py      Cookie export helper (Anjuke + Leyoujia)
  run_daily.sh           Cron wrapper for daily scraping
scripts/            Data processing (match_communities.py merges gov + Anjuke data)
app/                Vite + React frontend
  src/App.jsx       Map view with theme system
  public/           Static assets + merged JSON data
.claude/skills/     Claude Code skills
  recommend.md      AI apartment recommendation skill
```

## Run locally

```bash
cd app
npm install
npm run dev
```

Open `http://localhost:5173`. Tap a community dot → detail page.

To share on your local network (e.g. test on phone):

```bash
npm run dev -- --host
```

## Scraper

### Setup (one-time)

1. Login to `shenzhen.leyoujia.com` in Chrome
2. Open DevTools → Network tab → copy the `Cookie` header value from any request
3. Export cookies:
   ```bash
   cd scraper
   uv run python export_cookies.py --leyoujia
   ```
   Paste the cookie string when prompted.

### Run manually

```bash
cd scraper
uv run python leyoujia_scraper.py --workers 5
```

Scrapes all 21 Nanshan sub-areas with 5 concurrent workers (~8 min). Compares against previous data and reports new/removed listings. Each listing gets a `scraped_at` date for tracking when it first appeared.

### Daily cron

```bash
# Install (runs at 2:00 CEST / 8:00 CST daily)
echo "0 2 * * * /path/to/scraper/run_daily.sh" | crontab -
```

Logs are saved to `scraper/logs/YYYY-MM-DD.log`.

## AI Recommendations

Use the Claude Code skill to get personalized apartment recommendations:

```
/recommend
```

Filters the scraped data by your preferences (location, price, rooms, area, year, orientation, floor) and highlights today's new listings with match/mismatch analysis.

## Update map data

1. Run the Anjuke scraper:
   ```bash
   cd scraper
   uv run python main.py
   ```

2. Merge scraper output with government data:
   ```bash
   python3 scripts/match_communities.py
   ```
   This writes `app/public/communities.json`. The dev server picks it up live — no restart needed.

## Themes

Change `THEME_NAME` in both `app/src/App.jsx` and `app/public/xiaoqu-detail.html`:

| Theme | Look |
|---|---|
| `mono` | Paper/charcoal grayscale |
| `porcelain` | Blue tones on warm cream |
| `palm` | Olive green with amber accent |
| `wire` | Grayscale + orange (#F5572F) accent |

## Status

MVP — Nanshan district only. Validating market demand before expanding to other districts.
