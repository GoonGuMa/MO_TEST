#!/usr/bin/env bash
set -euo pipefail

pid_file="/tmp/mo-test-uvicorn-8080.pid"
log_file="/tmp/mo-test-uvicorn-8080.log"

if [[ -f "$pid_file" ]]; then
  server_pid="$(<"$pid_file")"
  for _ in {1..20}; do
    if ! kill -0 "$server_pid" 2>/dev/null; then
      break
    fi
    if curl --silent --fail http://127.0.0.1:8080/api/health >/dev/null; then
      echo "MO_TEST is already running at http://localhost:8080"
      exit 0
    fi
    sleep 0.25
  done
  if kill -0 "$server_pid" 2>/dev/null; then
    echo "MO_TEST process is running but the health check failed."
    echo "Server log: $log_file"
    exit 1
  fi
fi

nohup .venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8080 >"$log_file" 2>&1 &
echo "$!" >"$pid_file"

for _ in {1..40}; do
  if curl --silent --fail http://127.0.0.1:8080/api/health >/dev/null; then
    echo "MO_TEST started at http://localhost:8080"
    echo "Server log: $log_file"
    exit 0
  fi
  if ! kill -0 "$(<"$pid_file")" 2>/dev/null; then
    break
  fi
  sleep 0.25
done

echo "MO_TEST failed to start."
echo "Server log: $log_file"
exit 1
