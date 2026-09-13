#!/usr/bin/env bash
# Prepare /opt/uns/deploy/cloud settings, secrets, Keycloak realm, and TLS.
set -euo pipefail
# shellcheck source=common.sh
. "$(cd "$(dirname "$0")" && pwd)/common.sh"

REPO_ROOT="${UNS_REPO_ROOT:?UNS_REPO_ROOT is required}"
BUNDLE_DIR="${UNS_CLOUD_BUNDLE:-${REPO_ROOT}/deploy/cloud}"
CONSOLE_HOST="${UNS_CONSOLE_HOST:?}"
ENROLL_HOST="${UNS_ENROLL_HOST:?}"
MGMT_HOST="${UNS_MGMT_HOST:?}"
MQTT_HOST="${UNS_MQTT_HOST:?}"
PUBLICATIONS_HOST="${UNS_PUBLICATIONS_HOST:-publications.${CONSOLE_HOST#uns.}}"
PUBLIC_ORIGIN="https://${CONSOLE_HOST}"
AWS_REGION="${UNS_AWS_REGION:-eu-central-1}"
S3_BUCKET="${UNS_S3_LAKE_BUCKET:-uns-historic-events}"
TLS_MODE="${UNS_TLS_MODE:-demo}"

require_cmd python3
require_cmd openssl
require_cmd docker

ensure_dir "${BUNDLE_DIR}/secrets" 0750
ensure_dir "${BUNDLE_DIR}/keycloak" 0750

if [[ ! -f "${BUNDLE_DIR}/settings.yaml" ]]; then
  cp "${BUNDLE_DIR}/settings.yaml.example" "${BUNDLE_DIR}/settings.yaml"
fi

EXAMPLE_PUBLIC_HOST="$(yaml_scalar "${BUNDLE_DIR}/settings.yaml" example_public_host)"
EXAMPLE_PUBLIC_HOST="${EXAMPLE_PUBLIC_HOST:-iip.example.com}"
PRODUCT_NAME="$(yaml_scalar "${BUNDLE_DIR}/settings.yaml" product_name)"
PRODUCT_NAME="${PRODUCT_NAME:-Industrial Intelligence Platform}"

replace_in_file "${BUNDLE_DIR}/settings.yaml" "enroll.${EXAMPLE_PUBLIC_HOST}" "${ENROLL_HOST}"
replace_in_file "${BUNDLE_DIR}/settings.yaml" "edge-mgmt.${EXAMPLE_PUBLIC_HOST}" "${MGMT_HOST}"
replace_in_file "${BUNDLE_DIR}/settings.yaml" "mqtt.${EXAMPLE_PUBLIC_HOST}" "${MQTT_HOST}"
replace_in_file "${BUNDLE_DIR}/settings.yaml" "https://${EXAMPLE_PUBLIC_HOST}" "${PUBLIC_ORIGIN}"
replace_in_file "${BUNDLE_DIR}/settings.yaml" "${EXAMPLE_PUBLIC_HOST}" "${CONSOLE_HOST}"
replace_in_file "${BUNDLE_DIR}/settings.yaml" "eu-central-1" "${AWS_REGION}"
replace_in_file "${BUNDLE_DIR}/settings.yaml" "uns-historic-events" "${S3_BUCKET}"

# Frontend bakes conf/settings.yaml at image build time.
cp "${BUNDLE_DIR}/settings.yaml" "${REPO_ROOT}/conf/settings.yaml"

python3 - "${REPO_ROOT}/conf/keycloak/realm.json" "${BUNDLE_DIR}/keycloak/realm.json" "${PUBLIC_ORIGIN}" "${PRODUCT_NAME}" <<'PY'
import json, pathlib, sys
src, dest, origin, product_name = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
doc = json.loads(src.read_text(encoding="utf-8"))
doc["sslRequired"] = "external"
doc["displayName"] = product_name
for client in doc.get("clients", []):
    cid = client.get("clientId")
    if cid == "uns-console":
        client["redirectUris"] = [f"{origin}/*"]
        client["webOrigins"] = [origin]
        client.setdefault("attributes", {})["post.logout.redirect.uris"] = f"{origin}/*"
    elif cid == "uns-grafana":
        client["redirectUris"] = [f"{origin}/grafana/login/generic_oauth"]
        client["webOrigins"] = [origin]
dest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY

if [[ ! -f "${BUNDLE_DIR}/secrets/runtime.env" ]]; then
  cp "${BUNDLE_DIR}/secrets/runtime.env.example" "${BUNDLE_DIR}/secrets/runtime.env"
fi

# Generate missing secrets without clobbering operator-supplied values.
for key in \
  UNS_keycloak__admin_password \
  UNS_KEYCLOAK_ADMIN_PASSWORD \
  UNS_keycloak__db_password \
  UNS_keycloak__grafana_client_secret \
  UNS_KEYCLOAK_GRAFANA_CLIENT_SECRET \
  PGPASSWORD \
  UNS_graphdb__password \
  UNS_historian__password
do
  current="$(grep -E "^${key}=" "${BUNDLE_DIR}/secrets/runtime.env" | cut -d= -f2- || true)"
  if [[ -z "${current}" ]]; then
    set_env_value "${BUNDLE_DIR}/secrets/runtime.env" "${key}" "$(rand_secret)"
  fi
done

