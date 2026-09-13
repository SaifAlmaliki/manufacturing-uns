#!/usr/bin/env bash
# Prepare /opt/uns-edge from the synced repo: TLS, agent.env, then install.sh.
set -euo pipefail
# shellcheck source=common.sh
. "$(cd "$(dirname "$0")" && pwd)/common.sh"

REPO_ROOT="${UNS_REPO_ROOT:?}"
EDGE_SRC="${REPO_ROOT}/deploy/edge"
DESTINATION="${UNS_EDGE_DESTINATION:-/opt/uns-edge}"
CONSOLE_HOST="${UNS_CONSOLE_HOST:?}"
ENROLL_HOST="${UNS_ENROLL_HOST:?}"
MGMT_HOST="${UNS_MGMT_HOST:?}"
MQTT_HOST="${UNS_MQTT_HOST:?}"
EDGE_ID="${UNS_EDGE_ID:-site-01}"
CLOUD_CA_SRC="${UNS_CLOUD_CA_FILE:-}"

require_cmd docker
require_cmd python3
require_cmd openssl
require_cmd rsync
require_cmd envsubst

if [[ "$(id -u)" -ne 0 ]]; then
  die "edge-bootstrap.sh must run as root so install.sh can write ${DESTINATION}"
fi

ensure_dir /tmp/uns-edge-env 0750
ENV_EXPORT=/tmp/uns-edge-env/hivemq.env
if [[ ! -f "${ENV_EXPORT}" ]]; then
  cat > "${ENV_EXPORT}" <<EOF
EDGE_MQTT_KEYSTORE_PASSWORD=$(rand_secret)
EDGE_MQTT_TRUSTSTORE_PASSWORD=$(rand_secret)
EDGE_API_KEYSTORE_PASSWORD=$(rand_secret)
EDGE_API_TRUSTSTORE_PASSWORD=$(rand_secret)
BRIDGE_KEYSTORE_PASSWORD=$(rand_secret)
BRIDGE_TRUSTSTORE_PASSWORD=$(rand_secret)
EDGE_ID=${EDGE_ID}
CLOUD_MQTT_HOST=${MQTT_HOST}
BRIDGE_CLIENT_ID=${EDGE_ID}-bridge
BRIDGE_TOPIC_PREFIX=Enterprise/
EOF
  chmod 0600 "${ENV_EXPORT}"
fi
# shellcheck disable=SC1090
set -a
. "${ENV_EXPORT}"
set +a

# install.sh requires digest-looking sha256 strings; placeholders already match.
bash "${EDGE_SRC}/install.sh" --destination "${DESTINATION}"

# After install.sh, overwrite agent.env with real cloud endpoints.
EDGE_API_USER="${UNS_EDGE_API_USERNAME:-admin}"
EDGE_API_PASSWORD="${UNS_EDGE_API_PASSWORD:-}"
if [[ -z "${EDGE_API_PASSWORD}" ]]; then
  EDGE_API_PASSWORD="$(rand_secret)"
fi

cat > "${DESTINATION}/agent.env" <<EOF
UNS_EDGE_CLOUD_URL=https://${MGMT_HOST}
UNS_EDGE_ENROLL_URL=https://${ENROLL_HOST}
UNS_EDGE_ENDPOINT_ALLOWLIST=${MGMT_HOST},${ENROLL_HOST},${MQTT_HOST},${CONSOLE_HOST}
UNS_EDGE_API_URL=https://hivemq-edge:8443
UNS_EDGE_API_USERNAME=${EDGE_API_USER}
UNS_EDGE_API_PASSWORD=${EDGE_API_PASSWORD}
UNS_EDGE_CA_FILE=/etc/uns/cloud-ca.pem
EOF
chmod 0640 "${DESTINATION}/agent.env"

cat > "${DESTINATION}/secrets/edge-api.env" <<EOF
UNS_EDGE_API_USERNAME=${EDGE_API_USER}
UNS_EDGE_API_PASSWORD=${EDGE_API_PASSWORD}
EOF
chmod 0600 "${DESTINATION}/secrets/edge-api.env"

