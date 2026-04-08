#!/bin/zsh
set -euo pipefail

ROOT_DIR="/Users/plo/Documents/remoteBot"

cd "$ROOT_DIR"
/opt/homebrew/bin/python3 "$ROOT_DIR/scripts/process_control_server.py" --ensure-running >/dev/null
if /bin/zsh "$ROOT_DIR/scripts/build_process_control_widget.sh" >/tmp/remotebot_widget_build_path.txt 2>/tmp/remotebot_widget_build_err.txt; then
  APP_PATH="$(cat /tmp/remotebot_widget_build_path.txt)"
  open "$APP_PATH"
else
  /usr/bin/osascript "$ROOT_DIR/scripts/process_control_widget.applescript"
fi
