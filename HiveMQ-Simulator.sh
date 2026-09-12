#!/usr/bin/env bash
# OEE demo plant publisher for local stack development.
# Host:   npm run simulator   (or ./HiveMQ-Simulator.sh via Git Bash)
# Stack:  npm run simulator:stack   (compose profile oee-demo)
H=${H:-localhost}; P=${P:-1883}; TICK=${TICK:-3}; DEV=${DEV:-40}
Q="-q 1 -r"; B=${B:-DemoCorp/Site01/Production}
WARM=${WARM:-600}; DECL=${DECL:-300}; LOW=${LOW:-90}; REC=${REC:-30}; HEAL=${HEAL:-120}
MQTT_CLI_IMAGE=${MQTT_CLI_IMAGE:-hivemq/mqtt-cli:4.33.0}
CLIENT_ID_PREFIX=${CLIENT_ID_PREFIX:-mqtt_oee_demo}
MQTT_TLS=${MQTT_TLS:-0}
MQTT_TLS_VERIFY=${MQTT_TLS_VERIFY:-1}
MQTT_CA_FILE=${MQTT_CA_FILE:-}
MQTT_CERT_FILE=${MQTT_CERT_FILE:-}
MQTT_KEY_FILE=${MQTT_KEY_FILE:-}
MQTT_USERNAME=${MQTT_USERNAME:-}
MQTT_PASSWORD=${MQTT_PASSWORD:-}
MQTT_CREDENTIALS_FILE=${MQTT_CREDENTIALS_FILE:-}
MQTT_TLS_CONFIG_FILE=${MQTT_TLS_CONFIG_FILE:-}
ACCEPTANCE_MODE=${ACCEPTANCE_MODE:-0}
MALFORMED_MODE=${MALFORMED_MODE:-0}
RUN_ID=${RUN_ID:-}
SEED=${SEED:-0}
CASE_COUNT=${CASE_COUNT:-2}
IDENTITY_FILE=${IDENTITY_FILE:-/tmp/uns_oee_identity.env}

_load_secret_file() {
  file="$1"
  [ -f "$file" ] || return 0
  # shellcheck disable=SC1090
  set -a; . "$file"; set +a
}

_load_secret_file "$MQTT_CREDENTIALS_FILE"
_load_secret_file "$MQTT_TLS_CONFIG_FILE"

if [ "$H" = "localhost" ] && command -v docker >/dev/null 2>&1; then
  if docker ps --filter "publish=1883" --format '{{.Names}}' | head -n1 | grep -q .; then
    H=uns_mqtt_broker
  fi
fi

mqttcli() {
  if [ -d /app/classpath ]; then
    java -cp "/app/classpath/*:/app/libs/*" com.hivemq.cli.MqttCLIMain "$@"
    return
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "mqtt-cli: docker not available (start the stack or use npm run simulator:stack)" >&2
    exit 127
  fi
  broker="${MQTT_BROKER_CONTAINER:-}"
  if [ -z "$broker" ]; then
    broker=$(docker ps --filter "publish=1883" --format '{{.Names}}' | head -n1)
  fi
  if [ -z "$broker" ]; then
    echo "mqtt-cli: no MQTT broker container found (start the stack or set MQTT_BROKER_CONTAINER)" >&2
    exit 127
  fi
  network="${MQTT_DOCKER_NETWORK:-}"
  if [ -z "$network" ]; then
    network=$(docker inspect "$broker" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | head -n1)
  fi
  MSYS_NO_PATHCONV=1 docker run --rm -i --network "$network" "$MQTT_CLI_IMAGE" "$@"
}

