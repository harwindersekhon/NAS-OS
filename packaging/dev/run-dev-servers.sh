#!/bin/sh
# Runs the backend (NASOS_MODE=dev) and the Vite dev server together.
# Used by `make dev` and by Playwright (playwright.config.ts webServer) so
# e2e tests exercise the real HTTP/WS stack. Ctrl+C stops both.
set -eu

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO_ROOT"

if [ ! -x backend/.venv/bin/uvicorn ]; then
  echo "run-dev-servers.sh: backend/.venv is missing — run 'make bootstrap' first" >&2
  exit 1
fi

mkdir -p backend/devdata
if [ ! -f backend/devdata/devusers.toml ]; then
  cp packaging/dev/devusers.toml.example backend/devdata/devusers.toml
fi

export NASOS_MODE=dev
export NASOS_DEVDATA_DIR="$REPO_ROOT/backend/devdata"
export NASOS_DEVUSERS_FILE="$REPO_ROOT/backend/devdata/devusers.toml"
export NASOS_DB_PATH="$REPO_ROOT/backend/devdata/nasos.db"
# JobRunner's jsonl log + ManagedFile's config-backups land here instead of
# the real /var/lib/nasos, which the dev user can't write to anyway.
export NASOS_STATE_DIR="$REPO_ROOT/backend/devdata/var/lib/nasos"

trap 'kill 0' EXIT INT TERM

"$REPO_ROOT/backend/.venv/bin/uvicorn" nasos.web.main:create_app --factory \
  --app-dir "$REPO_ROOT/backend" --host 127.0.0.1 --port 5000 --reload &

(cd "$REPO_ROOT/frontend" && npm run dev -- --host 127.0.0.1 --port 5173 --strictPort) &

wait
