#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DB_SERVICE="db"
HEALTH_TIMEOUT_SECONDS=60
TEST_PATH="tests/test_postgres_integration.py"
TEST_DSN="postgresql+psycopg://cinesense:cinesense@db:5432/postgres"

fail() {
  echo "FAIL: $1"
  exit 1
}

if ! command -v docker >/dev/null 2>&1; then
  fail "docker is unavailable"
fi

if ! docker compose version >/dev/null 2>&1; then
  fail "docker compose is unavailable"
fi

docker compose up -d "$DB_SERVICE" >/dev/null

container_id="$(docker compose ps -q "$DB_SERVICE")"
if [[ -z "$container_id" ]]; then
  fail "postgres container is not running"
fi

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
while true; do
  health_status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' "$container_id" 2>/dev/null || true)"
  if [[ "$health_status" == "healthy" ]]; then
    break
  fi
  if (( SECONDS >= deadline )); then
    fail "postgres did not become healthy within ${HEALTH_TIMEOUT_SECONDS}s"
  fi
  sleep 2
done

set +e
test_output="$(
  docker compose run --rm -T \
    -e CINESENSE_TEST_DATABASE_URL="$TEST_DSN" \
    -v "$ROOT_DIR/services/api:/app/services/api" \
    api \
    sh -lc "cd /app/services/api && python -m pytest -c /dev/null -o 'markers=integration: tests that require the Docker-backed PostgreSQL environment' -m integration $TEST_PATH -v" 2>&1
)"
test_status=$?
set -e

printf '%s\n' "$test_output"

if (( test_status != 0 )); then
  fail "postgres verification test failed"
fi

if grep -Eq '(^|[[:space:]])SKIPPED([[:space:]]|$)' <<<"$test_output"; then
  fail "postgres verification test was skipped"
fi

if ! grep -Eq '(^|[[:space:]])1 passed([[:space:],]|$)' <<<"$test_output"; then
  fail "postgres verification test did not report a passing result"
fi

echo "PASS"