set_env_value "${DESTINATION}/simulation/secrets/mqtt-sim.env" "MQTT_USERNAME" "edge-sim-publisher"
if grep -q 'MQTT_PASSWORD=replace-with-local-simulator-secret' "${DESTINATION}/simulation/secrets/mqtt-sim.env"; then
  set_env_value "${DESTINATION}/simulation/secrets/mqtt-sim.env" "MQTT_PASSWORD" "$(rand_secret)"
fi

# Cloud CA used by the agent for first enrollment (no client cert yet).
if [[ -n "${CLOUD_CA_SRC}" && -f "${CLOUD_CA_SRC}" ]]; then
  cp "${CLOUD_CA_SRC}" "${DESTINATION}/secrets/cloud-ca.pem"
elif [[ -f "${REPO_ROOT}/deploy/cloud/secrets/tls/ca/ca.crt" ]]; then
  cp "${REPO_ROOT}/deploy/cloud/secrets/tls/ca/ca.crt" "${DESTINATION}/secrets/cloud-ca.pem"
fi

# Local Edge MQTT CA + server/client material for simulators.
TLS_DIR="${DESTINATION}/hivemq/tls"
ensure_dir "${TLS_DIR}" 0750
ensure_dir "${DESTINATION}/simulation/secrets" 0750
if [[ ! -f "${TLS_DIR}/edge-ca.crt" ]]; then
  log "Generating Edge MQTT/API TLS material"
  openssl genrsa -out "${TLS_DIR}/edge-ca.key" 4096
  openssl req -x509 -new -nodes -key "${TLS_DIR}/edge-ca.key" -sha256 -days 825 \
    -subj "/CN=${EDGE_ID} Edge CA" -out "${TLS_DIR}/edge-ca.crt"
  openssl genrsa -out "${TLS_DIR}/edge-mqtt.key" 2048
  openssl req -new -key "${TLS_DIR}/edge-mqtt.key" -subj "/CN=hivemq-edge" -out "${TLS_DIR}/edge-mqtt.csr"
  openssl x509 -req -in "${TLS_DIR}/edge-mqtt.csr" -CA "${TLS_DIR}/edge-ca.crt" -CAkey "${TLS_DIR}/edge-ca.key" \
    -CAcreateserial -days 825 -sha256 \
    -extfile <(printf 'subjectAltName=DNS:hivemq-edge,DNS:localhost,IP:127.0.0.1\n') \
    -out "${TLS_DIR}/edge-mqtt.crt"
  openssl pkcs12 -export -in "${TLS_DIR}/edge-mqtt.crt" -inkey "${TLS_DIR}/edge-mqtt.key" \
    -certfile "${TLS_DIR}/edge-ca.crt" -name edge-mqtt \
    -out "${TLS_DIR}/edge-mqtt-keystore.p12" -passout "pass:${EDGE_MQTT_KEYSTORE_PASSWORD}"
  openssl genrsa -out "${TLS_DIR}/edge-api.key" 2048
  openssl req -new -key "${TLS_DIR}/edge-api.key" -subj "/CN=hivemq-edge-api" -out "${TLS_DIR}/edge-api.csr"
  openssl x509 -req -in "${TLS_DIR}/edge-api.csr" -CA "${TLS_DIR}/edge-ca.crt" -CAkey "${TLS_DIR}/edge-ca.key" \
    -CAcreateserial -days 825 -sha256 \
    -extfile <(printf 'subjectAltName=DNS:hivemq-edge,DNS:localhost\n') \
    -out "${TLS_DIR}/edge-api.crt"
  openssl pkcs12 -export -in "${TLS_DIR}/edge-api.crt" -inkey "${TLS_DIR}/edge-api.key" \
    -certfile "${TLS_DIR}/edge-ca.crt" -name edge-api \
    -out "${TLS_DIR}/edge-api-keystore.p12" -passout "pass:${EDGE_API_KEYSTORE_PASSWORD}"
  openssl genrsa -out "${TLS_DIR}/bridge-placeholder.key" 2048
  openssl req -new -key "${TLS_DIR}/bridge-placeholder.key" -subj "/CN=${EDGE_ID}-bridge" \
    -out "${TLS_DIR}/bridge-placeholder.csr"
  openssl x509 -req -in "${TLS_DIR}/bridge-placeholder.csr" -CA "${TLS_DIR}/edge-ca.crt" \
    -CAkey "${TLS_DIR}/edge-ca.key" -CAcreateserial -days 30 -sha256 \
    -out "${TLS_DIR}/bridge-placeholder.crt"
  openssl pkcs12 -export -in "${TLS_DIR}/bridge-placeholder.crt" \
    -inkey "${TLS_DIR}/bridge-placeholder.key" -certfile "${TLS_DIR}/edge-ca.crt" \
    -name mqtt-bridge -out "${TLS_DIR}/bridge-keystore.p12" \
    -passout "pass:${BRIDGE_KEYSTORE_PASSWORD}"
  openssl genrsa -out "${DESTINATION}/simulation/secrets/edge-mqtt-client.key" 2048
  openssl req -new -key "${DESTINATION}/simulation/secrets/edge-mqtt-client.key" \
    -subj "/CN=edge-sim-publisher" -out "${TLS_DIR}/sim.csr"
  openssl x509 -req -in "${TLS_DIR}/sim.csr" -CA "${TLS_DIR}/edge-ca.crt" -CAkey "${TLS_DIR}/edge-ca.key" \
    -CAcreateserial -days 825 -sha256 -out "${DESTINATION}/simulation/secrets/edge-mqtt-client.pem"
  cp "${TLS_DIR}/edge-ca.crt" "${DESTINATION}/simulation/secrets/edge-mqtt-ca.pem"
  rm -f "${TLS_DIR}/"*.csr
