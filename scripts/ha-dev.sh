#!/usr/bin/env bash
# Throwaway Home Assistant with this integration loaded from the working tree.
# Usage: scripts/ha-dev.sh setup|start|stop|status|logs
set -euo pipefail

HA_VERSION="2026.10.4" # keep equal to the live instance (docs/interfaces.md)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.ha-venv"
CONFIG="$ROOT/config"
PIDFILE="$CONFIG/ha.pid"
LOGFILE="$CONFIG/home-assistant.log"

setup() {
  if [ ! -x "$VENV/bin/hass" ]; then
    python3.14 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet "homeassistant==$HA_VERSION" "pyshp>=2.3"
  fi
  mkdir -p "$CONFIG/custom_components"
  # A symlink, so edits in the working tree are what HA loads.
  ln -sfn "$ROOT/custom_components/bom_warnings" "$CONFIG/custom_components/bom_warnings"
  if [ ! -f "$CONFIG/configuration.yaml" ]; then
    cat >"$CONFIG/configuration.yaml" <<'YAML'
default_config:

http:
  server_host: 127.0.0.1
  server_port: 8124

logger:
  default: warning
  logs:
    custom_components.bom_warnings: debug
YAML
  fi
}

is_running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "${1:-}" in
setup) setup ;;
start)
  setup
  if is_running; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
  nohup "$VENV/bin/hass" -c "$CONFIG" >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
  echo "started pid $(cat "$PIDFILE"); UI at http://127.0.0.1:8124 (first boot takes a few minutes)"
  ;;
stop)
  if is_running; then
    kill "$(cat "$PIDFILE")"
    while kill -0 "$(cat "$PIDFILE")" 2>/dev/null; do sleep 1; done
    echo stopped
  else
    echo "not running"
  fi
  rm -f "$PIDFILE"
  ;;
status) if is_running; then echo "running (pid $(cat "$PIDFILE"))"; else echo "not running"; fi ;;
logs) tail -f "$LOGFILE" ;;
*) echo "usage: $0 setup|start|stop|status|logs" >&2; exit 2 ;;
esac
