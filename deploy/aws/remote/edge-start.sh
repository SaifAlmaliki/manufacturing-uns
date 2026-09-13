#!/usr/bin/env bash
# Start the edge bundle and optionally the edge-sim profile.
set -euo pipefail
# shellcheck source=common.sh
. "$(cd "$(dirname "$0")" && pwd)/common.sh"

DESTINATION="${UNS_EDGE_DESTINATION:-/opt/uns-edge}"
ENABLE_SIM="${UNS_EDGE_ENABLE_SIM:-1}"
cd "${DESTINATION}"

[[ -f compose.yml ]] || die "missing ${DESTINATION}/compose.yml"
[[ -f compose.images.yml ]] || die "run edge-build-images.sh first"
[[ -f agent.env ]] || die "missing agent.env"

COMPOSE=(docker compose --project-directory "${DESTINATION}" -f compose.yml)
if [[ "${ENABLE_SIM}" == "1" ]]; then
  COMPOSE+=(-f compose.simulation.yml --profile edge-sim)
fi
COMPOSE+=(-f compose.images.yml)

log "Rendering edge compose configuration"
"${COMPOSE[@]}" config --quiet

log "Starting edge services"
"${COMPOSE[@]}" up -d

if [[ -x "${DESTINATION}/verify.sh" ]]; then
  VERIFY=(bash "${DESTINATION}/verify.sh" --destination "${DESTINATION}")
  if [[ "${ENABLE_SIM}" == "1" ]]; then
    VERIFY+=(--profile edge-sim)
  fi
  # verify.sh checks running status; give Edge time to become healthy.
  sleep 15
  "${VERIFY[@]}" || log "verify.sh reported issues; inspect docker compose ps and logs"
fi

"${COMPOSE[@]}" ps
ENROLL_URL="$(grep -E '^UNS_EDGE_ENROLL_URL=' "${DESTINATION}/agent.env" | cut -d= -f2- || true)"
log "Edge stack started."
log "Enroll after the cloud console issues a token:"
log "  docker compose --project-directory ${DESTINATION} -f ${DESTINATION}/compose.yml -f ${DESTINATION}/compose.images.yml exec uns-edge-agent uv run --package uns_edge_agent uns_edge_enroll --token <token> --cloud-url ${ENROLL_URL:-https://enroll.example}"
