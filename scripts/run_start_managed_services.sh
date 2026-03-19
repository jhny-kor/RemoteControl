#!/bin/zsh
set -euo pipefail

cd /Users/plo/Documents/remoteBot
mkdir -p logs
exec /opt/homebrew/bin/python3 scripts/start_managed_services.py