fi

# Java truststores for Edge (server trusts the same CA, including simulator clients).
docker run --rm \
  -v "${TLS_DIR}:/work" \
  -e MQTT_TS_PASS="${EDGE_MQTT_TRUSTSTORE_PASSWORD}" \
  -e API_TS_PASS="${EDGE_API_TRUSTSTORE_PASSWORD}" \
  eclipse-temurin:17-jdk \
  bash -c 'cd /work && \
    keytool -importcert -noprompt -alias edge-ca -file edge-ca.crt \
      -keystore edge-mqtt-truststore.jks -storepass "$MQTT_TS_PASS" && \
    keytool -importcert -noprompt -alias edge-ca -file edge-ca.crt \
      -keystore edge-api-truststore.jks -storepass "$API_TS_PASS"'

if [[ -f "${DESTINATION}/secrets/cloud-ca.pem" ]]; then
  docker run --rm \
    -v "${TLS_DIR}:/work" \
    -v "${DESTINATION}/secrets/cloud-ca.pem:/ca/cloud-ca.pem:ro" \
    -e BRIDGE_TS_PASS="${BRIDGE_TRUSTSTORE_PASSWORD}" \
    eclipse-temurin:17-jdk \
    bash -c 'cd /work && keytool -importcert -noprompt -alias cloud-ca -file /ca/cloud-ca.pem \
      -keystore cloud-mqtt-truststore.jks -storepass "$BRIDGE_TS_PASS"'
fi

# Copy keystores into names expected by config.xml.template (rendered to hivemq/config.xml).
cp -f "${TLS_DIR}/edge-mqtt-keystore.p12" "${TLS_DIR}/edge-mqtt-keystore.p12"
# install.sh already rendered config.xml; copy TLS files next to HiveMQ conf mount.
# The compose volume is a named volume, so seed files into hivemq/ which we bind via override.

cat > "${DESTINATION}/simulation/secrets/mqtt-tls.env" <<EOF
MQTT_CA_FILE=/run/secrets/mqtt_ca
MQTT_CERT_FILE=/run/secrets/mqtt_cert
MQTT_KEY_FILE=/run/secrets/mqtt_key
EOF
chmod 0600 "${DESTINATION}/simulation/secrets/mqtt-tls.env"

# Re-render HiveMQ config with real env values.
envsubst < "${DESTINATION}/hivemq/config.xml.template" > "${DESTINATION}/hivemq/config.xml"

log "Edge host prepared at ${DESTINATION}"
log "Enrollment URL: https://${ENROLL_HOST}"
log "Management URL: https://${MGMT_HOST}"
