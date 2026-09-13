#!/usr/bin/env bash
# Shared helpers for AWS remote install scripts. Sourced, not executed.
set -euo pipefail

umask 077

log() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

# Prefer sudo docker when this login session is not yet in the docker group.
if ! docker info >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
  docker() { sudo docker "$@"; }
fi

rand_secret() {
  openssl rand -base64 24 | tr -d '\n=' | tr '/+' 'Aa'
}

ensure_dir() {
  mkdir -p "$1"
  chmod "$2" "$1" 2>/dev/null || true
}

yaml_scalar() {
  python3 - "$1" "$2" <<'PY'
import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
key = re.escape(sys.argv[2])
match = re.search(rf"(?m)^\s*{key}:\s*[\"']?([^\"'#\n]+?)[\"']?\s*(?:#.*)?$", text)
print(match.group(1).strip() if match else "")
PY
}

replace_in_file() {
  local file="$1"
  local from="$2"
  local to="$3"
  python3 - "$file" "$from" "$to" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
path.write_text(text.replace(sys.argv[2], sys.argv[3]), encoding="utf-8")
PY
}

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  python3 - "$file" "$key" "$value" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
key, value = sys.argv[2], sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
out = []
found = False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}
