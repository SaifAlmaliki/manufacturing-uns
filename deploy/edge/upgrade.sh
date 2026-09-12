#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: upgrade.sh --destination /opt/uns-edge --release <release_id>

Upgrade a verified DMZ edge bundle. Creates a timestamped backup of configuration,
secrets, and release metadata before applying the named release.
EOF
}

DESTINATION=""
RELEASE_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --destination)
      DESTINATION="${2:-}"
      shift 2
      ;;
    --release)
      RELEASE_ID="${2:-}"
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

if [[ -z "${DESTINATION}" || -z "${RELEASE_ID}" ]]; then
  usage
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_RELEASE="${SCRIPT_DIR}/releases/${RELEASE_ID}"
if [[ ! -d "${TARGET_RELEASE}" ]]; then
  echo "Named release not found: ${RELEASE_ID}" >&2
  exit 1
fi

BACKUP_DIR="${DESTINATION}/backups/$(date -u +%Y%m%dT%H%M%SZ)-${RELEASE_ID}"
mkdir -p "${BACKUP_DIR}"
cp -a "${DESTINATION}/compose.yml" "${DESTINATION}/release.json" "${BACKUP_DIR}/"
[[ -f "${DESTINATION}/agent.env" ]] && cp -a "${DESTINATION}/agent.env" "${BACKUP_DIR}/"
[[ -d "${DESTINATION}/hivemq" ]] && cp -a "${DESTINATION}/hivemq" "${BACKUP_DIR}/"
[[ -d "${DESTINATION}/secrets" ]] && cp -a "${DESTINATION}/secrets" "${BACKUP_DIR}/"

rsync -a "${TARGET_RELEASE}/" "${DESTINATION}/"
echo "Upgraded ${DESTINATION} to release ${RELEASE_ID}. Backup: ${BACKUP_DIR}"
