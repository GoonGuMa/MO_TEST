#!/usr/bin/env bash
set -euo pipefail

pid_file="/tmp/mo-test-uvicorn.pid"
log_file="/tmp/mo-test-uvicorn.log"

if [[ -f "$pid_file" ]]; then
  server_pid="$(<"$pid_file")"
  if kill -0 "$server_pid" 2>/dev/null; then
    echo "MO_TEST is already running at http://localhost:8000"
    exit 0
  fi
fi

nohup .venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 >"$log_file" 2>&1 &
echo "$!" >"$pid_file"
echo "MO_TEST started at http://localhost:8000"
echo "Server log: $log_file"
