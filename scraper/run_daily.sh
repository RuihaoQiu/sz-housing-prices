#!/usr/bin/env bash
# Daily scrapers — run via cron
export PATH="/Users/ruihaoqiu/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

cd "$SCRIPT_DIR"

# Leyoujia
echo "=== Leyoujia $(date) ===" >> "$LOG_FILE"
uv run python leyoujia_scraper.py --workers 5 >> "$LOG_FILE" 2>&1
echo "=== Leyoujia Done $(date) ===" >> "$LOG_FILE"

# Anjuke
echo "=== Anjuke $(date) ===" >> "$LOG_FILE"
uv run python anjuke_scraper.py --rentals-only --workers 5 >> "$LOG_FILE" 2>&1
echo "=== Anjuke Done $(date) ===" >> "$LOG_FILE"
