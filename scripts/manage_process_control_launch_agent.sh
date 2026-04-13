#!/bin/zsh
set -euo pipefail

LABEL="com.plo.remotebot.processcontrol"
PLIST="/Users/plo/Documents/remoteBot/launchd/com.plo.remotebot.processcontrol.plist"
TARGET="gui/$(id -u)/${LABEL}"

cmd="${1:-status}"

case "$cmd" in
  status)
    if launchctl print "$TARGET" >/tmp/remotebot_processcontrol_status.txt 2>/dev/null; then
      sed -n '1,40p' /tmp/remotebot_processcontrol_status.txt
    else
      echo "process control launch agent is not loaded"
    fi
    ;;
  reload)
    mkdir -p /Users/plo/Documents/remoteBot/logs
    launchctl bootout "$TARGET" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    launchctl kickstart -k "$TARGET"
    launchctl print "$TARGET" | sed -n '1,40p'
    ;;
  stop)
    launchctl bootout "$TARGET"
    echo "process control launch agent stopped"
    ;;
  *)
    echo "usage: $0 {status|reload|stop}" >&2
    exit 1
    ;;
esac
