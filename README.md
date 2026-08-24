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

**36,000+ rental listings** across 1,609 communities from three sources:

| Source | Records | Description |
|---|---|---|
| 深圳住建局 (Government) | 789 communities | Official rental reference prices with geocoded coordinates |
| 安居客 (Anjuke) | 23,106 listings | Active + removed rental listings across 896 communities |
| 乐有家 (Leyoujia) | 12,197 listings | Active + removed rental listings across 1,044 communities |

### Data architecture

```
data/
  xiaoqu_geocoded.csv           Government reference prices (source of truth for coordinates, GCJ-02)
  chengzhongcun_geocoded.csv    Urban village reference prices
  manual_map.json               Human-curated anjuke_id → gov_name mappings (211 entries)
  base/                         Normalized base layer (gitignored, rebuild with scripts)
    gov.json                    Government records for Nanshan
    communities.json            Unified community registry (1,609 entries)
    anjuke_rentals.json         Normalized anjuke listings
    leyoujia_rentals.json       Normalized leyoujia listings

app/public/
  data.json                     Map dots — 838 entries, GCJ-02 coordinates (do not regenerate)
  communities.json              Community index with inline rentals (5 MB, serves the detail page)
  details.json                  Anjuke community descriptions (小区解读)
```

The base layer (`data/base/`) is the single source of truth for all downstream data. The app layer (`app/public/`) contains frontend-optimized views built from the base layer. Both are produced by build scripts — the base layer is gitignored, while app files are tracked for GitHub Pages compatibility.

## Project structure

```
data/               Government CSVs + manual mappings
scripts/
  build_base.py     Raw sources → normalized base layer (data/base/)
  build_app.py      Base layer → frontend JSON (app/public/)
  match_communities.py  Community matching utilities
scraper/
  anjuke_scraper.py       安居客 scraper
  leyoujia_scraper.py     乐有家 scraper — concurrent workers, daily diff detection
  export_cookies.py       Cookie export helper
  run_daily.sh            Cron wrapper for daily scraping
app/                Vite + React frontend
  src/App.jsx       Map view with theme system
  public/           Static assets + built JSON data
```

## Run locally

```bash
cd app && npm install && npm run dev
```

Open `http://localhost:5173`. Tap a community dot → detail page.

## Rebuild data

After scraping new listings or updating manual mappings:

```bash
python3 scripts/build_base.py
```

```bash
python3 scripts/build_app.py
```

The first script produces the base layer from raw sources. The second reads the base layer and writes the app JSON files. The dev server picks up changes live.

## Scraper

### Setup (one-time)

1. Login to the target site in Chrome
2. Export cookies:
   ```bash
   cd scraper
   uv run python export_cookies.py --leyoujia
   ```

### Run

```bash
cd scraper
uv run python leyoujia_scraper.py --workers 5
```

### Daily cron

```bash
echo "0 2 * * * /path/to/scraper/run_daily.sh" | crontab -
```

Logs are saved to `scraper/logs/YYYY-MM-DD.log`.

## AI recommendations

Use the Claude Code skill to get personalized apartment recommendations:

```
/recommend
```

Filters the scraped data by your preferences (location, price, rooms, area, year, orientation, floor) and highlights today's new listings.

## Themes

Change `THEME_NAME` in both `app/src/App.jsx` and `app/public/xiaoqu-detail.html`:

| Theme | Look |
|---|---|
| `mono` | Paper/charcoal grayscale |
| `porcelain` | Blue tones on warm cream |
| `palm` | Olive green with amber accent |
| `wire` | Grayscale + orange accent |

## Deploy

Pushes to `main` auto-deploy to GitHub Pages via `.github/workflows/deploy.yml`. The workflow runs `npm run build` and deploys `app/dist/`.

## Status

MVP — Nanshan district only.