set_env_value "${BUNDLE_DIR}/secrets/runtime.env" "UNS_CONSOLE_ORIGIN" "${PUBLIC_ORIGIN}"
set_env_value "${BUNDLE_DIR}/secrets/runtime.env" "AWS_DEFAULT_REGION" "${AWS_REGION}"
set_env_value "${BUNDLE_DIR}/secrets/runtime.env" "UNS_datalake__s3__region" "${AWS_REGION}"
set_env_value "${BUNDLE_DIR}/secrets/runtime.env" "UNS_datalake__s3__bucket" "${S3_BUCKET}"
set_env_value "${BUNDLE_DIR}/secrets/runtime.env" "UNS_datalake__s3__endpoint_url" "https://s3.${AWS_REGION}.amazonaws.com"

# Keep Keycloak admin password aliases aligned.
admin_pw="$(grep -E '^UNS_keycloak__admin_password=' "${BUNDLE_DIR}/secrets/runtime.env" | cut -d= -f2-)"
set_env_value "${BUNDLE_DIR}/secrets/runtime.env" "UNS_KEYCLOAK_ADMIN_PASSWORD" "${admin_pw}"
grafana_secret="$(grep -E '^UNS_keycloak__grafana_client_secret=' "${BUNDLE_DIR}/secrets/runtime.env" | cut -d= -f2-)"
set_env_value "${BUNDLE_DIR}/secrets/runtime.env" "UNS_KEYCLOAK_GRAFANA_CLIENT_SECRET" "${grafana_secret}"

if [[ ! -f "${BUNDLE_DIR}/secrets/backup.env" ]]; then
  cp "${BUNDLE_DIR}/secrets/backup.env.example" "${BUNDLE_DIR}/secrets/backup.env"
fi

replace_in_file "${BUNDLE_DIR}/proxy/nginx.conf" "enroll.${EXAMPLE_PUBLIC_HOST}" "${ENROLL_HOST}"
replace_in_file "${BUNDLE_DIR}/proxy/nginx.conf" "edge-mgmt.${EXAMPLE_PUBLIC_HOST}" "${MGMT_HOST}"
replace_in_file "${BUNDLE_DIR}/proxy/nginx.conf" "publications.${EXAMPLE_PUBLIC_HOST}" "${PUBLICATIONS_HOST}"
replace_in_file "${BUNDLE_DIR}/proxy/nginx.conf" "${EXAMPLE_PUBLIC_HOST}" "${CONSOLE_HOST}"

case "${TLS_MODE}" in
  demo)
    UNS_CLOUD_BUNDLE="${BUNDLE_DIR}" \
      UNS_CONSOLE_HOST="${CONSOLE_HOST}" \
      UNS_ENROLL_HOST="${ENROLL_HOST}" \
      UNS_MGMT_HOST="${MGMT_HOST}" \
      UNS_MQTT_HOST="${MQTT_HOST}" \
      UNS_PUBLICATIONS_HOST="${PUBLICATIONS_HOST}" \
      bash "$(cd "$(dirname "$0")" && pwd)/make-tls-material.sh"
    ;;
  letsencrypt)
    require_cmd certbot
    log "Requesting Let's Encrypt certificates (ports 80/443 must be free)"
    certbot certonly --standalone --non-interactive --agree-tos \
      --email "${UNS_LETSENCRYPT_EMAIL:?UNS_LETSENCRYPT_EMAIL is required for letsencrypt}" \
      -d "${CONSOLE_HOST}" -d "${ENROLL_HOST}" -d "${MGMT_HOST}" \
      -d "${MQTT_HOST}" -d "${PUBLICATIONS_HOST}"
    LIVE="/etc/letsencrypt/live/${CONSOLE_HOST}"
    for name in console enrollment management publications mqtt; do
      ensure_dir "${BUNDLE_DIR}/secrets/tls/${name}" 0750
      cp "${LIVE}/fullchain.pem" "${BUNDLE_DIR}/secrets/tls/${name}/fullchain.pem"
      cp "${LIVE}/privkey.pem" "${BUNDLE_DIR}/secrets/tls/${name}/privkey.pem"
      cp "${LIVE}/chain.pem" "${BUNDLE_DIR}/secrets/tls/${name}/ca.pem" 2>/dev/null \
        || cp "${LIVE}/fullchain.pem" "${BUNDLE_DIR}/secrets/tls/${name}/ca.pem"
    done
    UNS_CLOUD_BUNDLE="${BUNDLE_DIR}" \
      UNS_CONSOLE_HOST="${CONSOLE_HOST}" \
      UNS_ENROLL_HOST="${ENROLL_HOST}" \
      UNS_MGMT_HOST="${MGMT_HOST}" \
      UNS_MQTT_HOST="${MQTT_HOST}" \
      UNS_PUBLICATIONS_HOST="${PUBLICATIONS_HOST}" \
      bash "$(cd "$(dirname "$0")" && pwd)/make-tls-material.sh"
    ;;
  existing)
    log "Using operator-supplied TLS files already under ${BUNDLE_DIR}/secrets/tls"
    ;;
  *)
    die "Unknown UNS_TLS_MODE=${TLS_MODE} (demo|letsencrypt|existing)"
    ;;
esac

chmod 0600 "${BUNDLE_DIR}/secrets/runtime.env" "${BUNDLE_DIR}/secrets/backup.env"
log "Cloud host prepared at ${BUNDLE_DIR}"
log "Keycloak admin user is cloud-admin; password is in secrets/runtime.env (UNS_keycloak__admin_password)"
