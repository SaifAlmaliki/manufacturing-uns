#!/bin/sh
# Stateful qualification router rules for isolated cloud / DMZ / OT acceptance.
set -eu

STATE_FILE="/var/run/uns-firewall.ready"
COUNTERS_FILE="/var/run/uns-firewall.counters"

DMZ_MGMT_ADDR="${DMZ_MGMT_ADDR:-172.30.21.10}"
CLOUD_NET="${CLOUD_NET:-172.30.10.0/24}"
DMZ_NET="${DMZ_NET:-172.30.20.0/24}"
OT_NET="${OT_NET:-172.30.30.0/24}"
DMGMT_NET="${DMGMT_NET:-172.30.21.0/24}"

apply_rules() {
  iptables -F
  iptables -X 2>/dev/null || true
  iptables -t nat -F
  iptables -P INPUT ACCEPT
  iptables -P OUTPUT ACCEPT
  iptables -P FORWARD DROP

  iptables -N UNS_EDGE_ESTABLISHED 2>/dev/null || iptables -F UNS_EDGE_ESTABLISHED
  iptables -N UNS_CLOUD_TO_DMZ 2>/dev/null || iptables -F UNS_CLOUD_TO_DMZ
  iptables -N UNS_DMZ_TO_CLOUD 2>/dev/null || iptables -F UNS_DMZ_TO_CLOUD
  iptables -N UNS_DMZ_TO_OT 2>/dev/null || iptables -F UNS_DMZ_TO_OT
  iptables -N UNS_OT_TO_CLOUD 2>/dev/null || iptables -F UNS_OT_TO_CLOUD

  iptables -A UNS_EDGE_ESTABLISHED -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -A FORWARD -j UNS_EDGE_ESTABLISHED

  # Outbound-only cloud path: DMZ may initiate MQTT/HTTPS to cloud.
  iptables -A UNS_DMZ_TO_CLOUD -s "${DMZ_NET}" -d "${CLOUD_NET}" -p tcp -m multiport --dports 443,8883,1883,9092,9000 -j ACCEPT
  iptables -A FORWARD -s "${DMZ_NET}" -d "${CLOUD_NET}" -j UNS_DMZ_TO_CLOUD

  # OT protocol collection requires an explicit allow rule.
  iptables -A UNS_DMZ_TO_OT -s "${DMZ_NET}" -d "${OT_NET}" -p tcp -m multiport --dports 4840,1502,1883,8883 -j ACCEPT
  iptables -A FORWARD -s "${DMZ_NET}" -d "${OT_NET}" -j UNS_DMZ_TO_OT

  # Simulators must not reach cloud directly.
  iptables -A UNS_OT_TO_CLOUD -s "${OT_NET}" -d "${CLOUD_NET}" -j LOG --log-prefix "UNS_OT_TO_CLOUD_DENIED "
  iptables -A UNS_OT_TO_CLOUD -s "${OT_NET}" -d "${CLOUD_NET}" -j DROP
  iptables -A FORWARD -s "${OT_NET}" -d "${CLOUD_NET}" -j UNS_OT_TO_CLOUD

  # Cloud must not dial private DMZ management API.
  iptables -A UNS_CLOUD_TO_DMZ -s "${CLOUD_NET}" -d "${DMGMT_NET}" -p tcp --dport 8443 -j LOG --log-prefix "UNS_CLOUD_DMZ_MGMT_DENIED "
  iptables -A UNS_CLOUD_TO_DMZ -s "${CLOUD_NET}" -d "${DMGMT_NET}" -p tcp --dport 8443 -j DROP
  iptables -A UNS_CLOUD_TO_DMZ -s "${CLOUD_NET}" -d "${DMGMT_NET}" -j DROP
  iptables -A FORWARD -s "${CLOUD_NET}" -d "${DMGMT_NET}" -j UNS_CLOUD_TO_DMZ

  # Private management stays on dmgmt; agent and edge management only.
  iptables -A FORWARD -s "${DMGMT_NET}" -d "${DMGMT_NET}" -j ACCEPT

  date -Iseconds > "${STATE_FILE}"
  iptables -L -v -n -x > "${COUNTERS_FILE}"
}

case "${1:-apply}" in
  apply)
    apply_rules
    ;;
  counters)
    iptables -L -v -n -x
    echo "--- conntrack ---"
    conntrack -C 2>/dev/null || true
    ;;
  stats)
    iptables -L UNS_CLOUD_DMZ_MGMT_DENIED -v -n -x 2>/dev/null || true
    iptables -L UNS_DMZ_TO_CLOUD -v -n -x 2>/dev/null || true
    iptables -L UNS_EDGE_ESTABLISHED -v -n -x 2>/dev/null || true
    echo "--- conntrack ---"
    conntrack -C 2>/dev/null || true
    ;;
  block-cloud)
    iptables -I FORWARD 1 -s "${DMZ_NET}" -d "${CLOUD_NET}" -j DROP
    ;;
  restore-cloud)
    iptables -D FORWARD -s "${DMZ_NET}" -d "${CLOUD_NET}" -j DROP 2>/dev/null || true
    ;;
  *)
    echo "usage: $0 [apply|counters|stats|block-cloud|restore-cloud]" >&2
    exit 1
    ;;
esac
