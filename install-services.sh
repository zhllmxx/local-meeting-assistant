#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DOMAIN="gui/$(id -u)"
SERVICE_DIRECTORY="$HOME/Library/LaunchAgents"
SERVICE_LABEL="com.local-meeting-assistant.web"
mkdir -p "$SERVICE_DIRECTORY" "$PROJECT_ROOT/var/tmp" "$PROJECT_ROOT/var/runs"

APP_PYTHON="$PROJECT_ROOT/.venv-app/bin/python"
if [[ ! -x "$APP_PYTHON" ]]; then
  PYTHON_EXECUTABLE="${PYTHON_EXECUTABLE:-$(command -v python3.11 || command -v python3)}"
  "$PYTHON_EXECUTABLE" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
  "$PYTHON_EXECUTABLE" -m venv "$PROJECT_ROOT/.venv-app"
fi
"$APP_PYTHON" -m pip install --disable-pip-version-check -r "$PROJECT_ROOT/requirements.txt"

cd "$PROJECT_ROOT"
if [[ ! -d node_modules ]]; then
  npm ci
fi
npm run build:web
"$APP_PYTHON" -c 'import app; app.ensure_screen_audio_capture()'

if [[ ! -f config.local.json ]]; then
  cp config.example.json config.local.json
  chmod 600 config.local.json
fi

SERVICE_PLIST="$SERVICE_DIRECTORY/$SERVICE_LABEL.plist"
"$APP_PYTHON" bin/service_config.py --output "$SERVICE_PLIST"

# Unload this tool's previous service names when upgrading an existing install.
for label in com.admin.local-meeting-assistant.mlx com.admin.local-meeting-assistant.whisper com.admin.local-meeting-assistant.web; do
  launchctl bootout "$SERVICE_DOMAIN/$label" >/dev/null 2>&1 || true
done
launchctl bootout "$SERVICE_DOMAIN/$SERVICE_LABEL" >/dev/null 2>&1 || true
sleep 1
launchctl bootstrap "$SERVICE_DOMAIN" "$SERVICE_PLIST"
