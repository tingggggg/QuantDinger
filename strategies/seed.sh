#!/usr/bin/env bash
# Load the repo's strategy sources into the running stack so the web UI sees them.
# Run from the repo root:  ./strategies/seed.sh
set -euo pipefail

CONTAINER="${CONTAINER:-quantdinger-backend}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "error: container '$CONTAINER' is not running" >&2
  echo "       start the stack first: docker compose up -d" >&2
  exit 1
fi

# The container has no bind mount to the repo, so copy the two source
# directories in. Paths mirror the repo layout because seed_key is the
# repo-relative path -- keeping it stable is what makes re-runs update in
# place instead of creating duplicates.
docker exec "$CONTAINER" sh -c 'rm -rf /repo && mkdir -p /repo'
docker cp strategies "$CONTAINER":/repo/strategies
docker cp smc "$CONTAINER":/repo/smc
docker cp strategies/seed.py "$CONTAINER":/tmp/seed.py

docker exec -e PYTHONPATH=/app -e SEED_ROOT=/repo "$CONTAINER" python /tmp/seed.py
