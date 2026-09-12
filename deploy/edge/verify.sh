#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: verify.sh --destination /opt/uns-edge

Verify the DMZ edge bundle is installed, both services are running, and the
management API is not published on a host port.
EOF
}

DESTINATION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --destination)
      DESTINATION="${2:-}"
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
if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Missing compose file: ${COMPOSE_FILE}" >&2
  exit 1
fi

docker compose --project-directory "${DESTINATION}" -f "${COMPOSE_FILE}" config --quiet

for service in hivemq-edge uns-edge-agent; do
  if ! docker compose --project-directory "${DESTINATION}" -f "${COMPOSE_FILE}" ps --status running --services | grep -qx "${service}"; then
    echo "Service not running: ${service}" >&2
    exit 1
  fi
done

if docker compose --project-directory "${DESTINATION}" -f "${COMPOSE_FILE}" port hivemq-edge 8443 >/dev/null 2>&1; then
  echo "Edge admin API must not be published on the host." >&2
  exit 1
fi

if docker compose --project-directory "${DESTINATION}" -f "${COMPOSE_FILE}" port uns-edge-agent 1 >/dev/null 2>&1; then
  echo "Agent must not publish a listening port on the host." >&2
  exit 1
fi

echo "DMZ edge bundle verification passed for ${DESTINATION}."
