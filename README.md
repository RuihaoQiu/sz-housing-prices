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

## Project Structure

```
data/               Government CSV data (geocoded)
scraper/            Anjuke scraper (Python, requests + BeautifulSoup)
scripts/            Data processing (match_communities.py merges gov + Anjuke data)
app/                Vite + React frontend
  src/App.jsx       Map view with theme system
  public/           Static assets + merged JSON data
    xiaoqu-detail.html   Community detail page (standalone, ECharts + hand-drawn SVG)
    communities.json     Merged data: gov prices + Anjuke metadata + rental listings
    data.json            Government reference prices for map dots
    details.json         Community descriptions
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

## Update data

1. Run the scraper to fetch latest listings:
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
