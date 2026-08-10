#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STATUS_PID=""
CHAT_PID=""
PYTHON_BIN=""

wait_for_service() {
  local service_name="$1"
  local service_url="$2"
  "${PYTHON_BIN}" - "${service_name}" "${service_url}" <<'PY'
import sys
import time
import urllib.error
import urllib.request

name, url = sys.argv[1:]
deadline = time.monotonic() + 15
last_error = "service did not respond"
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200:
                raise SystemExit(0)
            last_error = f"HTTP {response.status}"
    except (OSError, urllib.error.URLError) as exc:
        last_error = str(exc)
    time.sleep(0.1)
print(f"LoopX {name} service failed to start: {last_error}", file=sys.stderr)
raise SystemExit(1)
PY
}

cleanup() {
  if [ -n "${STATUS_PID}" ]; then
    kill "${STATUS_PID}" 2>/dev/null || true
  fi
  if [ -n "${CHAT_PID}" ]; then
    kill "${CHAT_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "${candidate}" >/dev/null 2>&1 \
    && "${candidate}" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
    PYTHON_BIN="${candidate}"
    break
  fi
done

if [ -z "${PYTHON_BIN}" ]; then
  echo "LoopX requires Python 3.11 or newer to start status and Chat services." >&2
  echo "Starting the Vite UI only; use the bundled example until Python is upgraded." >&2
  cd "${REPO_ROOT}/apps/presentation/dashboard"
  exec npm run dev:web
fi

cd "${REPO_ROOT}"
"${PYTHON_BIN}" -m loopx.cli serve-status \
  --global-registry \
  --host 127.0.0.1 \
  --port 8766 \
  --limit 80 &
STATUS_PID=$!

"${PYTHON_BIN}" -m loopx.cli chat \
  --global-registry \
  --host 127.0.0.1 \
  --port 8767 \
  --no-open &
CHAT_PID=$!

if ! wait_for_service "status" "http://127.0.0.1:8766/healthz"; then
  exit 1
fi
if ! wait_for_service "Chat" "http://127.0.0.1:8767/api/chat/capabilities"; then
  exit 1
fi

echo "LoopX dashboard services:"
echo "  UI:     http://127.0.0.1:5173/"
echo "  Status: http://127.0.0.1:8766/status.json"
echo "  Chat:   http://127.0.0.1:8767/api/chat/capabilities"

cd "${REPO_ROOT}/apps/presentation/dashboard"
npm run dev:web
