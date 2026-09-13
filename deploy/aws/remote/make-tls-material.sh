#!/usr/bin/env bash
# Create demo CA, HTTPS PEMs, and HiveMQ JKS material on the cloud host.
set -euo pipefail
# shellcheck source=common.sh
. "$(cd "$(dirname "$0")" && pwd)/common.sh"

BUNDLE_DIR="${UNS_CLOUD_BUNDLE:?UNS_CLOUD_BUNDLE is required}"
TLS_DIR="${BUNDLE_DIR}/secrets/tls"
BROKER_TLS_DIR="${BUNDLE_DIR}/secrets/broker-tls"
CONSOLE_HOST="${UNS_CONSOLE_HOST:?}"
ENROLL_HOST="${UNS_ENROLL_HOST:?}"
MGMT_HOST="${UNS_MGMT_HOST:?}"
MQTT_HOST="${UNS_MQTT_HOST:?}"
PUBLICATIONS_HOST="${UNS_PUBLICATIONS_HOST:?}"

ensure_dir "${TLS_DIR}/ca" 0750
ensure_dir "${TLS_DIR}/console" 0750
ensure_dir "${TLS_DIR}/enrollment" 0750
ensure_dir "${TLS_DIR}/management" 0750
ensure_dir "${TLS_DIR}/publications" 0750
ensure_dir "${BROKER_TLS_DIR}" 0750

CA_KEY="${TLS_DIR}/ca/ca.key"
CA_CRT="${TLS_DIR}/ca/ca.crt"
if [[ ! -f "${CA_CRT}" ]]; then
  log "Generating demo certificate authority"
  openssl genrsa -out "${CA_KEY}" 4096
  openssl req -x509 -new -nodes -key "${CA_KEY}" -sha256 -days 825 \
    -subj "/CN=UNS Demo CA" \
    -addext "basicConstraints=critical,CA:true" \
    -out "${CA_CRT}"
fi

issue_server() {
  local name="$1"
  local dir="$2"
  local cn="$3"
  shift 3
  local san="$1"
  ensure_dir "${dir}" 0750
  if [[ -f "${dir}/fullchain.pem" ]]; then
    return 0
  fi
  log "Issuing server certificate for ${cn}"
  openssl genrsa -out "${dir}/privkey.pem" 2048
  openssl req -new -key "${dir}/privkey.pem" -subj "/CN=${cn}" -out "${dir}/csr.pem"
  openssl x509 -req -in "${dir}/csr.pem" -CA "${CA_CRT}" -CAkey "${CA_KEY}" -CAcreateserial \
    -days 825 -sha256 \
    -extfile <(printf 'subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth,clientAuth\n' "${san}") \
    -out "${dir}/cert.pem"
  cat "${dir}/cert.pem" "${CA_CRT}" > "${dir}/fullchain.pem"
  cp "${CA_CRT}" "${dir}/ca.pem"
  rm -f "${dir}/csr.pem"
}

issue_server console "${TLS_DIR}/console" "${CONSOLE_HOST}" "DNS:${CONSOLE_HOST}"
issue_server enrollment "${TLS_DIR}/enrollment" "${ENROLL_HOST}" "DNS:${ENROLL_HOST}"
issue_server management "${TLS_DIR}/management" "${MGMT_HOST}" "DNS:${MGMT_HOST}"
issue_server publications "${TLS_DIR}/publications" "${PUBLICATIONS_HOST}" "DNS:${PUBLICATIONS_HOST}"
issue_server mqtt "${TLS_DIR}/mqtt" "${MQTT_HOST}" "DNS:${MQTT_HOST}"

cp "${CA_CRT}" "${TLS_DIR}/management/ca.pem"
cp "${CA_CRT}" "${TLS_DIR}/publications/ca.pem"

BROKER_PASSWORD_FILE="${BUNDLE_DIR}/secrets/broker-tls.env"
if [[ ! -f "${BROKER_PASSWORD_FILE}" ]] || grep -q 'BROKER_KEYSTORE_PASSWORD=$' "${BROKER_PASSWORD_FILE}" 2>/dev/null; then
  KS_PASS="$(rand_secret)"
  mkdir -p "$(dirname "${BROKER_PASSWORD_FILE}")"
  cat > "${BROKER_PASSWORD_FILE}" <<EOF
BROKER_KEYSTORE_PASSWORD=${KS_PASS}
BROKER_KEY_PASSWORD=${KS_PASS}
BROKER_TRUSTSTORE_PASSWORD=${KS_PASS}
EOF
  chmod 0600 "${BROKER_PASSWORD_FILE}"
fi

# shellcheck disable=SC1090
. "${BROKER_PASSWORD_FILE}"

P12="${BROKER_TLS_DIR}/broker.p12"
if [[ ! -f "${BROKER_TLS_DIR}/broker-keystore.jks" ]]; then
  log "Building HiveMQ JKS keystore and truststore"
  openssl pkcs12 -export \
    -in "${TLS_DIR}/mqtt/fullchain.pem" \
    -inkey "${TLS_DIR}/mqtt/privkey.pem" \
    -certfile "${CA_CRT}" \
    -name mqtt-broker \
    -out "${P12}" \
    -passout "pass:${BROKER_KEYSTORE_PASSWORD}"
  docker run --rm \
    -v "${BROKER_TLS_DIR}:/work" \
    -v "${TLS_DIR}/ca:/ca:ro" \
    -e KS_PASS="${BROKER_KEYSTORE_PASSWORD}" \
    eclipse-temurin:17-jdk \
    bash -c 'cd /work && \
      keytool -importkeystore -noprompt \
        -srckeystore broker.p12 -srcstoretype PKCS12 -srcstorepass "$KS_PASS" \
        -destkeystore broker-keystore.jks -deststoretype JKS -deststorepass "$KS_PASS" && \
      keytool -importcert -noprompt -alias uns-demo-ca -file /ca/ca.crt \
        -keystore broker-truststore.jks -storepass "$KS_PASS"'
fi

chmod 0640 "${TLS_DIR}"/*/fullchain.pem "${TLS_DIR}"/*/ca.pem 2>/dev/null || true
chmod 0600 "${TLS_DIR}"/*/privkey.pem "${BROKER_TLS_DIR}"/* 2>/dev/null || true
log "TLS material ready under ${TLS_DIR}"
