#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
LOG_DIR="$REPO_ROOT/logs"
PID_FILE="$REPO_ROOT/wms.pid"
PORT_FILE="$REPO_ROOT/wms.port"

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
  wms.sh restart [port]
  wms.sh status

Examples:
  wms.sh start
  wms.sh start 8080
  wms.sh stop
  wms.sh restart
  wms.sh restart 8080
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

current_port() {
    local port=""

    if [[ -f "$PORT_FILE" ]]; then
        port="$(<"$PORT_FILE")"
        if [[ "$port" =~ ^[0-9]+$ ]]; then
            printf '%s\n' "$port"
            return 0
        fi
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
    printf '%s\n' "$port" > "$PORT_FILE"
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
    rm -f "$PORT_FILE"
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

restart_server() {
    local port

    port="${1:-}"
    if [[ -z "$port" ]]; then
        port="$(current_port)"
        if [[ -z "$port" ]]; then
            port="8000"
        fi
    fi

    stop_server
    sleep 1
    start_server "$port"
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
    restart)
        restart_server "${2:-}"
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