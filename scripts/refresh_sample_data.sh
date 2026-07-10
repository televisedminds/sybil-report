#!/usr/bin/env bash
# Refresh the bundled sample candles from the Coinbase public API.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m autopilot fetch --symbol BTC-USD --timeframe 1d --start 2016-01-01 \
    --out sample_data/BTC-USD-1d.csv
python3 -m autopilot fetch --symbol ETH-USD --timeframe 1d --start 2017-01-01 \
    --out sample_data/ETH-USD-1d.csv

echo "done — remember to update the table in sample_data/README.md"