_connect_args() {
  client_id="${CLIENT_ID_PREFIX}-$(date +%s)"
  if [ -f "$IDENTITY_FILE" ]; then
    # shellcheck disable=SC1090
    . "$IDENTITY_FILE"
    [ -n "${BOOT_ID:-}" ] && client_id="${CLIENT_ID_PREFIX}-${BOOT_ID}"
    [ -n "${SEQUENCE:-}" ] && START_SEQUENCE="$SEQUENCE"
  else
    BOOT_ID=$(date +%s)
    START_SEQUENCE=0
    mkdir -p "$(dirname "$IDENTITY_FILE")"
    printf 'BOOT_ID=%s\nSEQUENCE=%s\n' "$BOOT_ID" "$START_SEQUENCE" >"$IDENTITY_FILE"
  fi
  args="con -i $client_id -h $H -p $P"
  if [ "$MQTT_TLS" = "1" ]; then
    args="$args --tls"
    [ -n "$MQTT_CA_FILE" ] && args="$args --cafile $MQTT_CA_FILE"
    [ -n "$MQTT_CERT_FILE" ] && args="$args --cert $MQTT_CERT_FILE"
    [ -n "$MQTT_KEY_FILE" ] && args="$args --key $MQTT_KEY_FILE"
    if [ "$MQTT_TLS_VERIFY" != "1" ]; then
      args="$args --insecure"
    fi
  fi
  if [ -n "$MQTT_USERNAME" ]; then
    args="$args -u $MQTT_USERNAME -pw:env MQTT_PASSWORD"
  fi
  echo "$args"
}

