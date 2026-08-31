#!/bin/sh
set -eu

mkdir -p /etc/grafana/provisioning/datasources
envsubst '${UNS_HISTORIAN_PASSWORD}' \
  < /etc/grafana/provisioning/datasources/datasources.yaml.template \
  > /etc/grafana/provisioning/datasources/datasources.yaml

exec /run.sh
