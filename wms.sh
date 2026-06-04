#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
LOG_DIR="$REPO_ROOT/logs"
PID_FILE="$REPO_ROOT/wms.pid"

resolve_gunicorn() {
    if [[ -x "$REPO_ROOT/.venv/bin/gunicorn" ]]; then
        printf '%s\n' "$REPO_ROOT/.venv/bin/gunicorn"
        return 0
    fi

    if command -v gunicorn >/dev/null 2>&1; then
        command -v gunicorn
        return 0
    fi

    return 1
}

usage() {
    cat <<'EOF'
Usage:
  wms.sh start [port]
  wms.sh stop
  wms.sh status

Examples:
  wms.sh start
  wms.sh start 8080
  wms.sh stop
  wms.sh status
EOF
}

normalize_start_port() {
    local port="${1:-8000}"

    if [[ ! "$port" =~ ^[0-9]+$ ]]; then
        usage
        exit 1
    fi

    printf '%s\n' "$port"
}

current_pid() {
    local pid=""

    if [[ -f "$PID_FILE" ]]; then
        pid="$(<"$PID_FILE")"
        if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1; then
            printf '%s\n' "$pid"
            return 0
        fi

        rm -f "$PID_FILE"
    fi

    printf '\n'
    return 0
}

start_server() {
    local gunicorn_bin port pid log

    gunicorn_bin="$(resolve_gunicorn)"
    port="$(normalize_start_port "${1:-8000}")"
    mkdir -p "$LOG_DIR"

    pid="$(current_pid)"
    if [[ -n "$pid" ]]; then
        echo "Already running (pid $pid)."
        exit 0
    fi

    log="$LOG_DIR/$(date --iso-8601).log"
    nohup "$gunicorn_bin" --bind "0.0.0.0:$port" --workers=3 --pid "$PID_FILE" wsgi:app &>> "$log" &
    echo "Started on port $port. Log: $log"
}

stop_server() {
    local pid

    pid="$(current_pid)"
    if [[ -z "$pid" ]]; then
        echo "Not running."
        exit 0
    fi

    kill "$pid" >/dev/null 2>&1 || true
    rm -f "$PID_FILE"
    echo "Stopped pid $pid."
}

status_server() {
    local pid

    pid="$(current_pid)"
    if [[ -n "$pid" ]]; then
        echo "Running (pid $pid)."
        return 0
    fi

    echo "Not running."
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage
    exit 1
fi

case "$1" in
    start)
        start_server "${2:-8000}"
        ;;
    stop)
        if [[ $# -ne 1 ]]; then
            usage
            exit 1
        fi
        stop_server
        ;;
    status)
        if [[ $# -ne 1 ]]; then
            usage
            exit 1
        fi
        status_server
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage
        exit 1
        ;;
esac