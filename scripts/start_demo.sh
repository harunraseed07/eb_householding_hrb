#!/usr/bin/env bash
# Build the data and open the app in one command.
#
#   ./scripts/start_demo.sh            use the data that is already there
#   ./scripts/start_demo.sh --reset    rebuild from the seed first
#
# Use --reset between dry runs so the steward queue starts clean.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--reset" || ! -d data ]]; then
  echo "Building demo data..."
  python3 scripts/run_pipeline.py --reset
fi

echo
echo "Opening the app. Press Ctrl+C to stop."
exec streamlit run app/app.py
