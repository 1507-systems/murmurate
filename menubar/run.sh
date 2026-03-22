#!/usr/bin/env bash
# run.sh — Launch the Murmurate menu bar app.
#
# Usage:
#   ./run.sh                                    # Connect to default (127.0.0.1:7683)
#   MURMURATE_API_HOST=192.168.1.5 ./run.sh    # Connect to remote instance
#   MURMURATE_API_TOKEN=secret ./run.sh        # With auth token
#
# The app runs as a macOS status bar item and polls the Murmurate REST API
# for status updates. It does NOT start or manage the daemon itself — run
# `murmurate start --api` separately.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Ensure rumps is installed
if ! python3 -c "import rumps" 2>/dev/null; then
    echo "Installing rumps..."
    pip3 install rumps
fi

exec python3 "$SCRIPT_DIR/murmurate_menubar.py"
