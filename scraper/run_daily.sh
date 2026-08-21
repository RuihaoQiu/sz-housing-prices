#!/usr/bin/env bash
# Daily leyoujia scraper — run via cron
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

cd "$SCRIPT_DIR"
echo "=== $(date) ===" >> "$LOG_FILE"
/Users/ruihaoqiu/.local/bin/uv run python leyoujia_scraper.py --workers 5 >> "$LOG_FILE" 2>&1
echo "=== Done $(date) ===" >> "$LOG_FILE"
