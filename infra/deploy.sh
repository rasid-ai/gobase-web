#!/bin/sh
# Runs on the VPS, in the same directory as docker-compose.prod.yml and .env.
# CI copies this file and the compose file in, exports IMAGE_TAG to the commit
# SHA, and runs it over SSH.
#
# To roll back: export IMAGE_TAG=<old-sha> and rerun this script. The images
# for every deployed SHA stay in GHCR, and each carries its own migrations and
# its own admin static files, so a rollback is a single command.
set -eu

cd "$(dirname "$0")"

# docker compose reads .env automatically for its own variable substitution,
# but this is a plain shell script — nothing loads .env into its environment
# unless we do it explicitly here.
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

: "${GHCR_OWNER:?GHCR_OWNER must be set in .env — the image names are built from it}"

echo "Pulling images (tag: ${IMAGE_TAG:-latest})..."
docker compose -f docker-compose.prod.yml pull

# The backend container migrates `portal` on start, from its own entrypoint —
# the image and the schema it expects therefore ship together.
echo "Restarting services..."
docker compose -f docker-compose.prod.yml up -d

# No `docker image prune` here. It is host-wide, not project-scoped, so on a
# box running other projects it deletes their dangling images too. Ours are
# tagged with their commit SHA and so are never dangling anyway — that is what
# keeps a rollback possible. Reclaim space deliberately instead:
#   docker images 'ghcr.io/*/geo-portal-*' --format '{{.Repository}}:{{.Tag}}'

echo "Waiting for backend health check..."
# HEALTH_CHECK_URL must be the real public URL in .env (e.g.
# https://portal.example/api/health/) — nginx routes by server_name, so a bare
# "http://localhost/..." falls through to a different site on a multi-tenant
# box instead of matching this app's config. Checking through nginx is the
# point: it proves TLS, routing and the app, not just the process.
health_check_url="${HEALTH_CHECK_URL:-http://localhost/api/health/}"
attempts=0
max_attempts=30
until curl -sf "$health_check_url" > /dev/null; do
  attempts=$((attempts + 1))
  if [ "$attempts" -ge "$max_attempts" ]; then
    echo "Health check failed after ${max_attempts} attempts (60s) — deploy did not complete successfully." >&2
    echo "Recent backend logs:" >&2
    docker compose -f docker-compose.prod.yml logs --tail 50 backend >&2
    exit 1
  fi
  sleep 2
done

echo "Deploy successful — backend is healthy."
