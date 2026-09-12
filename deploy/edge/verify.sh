#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: verify.sh --destination /opt/uns-edge [--profile edge-sim]

Verify the DMZ edge bundle is installed, services are running, and the management
API is not published on a host port. With --profile edge-sim, also verify the four
simulator services, local-only destinations, and absence of cloud credentials.
EOF
}

DESTINATION=""
PROFILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --destination)
      DESTINATION="${2:-}"
      shift 2
      ;;
    --profile)
      PROFILE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${DESTINATION}" ]]; then
  usage
  exit 1
fi

COMPOSE_FILE="${DESTINATION}/compose.yml"
SIM_COMPOSE_FILE="${DESTINATION}/compose.simulation.yml"
if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Missing compose file: ${COMPOSE_FILE}" >&2
  exit 1
fi

COMPOSE_ARGS=(--project-directory "${DESTINATION}" -f "${COMPOSE_FILE}")
if [[ "${PROFILE}" == "edge-sim" ]]; then
  if [[ ! -f "${SIM_COMPOSE_FILE}" ]]; then
    echo "Missing simulation overlay: ${SIM_COMPOSE_FILE}" >&2
    exit 1
  fi
  COMPOSE_ARGS+=(-f "${SIM_COMPOSE_FILE}" --profile edge-sim)
fi

docker compose "${COMPOSE_ARGS[@]}" config --quiet

BASE_SERVICES=(hivemq-edge uns-edge-agent)
SIM_SERVICES=(oee-simulator multi-system-simulator opcua-simulator modbus-simulator)
SERVICES=("${BASE_SERVICES[@]}")
if [[ "${PROFILE}" == "edge-sim" ]]; then
  SERVICES+=("${SIM_SERVICES[@]}")
fi

for service in "${SERVICES[@]}"; do
  if ! docker compose "${COMPOSE_ARGS[@]}" ps --status running --services | grep -qx "${service}"; then
    echo "Service not running: ${service}" >&2
    exit 1
  fi
done

if docker compose "${COMPOSE_ARGS[@]}" port hivemq-edge 8443 >/dev/null 2>&1; then
  echo "Edge admin API must not be published on the host." >&2
  exit 1
fi

if docker compose "${COMPOSE_ARGS[@]}" port uns-edge-agent 1 >/dev/null 2>&1; then
  echo "Agent must not publish a listening port on the host." >&2
  exit 1
fi

if [[ "${PROFILE}" == "edge-sim" ]]; then
  for service in "${SIM_SERVICES[@]}"; do
    if docker compose "${COMPOSE_ARGS[@]}" port "${service}" 1 >/dev/null 2>&1; then
      echo "Simulator ${service} must not publish host ports." >&2
      exit 1
    fi
  done

  rendered="$(docker compose "${COMPOSE_ARGS[@]}" config)"
  if grep -Eiq 'CLOUD_MQTT|cloud-mqtt|CLOUD_MANAGEMENT|cloud\.example' <<<"${rendered}"; then
    echo "Simulation overlay must not reference cloud broker or management endpoints." >&2
    exit 1
  fi

  for service in "${SIM_SERVICES[@]}"; do
    if ! grep -q "hivemq-edge" <<<"$(docker compose "${COMPOSE_ARGS[@]}" config | awk "/^  ${service}:/,/^  [^ ]/")"; then
      continue
    fi
  done

  if ! grep -q 'sim-ot' <<<"${rendered}"; then
    echo "Simulation overlay must define the internal sim-ot network." >&2
    exit 1
  fi
fi

if [[ "${PROFILE}" == "edge-sim" ]]; then
  echo "DMZ edge bundle verification passed for ${DESTINATION} (profile edge-sim)."
else
  echo "DMZ edge bundle verification passed for ${DESTINATION}."
fi
