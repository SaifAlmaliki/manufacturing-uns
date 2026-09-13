#!/usr/bin/env bash
# Validate compose and start the cloud bundle.
set -euo pipefail
# shellcheck source=common.sh
. "$(cd "$(dirname "$0")" && pwd)/common.sh"

REPO_ROOT="${UNS_REPO_ROOT:?}"
BUNDLE_DIR="${UNS_CLOUD_BUNDLE:-${REPO_ROOT}/deploy/cloud}"
cd "${BUNDLE_DIR}"

[[ -f compose.yml ]] || die "missing ${BUNDLE_DIR}/compose.yml"
[[ -f compose.images.yml ]] || die "run cloud-build-images.sh first"
[[ -f secrets/runtime.env ]] || die "missing secrets/runtime.env"
[[ -f settings.yaml ]] || die "missing settings.yaml"

COMPOSE=(docker compose --env-file secrets/runtime.env -f compose.yml -f compose.images.yml)

log "Rendering compose configuration"
"${COMPOSE[@]}" config --quiet

log "Starting cloud stack (first boot can take several minutes)"
"${COMPOSE[@]}" up -d

log "Waiting for proxy health"
for _ in $(seq 1 60); do
  if docker inspect --format '{{.State.Health.Status}}' uns_proxy 2>/dev/null | grep -qx healthy; then
    log "uns_proxy is healthy"
    break
  fi
  sleep 5
done

"${COMPOSE[@]}" ps
log "Cloud stack started. Console: ${UNS_CONSOLE_ORIGIN:-see settings.yaml}"
log "This is an unqualified demo deployment until HiveMQ licenses and image digests are operator-qualified."
