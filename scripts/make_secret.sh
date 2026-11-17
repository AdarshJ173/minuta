#!/usr/bin/env bash
# Rebuild the Modal secret from local .env. Values are never printed.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
. ./.env
set +a

require() { [ -n "${!1:-}" ] || { echo "missing $1 in .env" >&2; exit 1; }; }
require DATABASE_URL; require R2_ENDPOINT; require R2_BUCKET_NAME
require R2_ACCESS_KEY_ID; require R2_SECRET_ACCESS_KEY; require YOUTUBE_API_KEY
require PUBLIC_BASE_URL

ARGS=(
  "DATABASE_URL=${DATABASE_URL}"
  "R2_ENDPOINT=${R2_ENDPOINT}" "R2_BUCKET_NAME=${R2_BUCKET_NAME}"
  "R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID}" "R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY}"
  "YOUTUBE_API_KEY=${YOUTUBE_API_KEY}" "PUBLIC_BASE_URL=${PUBLIC_BASE_URL}"
  "ENV=prod" "LOG_FORMAT=json"
  "TRANSCRIPT_PROVIDER_ORDER=${TRANSCRIPT_PROVIDER_ORDER:-yta}"
)
[ -n "${ALLOWED_HOSTS:-}" ] && ARGS+=("ALLOWED_HOSTS=${ALLOWED_HOSTS}")
[ -n "${SUPADATA_API_KEY:-}" ] && ARGS+=("SUPADATA_API_KEY=${SUPADATA_API_KEY}")
[ -n "${APIFY_API_TOKEN:-}" ] && ARGS+=("APIFY_API_TOKEN=${APIFY_API_TOKEN}")
[ -n "${ADMIN_BOOTSTRAP_TOKEN:-}" ] && ARGS+=("ADMIN_BOOTSTRAP_TOKEN=${ADMIN_BOOTSTRAP_TOKEN}")
[ -n "${WORKER_CONCURRENCY:-}" ] && ARGS+=("WORKER_CONCURRENCY=${WORKER_CONCURRENCY}")

modal secret create minuta --force "${ARGS[@]}"
echo "secret minuta refreshed with ${#ARGS[@]} keys (values not printed)"