n() { v=$(($1 + RANDOM % ($2 - $1 + 1))); printf "%d.%03d" $((v / 1000)) $((v % 1000)); }
pct() { printf "%d.%d" $(($1 / 10)) $(($1 % 10)); }
dec() { printf "0.%03d" $1; }
p() {
  case $1 in kpi/*) m=$2; j=0;; *) m="{\"value\":$2,\"timestamp\":\"$T\"}"; j=1;; esac
  if [ "$MALFORMED_MODE" = "1" ] && [ "$1" = "raw/machine_state" ]; then
    m='{"value":broken'
    echo "  malformed payload -> $M/$1 $m" >&2
    echo "pub -t $B/$M/$1 $3 -m $m"
    return
  fi
  case $2 in \"*) ;; *)
    if [ "$ACCEPTANCE_MODE" != "1" ] && [ $((RANDOM % DEV)) -eq 0 ]; then
      case $2 in *.*) k=$((RANDOM % (j + 2)));; *) k=$((RANDOM % (j + 1)));; esac
      if [ $j = 0 ]; then
        case $k in 0) m=null;; *) m=${2/./,};; esac
      else
        case $k in
          0) m="{\"value\":null,\"timestamp\":\"$T\"}";;
          1) m="{\"value\":$2}";;
          *) m="{\"value\":${2/./,},\"timestamp\":\"$T\"}";;
        esac
      fi
      echo "  deviating payload -> $M/$1 $m" >&2
    fi;;
  esac
  echo "pub -t $B/$M/$1 $3 -m $m"
}

ctx() { M=$2/$1; echo "pub -t $B/$M/context $Q -m {\"machine_type\":\"$3\",\"asset_id\":\"$4\",\"ideal_cycle_time_sec\":$5,\"rated_capacity_units_per_hour\":$6,\"planned_production_time_min\":480}"; }

raw() {
  M=$2/$1; s=running; d=none; u=good
  if [ "$ACCEPTANCE_MODE" = "1" ]; then
    s=running; d=none; u=good
  elif [ $((RANDOM % 1000)) -ge $5 ]; then
    s=stopped; [ $((RANDOM % 3)) -eq 0 ] && s=idle
  fi
  if [ $s = running ]; then
    [ "$ACCEPTANCE_MODE" != "1" ] && [ $((RANDOM % 20)) -eq 0 ] && u=reject
    eval "c_$1=\$((c_$1 + 1))"
  else
    u=none
    case $((RANDOM % 4)) in 0) d=changeover;; 1) d=breakdown;; 2) d=minor_stop;; *) d=no_material;; esac
  fi
  eval "c=\$c_$1"
  p raw/machine_state "\"$s\""
  p raw/downtime_reason "\"$d\""
  p raw/unit_result "\"$u\""
  p raw/units_produced_total $c
  p raw/actual_cycle_time_sec $(n $(($3 - 600)) $(($3 + 600)))
  p raw/throughput_units_per_min $(n $(($4 - 2500)) $(($4 + 2500)))
}

kpi() {
  M=$2/$1; a=$4; pf=$((940 + RANDOM % 21)); ql=$((975 + RANDOM % 11))
  [ $a -gt 995 ] && a=995
  if [ $3 = pct ]; then
    p kpi/availability $(pct $a) "$Q"; p kpi/performance $(pct $pf) "$Q"; p kpi/quality $(pct $ql) "$Q"
  else
    p kpi/availability $(dec $a) "$Q"; p kpi/performance $(dec $pf) "$Q"; p kpi/quality $(dec $ql) "$Q"
  fi
}

c_Filler01=0; c_Capper01=0; c_Mixer01=0; c_Packer01=0; i=0; ph=; START=$(date +%s)
CYCLE=$((DECL + LOW + REC + HEAL))
echo "40 topics under $B/#  |  Ctrl+C to stop"
if [ "$ACCEPTANCE_MODE" = "1" ]; then
  echo "acceptance mode run_id=${RUN_ID:-unset} seed=${SEED} cases=${CASE_COUNT}"
fi
{
  echo "$(_connect_args)"
  ctx Filler01 LineA Filler AST-1001 3.5 1029
  ctx Capper01 LineA Capper AST-1002 3.0 1200
  ctx Mixer01 LineB Mixer AST-2001 5.0 720
  ctx Packer01 LineB Packer AST-2002 4.0 900
  if [ "$ACCEPTANCE_MODE" = "1" ]; then
    RANDOM=$SEED
    case_i=0
    while [ "$case_i" -lt "$CASE_COUNT" ]; do
      T=$(date -u +%FT%TZ)
      raw Filler01 LineA 3500 17100 930
      raw Capper01 LineA 3000 20000 930
      raw Mixer01 LineB 5000 12000 930
      raw Packer01 LineB 4000 15000 950
      kpi Filler01 LineA pct 900
      case_i=$((case_i + 1))
      SEQUENCE=$((START_SEQUENCE + case_i))
      printf 'BOOT_ID=%s\nSEQUENCE=%s\n' "$BOOT_ID" "$SEQUENCE" >"$IDENTITY_FILE"
      sleep "$TICK"
    done
    exit 0
  fi
  while :; do
    T=$(date -u +%FT%TZ); S=$(($(date +%s) - START))
    if [ $S -lt $WARM ]; then o=900; x=warm-up
    else
      c=$(((S - WARM) % CYCLE))
      if [ $c -lt $DECL ]; then o=$((900 - 100 * c / DECL)); x=DECLINING
      elif [ $c -lt $((DECL + LOW)) ]; then o=800; x="at 80% — agent should have alerted"
      elif [ $c -lt $((DECL + LOW + REC)) ]; then o=$((800 + 100 * (c - DECL - LOW) / REC)); x=recovering
      else o=900; x=healthy
      fi
    fi
    [ "$x" != "$ph" ] && { echo "  [$((S / 60))m$((S % 60))s] Filler01 $x, OEE $((o / 10))%" >&2; ph=$x; }
    a=$((o * 1000000 / 931000))
    raw Filler01 LineA 3500 17100 $a
    raw Capper01 LineA 3000 20000 930
    raw Mixer01 LineB 5000 12000 930
    raw Packer01 LineB 4000 15000 950
    i=$((i + 1))
    if [ $((i % 5)) -eq 0 ]; then
      kpi Filler01 LineA pct $a
      kpi Capper01 LineA dec $((925 + RANDOM % 30))
      kpi Mixer01 LineB dec $((925 + RANDOM % 30))
      kpi Packer01 LineB dec $((955 + RANDOM % 25))
    fi
    sleep $TICK
  done
} | mqttcli shell > /dev/null
