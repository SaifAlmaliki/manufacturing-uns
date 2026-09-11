"""First-boot healthcheck windows for infra that `npm run stack` waits on.

Compose treats `unhealthy` as "failed to start" and leaves dependents in Created.
Docker marks unhealthy at start_period + retries * interval. Failures during
start_period do not consume retries — that is the knob for a slow first boot,
not a larger retry count that also delays detecting a crash after listen.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# Measured 2026-09-11 on Docker Desktop after `npm run stack --build` (~11 min
# image build, then every JVM/DB container starting at once):
#   uns_keycloak  listen ~271s (Quarkus augmentation 155s + H2 schema + realm import)
#   uns_neo4j_db  HTTP  ~263s (APOC plugin install + start)
# Both healthcheck budgets were 240s. Compose aborted at ~243s.
_SLOW_FIRST_BOOT = {
    "uns_keycloak": {"min_start_period": 240, "min_budget": 420},
    "uns_neo4j_db": {"min_start_period": 240, "min_budget": 360},
}


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))


def _seconds(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    total = 0
    for amount, unit in re.findall(r"(\d+)([hms])", text):
        total += int(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    if total == 0:
        raise AssertionError(f"unparsed duration: {value!r}")
    return total


def _budget(health: dict) -> int:
    start = _seconds(health.get("start_period", 0))
    interval = _seconds(health.get("interval", "30s"))
    retries = int(health.get("retries", 3))
    return start + retries * interval


def test_slow_infra_healthchecks_survive_first_boot_after_image_build():
    compose = _compose()
    for name, floors in _SLOW_FIRST_BOOT.items():
        health = compose["services"][name]["healthcheck"]
        start = _seconds(health.get("start_period", 0))
        budget = _budget(health)
        assert start >= floors["min_start_period"], (
            f"{name} start_period {start}s is shorter than a contended first boot; "
            "failures during startup consume retries and abort npm run stack"
        )
        assert budget >= floors["min_budget"], (
            f"{name} healthcheck budget {budget}s is shorter than {floors['min_budget']}s"
        )
