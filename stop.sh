#!/bin/zsh
set -euo pipefail

DOMAIN="gui/$(id -u)"
for label in com.local-meeting-assistant.web com.admin.local-meeting-assistant.web com.admin.local-meeting-assistant.mlx; do
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
done

echo "Local meeting assistant services stopped."
