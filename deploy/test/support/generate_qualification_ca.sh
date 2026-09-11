#!/bin/sh
# Generate qualification-only CA and TLS material for the acceptance harness.
set -eu

OUT="${1:-/qualification-ca}"
mkdir -p "${OUT}"

openssl genrsa -out "${OUT}/ca.key" 2048
openssl req -x509 -new -key "${OUT}/ca.key" -out "${OUT}/ca.crt" -days 365 \
  -subj "/CN=qualification-ca.uns/O=UNS Qualification"

openssl genrsa -out "${OUT}/server.key" 2048
openssl req -new -key "${OUT}/server.key" -out "${OUT}/server.csr" \
  -subj "/CN=cloud-management.qualification.uns/O=UNS Qualification"
openssl x509 -req -in "${OUT}/server.csr" -CA "${OUT}/ca.crt" -CAkey "${OUT}/ca.key" \
  -CAcreateserial -out "${OUT}/server.crt" -days 365

openssl genrsa -out "${OUT}/client.key" 2048
openssl req -new -key "${OUT}/client.key" -out "${OUT}/client.csr" \
  -subj "/CN=edge-agent.qualification.uns/O=UNS Qualification"
openssl x509 -req -in "${OUT}/client.csr" -CA "${OUT}/ca.crt" -CAkey "${OUT}/ca.key" \
  -CAcreateserial -out "${OUT}/client.crt" -days 365

chmod 600 "${OUT}/ca.key" "${OUT}/server.key" "${OUT}/client.key"
rm -f "${OUT}/server.csr" "${OUT}/client.csr"

echo "qualification CA material written to ${OUT}"
