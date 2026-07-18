#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "Missing $ROOT_DIR/.env"
  echo "Create it from .env.example and set TMDB_API_READ_ACCESS_TOKEN first."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for the one-command startup path."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running."
  exit 1
fi

cd "$ROOT_DIR"

# ponytail: keep one startup path; if disk pressure becomes frequent, add a separate clean script instead of forcing global prune here.
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_BAKE=true

docker compose build
docker compose up -d --remove-orphans

echo "Waiting for API health..."
attempt=0
until curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    echo "API did not become healthy. Check: docker compose logs api"
    exit 1
  fi
  sleep 2
done

echo "Checking TMDB access..."
if ! docker compose exec -T api python - <<'PY'
import os
import time

import httpx
from app.adapters.tmdb import summarize_tmdb_http_error

token = os.environ.get("TMDB_API_READ_ACCESS_TOKEN", "")
if not token:
    print("TMDB token missing in container environment.")
    raise SystemExit(1)

with httpx.Client(
    timeout=10,
    trust_env=False,
    headers={
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
        "user-agent": "cineSense/0.1",
    },
) as client:
    last_error = None
    for attempt in range(3):
        try:
            response = client.get(
                "https://api.themoviedb.org/3/movie/155/recommendations",
                params={"page": "1"},
            )
            if response.status_code == 200:
                raise SystemExit(0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            category, detail = summarize_tmdb_http_error(exc)
            last_error = f"{category}: {detail}"
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
                print(f"TMDB probe auth failure: {detail}")
                raise SystemExit(1)
        if attempt < 2:
            time.sleep(0.2 * (attempt + 1))
    print(f"TMDB probe failed after retries: {last_error}")
    raise SystemExit(1)
PY
then
  echo "TMDB probe failed."
  echo "The API container could not complete the known-good TMDB recommendations probe."
  echo "Classify the failure above as TLS/network, DNS/connectivity, or auth before changing credentials."
  echo "Rerun after fixing the reported cause: ./scripts/start-phase-1a.sh"
  exit 1
fi

echo "Phase 1A is up."
echo "Web: http://localhost:3000"
echo "API: http://localhost:8000"
exec docker compose logs -f
