#!/usr/bin/env bash
# ======================================================
# Build the Vue frontend and sync dist/ into this repo,
# then rebuild the frontend Docker container.
#
# Default convention: clone QuantDinger-Vue into the project root as
# `quantdinger_vue/` (already gitignored). Override with QUANTDINGER_VUE_SRC.
#
# Usage:
#   ./scripts/sync-frontend-dist.sh             # uses ./quantdinger_vue
#   QUANTDINGER_VUE_SRC=/path/to/repo ./scripts/sync-frontend-dist.sh
#   ./scripts/sync-frontend-dist.sh --no-docker # skip docker rebuild
#   ./scripts/sync-frontend-dist.sh --no-build  # assume dist/ already built
# ======================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST="$ROOT/frontend/dist"
SRC="${QUANTDINGER_VUE_SRC:-$ROOT/quantdinger_vue}"

DO_BUILD=1
DO_DOCKER=1
for arg in "$@"; do
  case "$arg" in
    --no-build)  DO_BUILD=0 ;;
    --no-docker) DO_DOCKER=0 ;;
    -h|--help)
      sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $arg"; exit 2 ;;
  esac
done

if [[ ! -d "$SRC" ]]; then
  echo "ERROR: Vue source not found at: $SRC"
  echo "  - Clone it:  git clone https://github.com/brokermr810/QuantDinger-Vue.git quantdinger_vue"
  echo "  - Or set:    export QUANTDINGER_VUE_SRC=/path/to/QuantDinger-Vue"
  exit 1
fi
SRC="$(cd "$SRC" && pwd)"

echo "Vue source : $SRC"
echo "Dist target: $DEST"

if [[ "$DO_BUILD" == "1" ]]; then
  echo "[1/3] Installing dependencies (npm install)..."
  ( cd "$SRC" && npm install --legacy-peer-deps )

  echo "[2/3] Building production bundle (npm run build)..."
  ( cd "$SRC" && npm run build )
else
  echo "[1-2/3] Skipping npm install + build (--no-build)"
fi

if [[ ! -d "$SRC/dist" ]]; then
  echo "ERROR: $SRC/dist not found - build did not produce a dist/ directory"
  exit 1
fi

echo "[3/3] Syncing $SRC/dist -> $DEST"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$SRC/dist/." "$DEST/"

FILE_COUNT=$(find "$DEST" -type f | wc -l | tr -d ' ')
DIST_SIZE=$(du -sh "$DEST" | cut -f1)
echo "  -> $FILE_COUNT files, $DIST_SIZE"

if [[ "$DO_DOCKER" == "1" ]]; then
  if ! command -v docker >/dev/null; then
    echo "WARN: docker not in PATH - skipping container rebuild"
  else
    echo "[docker] Rebuilding frontend container..."
    ( cd "$ROOT" && docker compose up -d --build frontend )
    echo "Done. Open http://localhost:8888"
  fi
else
  echo "Skipped docker rebuild (--no-docker). Run manually:"
  echo "  docker compose up -d --build frontend"
fi
