#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/agentmesh-demo"
RUN_DIR="$ROOT_DIR/.dev/run"
LOG_DIR="$ROOT_DIR/.dev/logs"

BACKEND_HOST="${AGENTMESH_BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${AGENTMESH_FRONTEND_HOST:-127.0.0.1}"
BACKEND_PORT="${AGENTMESH_BACKEND_PORT:-8010}"
FRONTEND_PORT="${AGENTMESH_FRONTEND_PORT:-5178}"

UVICORN_CMD=($ROOT_DIR/.venv/bin/python -m uvicorn)
VITE_BIN="$FRONTEND_DIR/node_modules/.bin/vite"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

usage() {
  cat <<EOF
Usage: ./scripts/dev.sh <command>

Commands:
  status   Show backend/frontend dev-server status
  start    Start backend on :$BACKEND_PORT and frontend on :$FRONTEND_PORT
  stop     Stop processes listening on :$BACKEND_PORT and :$FRONTEND_PORT
  restart  Stop, then start both servers
  logs     Print recent backend/frontend logs

Environment overrides:
  AGENTMESH_BACKEND_PORT=$BACKEND_PORT
  AGENTMESH_FRONTEND_PORT=$FRONTEND_PORT
  AGENTMESH_BACKEND_HOST=$BACKEND_HOST
  AGENTMESH_FRONTEND_HOST=$FRONTEND_HOST
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

ensure_runtime_tools() {
  command -v lsof >/dev/null 2>&1 || die "lsof is required"
  command -v curl >/dev/null 2>&1 || die "curl is required"
}

ensure_start_prereqs() {
  ensure_runtime_tools
  [[ -x "$ROOT_DIR/.venv/bin/python" ]] || die "missing $ROOT_DIR/.venv/bin/python; run: /opt/homebrew/bin/python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'"
  [[ -x "$VITE_BIN" ]] || die "missing $VITE_BIN; run: npm --prefix agentmesh-demo install"
}

port_pids() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
}

has_port_listener() {
  local port="$1"
  [[ -n "$(port_pids "$port" || true)" ]]
}

format_pids() {
  tr '\n' ' ' | sed 's/[[:space:]]*$//'
}

wait_for_url() {
  local name="$1"
  local url="$2"

  for _ in {1..80}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name ready: $url"
      return 0
    fi
    sleep 0.25
  done

  echo "$name did not become ready: $url" >&2
  return 1
}

managed_pid() {
  local pid_file="$1"
  local marker="${2:-}"
  [[ -f "$pid_file" ]] || return 0
  local pid command
  pid="$(sed -n '1p' "$pid_file" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ -z "$marker" || "$command" == *"$marker"* ]]; then
      printf '%s\n' "$pid"
    fi
  fi
}

start_backend() {
  local pids managed
  pids="$(port_pids "$BACKEND_PORT" || true)"
  managed="$(managed_pid "$BACKEND_PID_FILE" "agentmesh.app:app")"
  if [[ -n "$pids" ]]; then
    [[ -n "$managed" ]] || die "backend port :$BACKEND_PORT is occupied by an unmanaged process; inspect with: lsof -nP -iTCP:$BACKEND_PORT -sTCP:LISTEN"
    echo "backend already listening on http://$BACKEND_HOST:$BACKEND_PORT (managed pid: $managed)"
    return 0
  fi

  mkdir -p "$RUN_DIR" "$LOG_DIR"
  (
    cd "$ROOT_DIR"
    nohup "${UVICORN_CMD[@]}" agentmesh.app:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
    echo "$!" >"$BACKEND_PID_FILE"
  )

  wait_for_url "backend" "http://$BACKEND_HOST:$BACKEND_PORT/api/health" || {
    tail -n 80 "$BACKEND_LOG" >&2 || true
    return 1
  }
}

start_frontend() {
  local pids managed
  pids="$(port_pids "$FRONTEND_PORT" || true)"
  managed="$(managed_pid "$FRONTEND_PID_FILE" "vite")"
  if [[ -n "$pids" ]]; then
    [[ -n "$managed" ]] || die "frontend port :$FRONTEND_PORT is occupied by an unmanaged process; inspect with: lsof -nP -iTCP:$FRONTEND_PORT -sTCP:LISTEN"
    echo "frontend already listening on http://$FRONTEND_HOST:$FRONTEND_PORT (managed pid: $managed)"
    return 0
  fi

  mkdir -p "$RUN_DIR" "$LOG_DIR"
  (
    cd "$FRONTEND_DIR"
    nohup "$VITE_BIN" --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort >"$FRONTEND_LOG" 2>&1 &
    echo "$!" >"$FRONTEND_PID_FILE"
  )

  wait_for_url "frontend" "http://$FRONTEND_HOST:$FRONTEND_PORT/" || {
    tail -n 80 "$FRONTEND_LOG" >&2 || true
    return 1
  }
}

start_all() {
  ensure_start_prereqs
  start_backend
  start_frontend
  echo "dev servers ready"
}

collect_stop_pids() {
  local _port="$1"
  local pid_file="$2"
  local marker="$3"
  managed_pid "$pid_file" "$marker"
}

stop_one() {
  local name="$1"
  local port="$2"
  local pid_file="$3"
  local marker="$4"
  local pids
  pids="$(collect_stop_pids "$port" "$pid_file" "$marker")"

  if [[ -z "$pids" ]]; then
    if has_port_listener "$port"; then
      echo "$name port :$port is owned by an unmanaged process; refusing to terminate it" >&2
      echo "inspect with: lsof -nP -iTCP:$port -sTCP:LISTEN" >&2
      return 1
    fi
    echo "$name stopped (:${port})"
    rm -f "$pid_file"
    return 0
  fi

  echo "stopping $name (:${port}) pid(s): $(printf '%s\n' "$pids" | format_pids)"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done <<<"$pids"

  for _ in {1..40}; do
    if ! has_port_listener "$port"; then
      rm -f "$pid_file"
      echo "$name stopped"
      return 0
    fi
    sleep 0.25
  done

  echo "$name still has a listener on :$port; inspect with: lsof -nP -iTCP:$port -sTCP:LISTEN" >&2
  return 1
}

stop_all() {
  ensure_runtime_tools
  stop_one "frontend" "$FRONTEND_PORT" "$FRONTEND_PID_FILE" "vite"
  stop_one "backend" "$BACKEND_PORT" "$BACKEND_PID_FILE" "agentmesh.app:app"
}

status_one() {
  local name="$1"
  local host="$2"
  local port="$3"
  local pids
  pids="$(port_pids "$port" || true)"

  if [[ -n "$pids" ]]; then
    echo "$name running: http://$host:$port (pid: $(printf '%s\n' "$pids" | format_pids))"
  else
    echo "$name stopped: http://$host:$port"
  fi
}

status_all() {
  ensure_runtime_tools
  status_one "backend" "$BACKEND_HOST" "$BACKEND_PORT"
  if curl -fsS "http://$BACKEND_HOST:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    echo "backend health: ok"
  fi
  status_one "frontend" "$FRONTEND_HOST" "$FRONTEND_PORT"
}

print_logs() {
  for entry in "backend:$BACKEND_LOG" "frontend:$FRONTEND_LOG"; do
    local name="${entry%%:*}"
    local file="${entry#*:}"
    echo "==> $name log: $file"
    if [[ -f "$file" ]]; then
      tail -n 80 "$file"
    else
      echo "no log yet"
    fi
  done
}

case "${1:-}" in
  status)
    status_all
    ;;
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  logs)
    print_logs
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
