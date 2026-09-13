#!/usr/bin/env bash
# After uns_edge_enroll, copy the issued MQTT client keystore into the Edge bridge.
set -euo pipefail
# shellcheck source=common.sh
. "$(cd "$(dirname "$0")" && pwd)/common.sh"

DESTINATION="${UNS_EDGE_DESTINATION:-/opt/uns-edge}"
cd "${DESTINATION}"
COMPOSE=(docker compose --project-directory "${DESTINATION}" -f compose.yml -f compose.images.yml)

CRED_DIR="/var/lib/uns-edge-agent/credentials"
"${COMPOSE[@]}" exec -T uns-edge-agent test -f "${CRED_DIR}/mqtt.keystore.p12" \
  || die "MQTT keystore missing; did uns_edge_enroll succeed?"

"${COMPOSE[@]}" exec -T uns-edge-agent cat "${CRED_DIR}/mqtt.keystore.p12" \
  > "${DESTINATION}/hivemq/tls/bridge-keystore.p12"
chmod 0600 "${DESTINATION}/hivemq/tls/bridge-keystore.p12"
BRIDGE_PASS="$("${COMPOSE[@]}" exec -T uns-edge-agent cat "${CRED_DIR}/mqtt.keystore.pass" | tr -d '\r\n')"

python3 - "${DESTINATION}/hivemq/config.xml" "${BRIDGE_PASS}" <<'PY'
from pathlib import Path
import re, sys
path = Path(sys.argv[1])
password = sys.argv[2]
text = path.read_text(encoding="utf-8")
# Replace the bridge keystore password element only.
text, n = re.subn(
    r"(<mqtt-bridge>.*?<keystore>.*?<password>)(.*?)(</password>)",
    r"\1" + password + r"\3",
    text,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit(f"could not update bridge keystore password ({n} matches)")
path.write_text(text, encoding="utf-8")
PY

log "Restarting hivemq-edge to load enrolled bridge certificate"
"${COMPOSE[@]}" restart hivemq-edge
log "Bridge keystore installed from enrollment material"
