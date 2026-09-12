#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install.sh --destination /opt/uns-edge

Install a verified UNS DMZ edge bundle. Re-running preserves existing identity,
configuration, and journal volumes under the destination directory.
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

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "install.sh supports Linux installation hosts only." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Engine is required." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is required." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_FILE="${SCRIPT_DIR}/release.json"
if [[ ! -f "${RELEASE_FILE}" ]]; then
  echo "Missing trusted release manifest: ${RELEASE_FILE}" >&2
  exit 1
fi

python3 - <<'PY' "${RELEASE_FILE}"
import json
import re
import sys
from pathlib import Path

release = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
pattern = re.compile(r"^sha256:[0-9a-f]{64}$")
for name, image in release.get("images", {}).items():
    digest = image.get("digest", "")
    if not pattern.fullmatch(digest):
        raise SystemExit(f"Untrusted image digest for {name}: {digest}")
PY

AVAILABLE_KB="$(df -Pk "${DESTINATION%/*}" 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ -n "${AVAILABLE_KB}" && "${AVAILABLE_KB}" -lt 10485760 ]]; then
  echo "At least 10 GiB free disk is recommended for ${DESTINATION}." >&2
  exit 1
fi

mkdir -p "${DESTINATION}"
install -d -m 0750 "${DESTINATION}/secrets" "${DESTINATION}/hivemq" "${DESTINATION}/state"

rsync -a --exclude 'state/' --exclude 'secrets/edge-api.env' --exclude 'agent.env' "${SCRIPT_DIR}/" "${DESTINATION}/"

if [[ ! -f "${DESTINATION}/agent.env" ]]; then
  install -m 0640 "${DESTINATION}/agent.env.example" "${DESTINATION}/agent.env"
fi

if [[ ! -f "${DESTINATION}/secrets/edge-api.env" ]]; then
  install -m 0600 "${DESTINATION}/secrets/edge-api.env.example" "${DESTINATION}/secrets/edge-api.env"
fi

if [[ ! -f "${DESTINATION}/hivemq/config.xml" ]]; then
  envsubst < "${DESTINATION}/hivemq/config.xml.template" > "${DESTINATION}/hivemq/config.xml"
fi

echo "Installed verified bundle to ${DESTINATION}. Start with:"
echo "  docker compose --project-directory ${DESTINATION} -f ${DESTINATION}/compose.yml up -d"
