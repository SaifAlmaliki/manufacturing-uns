"""Read `conf/oee/*.yaml` into a plan, then apply the plan.

Split for the same reason as `seed.py`: planning is a pure function of a mapping, so every
validation error is reachable from a unit test with no database and no files, and
`--dry-run` prints exactly what the write would do.

Not routed through `uns_config.get_settings()`: that hardcodes
`settings_files=["settings.yaml", ".secrets.yaml"]` for all modules, so widening it for the
OEE module's benefit would change config loading platform-wide.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any

import yaml
from uns_config import resolve_conf_dir

from uns_model.oee_master_data import (
    DowntimeReasonSpec,
    IdealCycleTimeSpec,
    OeeMasterDataRepository,
    OeeUnitSpec,
    ProductSpec,
    ShiftExceptionSpec,
    ShiftPatternSpec,
    ShiftSlotSpec,
    StateReasonRuleSpec,
)
from uns_model.oee_tables import DEFAULT_PRODUCING_STATES

LOGGER = logging.getLogger(__name__)

OEE_CONF_SUBDIR = "oee"
OEE_CONF_FILES = ("products", "shifts", "units", "reasons")


@dataclass(slots=True)
class OeeSeedPlan:
    """Everything an import would write, before anything is written."""

    products: list[ProductSpec] = field(default_factory=list)
    reasons: list[DowntimeReasonSpec] = field(default_factory=list)
    patterns: list[ShiftPatternSpec] = field(default_factory=list)
    exceptions: list[ShiftExceptionSpec] = field(default_factory=list)
    units: list[OeeUnitSpec] = field(default_factory=list)
    cycle_times: list[IdealCycleTimeSpec] = field(default_factory=list)
    state_reason_rules: list[StateReasonRuleSpec] = field(default_factory=list)
    present_files: frozenset[str] = field(default_factory=frozenset)

    def describe(self) -> str:
        """The plan as text, for `--dry-run`."""
        lines: list[str] = ["Products:"]
        lines += [f"  {spec.code}  {spec.name}" for spec in self.products]
        lines.append("Downtime reasons:")
        lines += [
            f"  {spec.code}  {'planned' if spec.is_planned else 'unplanned'}  {spec.display_name}" for spec in self.reasons
        ]
        lines.append("Shift patterns:")
        for spec in self.patterns:
            lines.append(f"  {spec.name}  [{spec.timezone}]  {len(spec.slots)} slot(s)")
            lines += [
                f"    day {slot.day_of_week} {slot.start_time} +{slot.duration_minutes}m  {slot.label}" for slot in spec.slots
            ]
        lines.append("Shift exceptions:")
        lines += [
            f"  {spec.kind}  {spec.starts_at} .. {spec.ends_at}  {spec.asset_path or '(all Assets)'}  {spec.note}"
            for spec in self.exceptions
        ]
        lines.append("OEE units:")
        for spec in self.units:
            lines.append(f"  {spec.asset_path}  pattern={spec.shift_pattern_name}")
            lines.append(f"    state      {spec.state_metric_key}")
            lines.append(f"    good       {spec.good_count_metric_key}")
            lines.append(f"    reject     {spec.reject_count_metric_key or '(none)'}")
            lines.append(f"    product    {spec.product_metric_key or '(single product)'}")
            lines.append(f"    producing  {', '.join(spec.producing_states)}")
        lines.append("Ideal cycle times:")
        lines += [
            f"  {spec.asset_path}  {spec.product_code or '(any product)'}  {spec.seconds_per_unit}s/unit"
            for spec in self.cycle_times
        ]
        lines.append("State reason rules:")
        lines += [
            f"  {spec.state_value} -> {spec.reason_code}  {spec.asset_path or '(all units)'}"
            for spec in self.state_reason_rules
        ]
        return "\n".join(lines)


def _read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{path.name}: expected a YAML mapping at the top level, got {type(loaded).__name__}")
    return dict(loaded)


def read_oee_conf(conf_dir: Path | None = None) -> dict[str, Any]:
    """Read `conf/oee/*.yaml` into the mapping `plan_from_oee_config` consumes.

    Absent files are skipped rather than defaulted, so a deployment can land `shifts.yaml`
    before reason codes. `apply_plan` reconciles only collections whose file was present: a
    missing file leaves existing rows alone, while a present file with an empty list is the
    source of truth and wipes that collection.
    """
    directory = (conf_dir if conf_dir is not None else resolve_conf_dir()) / OEE_CONF_SUBDIR
    raw: dict[str, Any] = {}
    for name in OEE_CONF_FILES:
        if (document := _read_yaml_mapping(directory / f"{name}.yaml")) is not None:
            raw[name] = document
    LOGGER.info("Read OEE configuration from %s: %s", directory, ", ".join(sorted(raw)) or "nothing")
    return raw


def _section(config: Mapping[str, Any], file: str, key: str) -> list[Mapping[str, Any]]:
    document = config.get(file) or {}
    entries = document.get(key) or []
    if not isinstance(entries, Sequence) or isinstance(entries, str):
        raise ValueError(f"{file}.yaml: '{key}' must be a list, got {type(entries).__name__}")
    return [dict(entry) for entry in entries]


def _parse_time(raw: Any, where: str) -> time:
    """Accept both a YAML time and a 'HH:MM' string.

    PyYAML turns an unquoted 06:00 into the integer 360 (sexagesimal), so a bare number is
    an authoring mistake worth naming rather than silently accepting.
    """
    if isinstance(raw, time):
        return raw
    if isinstance(raw, str):
        return time.fromisoformat(raw)
    raise ValueError(f"{where}: 'start' must be a quoted 'HH:MM' string, got {raw!r}")


def _parse_datetime(raw: Any, where: str) -> datetime:
    value = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if value.tzinfo is None:
        raise ValueError(f"{where}: timestamp {raw!r} has no timezone offset")
    return value


def _pattern_spec_from_entry(entry: Mapping[str, Any]) -> ShiftPatternSpec:
    """Expand one `shifts.yaml` pattern, including one slot per named weekday."""
    name = str(entry["name"])
    slots: list[ShiftSlotSpec] = []
    for raw_slot in entry.get("slots") or []:
        start = _parse_time(raw_slot.get("start"), f"shifts.yaml pattern {name!r}")
        slots.extend(
            ShiftSlotSpec(
                day_of_week=int(day),
                start_time=start,
                duration_minutes=int(raw_slot["duration_minutes"]),
                label=str(raw_slot.get("label", "")),
            )
            for day in raw_slot.get("days") or []
        )
    return ShiftPatternSpec(
        name=name,
        timezone=str(entry.get("timezone", "UTC")),
        asset_path=entry.get("asset"),
        slots=tuple(slots),
    )


def plan_from_oee_config(config: Mapping[str, Any]) -> OeeSeedPlan:
    """Turn the `conf/oee/` mapping into a plan, validating every cross-reference."""
    plan = OeeSeedPlan(present_files=frozenset(config.keys()))

    for entry in _section(config, "products", "products"):
        plan.products.append(ProductSpec(code=str(entry["code"]), name=str(entry.get("name", ""))))

    for entry in _section(config, "reasons", "reasons"):
        plan.reasons.append(
            DowntimeReasonSpec(
                code=str(entry["code"]),
                display_name=str(entry.get("display_name", entry["code"])),
                category=str(entry.get("category", "")),
                is_planned=bool(entry.get("is_planned", False)),
            )
        )

    for entry in _section(config, "shifts", "patterns"):
        plan.patterns.append(_pattern_spec_from_entry(entry))

    for entry in _section(config, "shifts", "exceptions"):
        plan.exceptions.append(
            ShiftExceptionSpec(
                starts_at=_parse_datetime(entry["starts_at"], "shifts.yaml exception"),
                ends_at=_parse_datetime(entry["ends_at"], "shifts.yaml exception"),
                kind=str(entry.get("kind", "PLANNED_DOWN")),
                asset_path=entry.get("asset"),
                note=str(entry.get("note", "")),
            )
        )

    pattern_names = {spec.name for spec in plan.patterns}
    product_codes = {spec.code for spec in plan.products}
    producing_states: set[str] = set()

    for entry in _section(config, "units", "units"):
        asset_path = str(entry["asset"])
        pattern_name = str(entry["shift_pattern"])
        if pattern_name not in pattern_names:
            raise ValueError(
                f"units.yaml: unit {asset_path!r} names shift pattern {pattern_name!r}, which shifts.yaml does not define"
            )
        states = tuple(str(state) for state in entry.get("producing_states") or DEFAULT_PRODUCING_STATES)
        producing_states.update(states)
        plan.units.append(
            OeeUnitSpec(
                asset_path=asset_path,
                shift_pattern_name=pattern_name,
                state_metric_key=str(entry["state_metric_key"]),
                good_count_metric_key=str(entry["good_count_metric_key"]),
                reject_count_metric_key=entry.get("reject_count_metric_key"),
                product_metric_key=entry.get("product_metric_key"),
                producing_states=states,
            )
        )
        for raw_cycle in entry.get("ideal_cycle_times") or []:
            product_code = raw_cycle.get("product")
            if product_code is not None and str(product_code) not in product_codes:
                raise ValueError(
                    f"units.yaml: ideal cycle time on {asset_path!r} names product "
                    f"{product_code!r}, which products.yaml does not define"
                )
            plan.cycle_times.append(
                IdealCycleTimeSpec(
                    asset_path=asset_path,
                    seconds_per_unit=float(raw_cycle["seconds_per_unit"]),
                    product_code=None if product_code is None else str(product_code),
                )
            )

    reason_codes = {spec.code for spec in plan.reasons}
    for entry in _section(config, "reasons", "state_rules"):
        state_value = str(entry["state"])
        if state_value in producing_states:
            raise ValueError(
                f"reasons.yaml: {state_value!r} is a producing state, so it can never be a stop "
                f"and must not have a reason rule"
            )
        plan.state_reason_rules.append(
            StateReasonRuleSpec(
                state_value=state_value,
                reason_code=str(entry["reason"]),
                asset_path=entry.get("asset"),
            )
        )
        LOGGER.debug("state rule %s -> %s", state_value, entry["reason"])

    for spec in (
        *plan.products,
        *plan.reasons,
        *plan.patterns,
        *plan.exceptions,
        *plan.units,
        *plan.cycle_times,
        *plan.state_reason_rules,
    ):
        spec.validate()

    # Reason codes not declared here may still be seeded by migration 0003, so an unknown
    # code is a warning at plan time and a foreign-key error at write time - which names
    # the offending code either way.
    for rule in plan.state_reason_rules:
        if rule.reason_code not in reason_codes:
            LOGGER.info(
                "state rule %s -> %s relies on a reason code seeded by migration 0003",
                rule.state_value,
                rule.reason_code,
            )
    return plan


async def apply_plan(repository: OeeMasterDataRepository, plan: OeeSeedPlan) -> dict[str, int]:
    """Write a plan to the OEE master data.

    Order matters: products before their cycle times, patterns before the units that name
    them, units before the unit-scoped reason rules, reasons before the rules that
    reference them. Reconcile runs only for files in `plan.present_files`, so a missing
    YAML file leaves that collection alone.
    """
    for product in plan.products:
        await repository.save_product(product)
    for reason in plan.reasons:
        await repository.save_downtime_reason(reason)
    for pattern in plan.patterns:
        await repository.save_shift_pattern(pattern)
    for exception in plan.exceptions:
        await repository.save_shift_exception(exception)
    for unit in plan.units:
        await repository.save_oee_unit(unit)
    for cycle_time in plan.cycle_times:
        await repository.save_ideal_cycle_time(cycle_time)
    for rule in plan.state_reason_rules:
        await repository.save_state_reason_rule(rule)
    present = plan.present_files
    if "products" in present:
        await repository.reconcile_products(plan.products)
    if "shifts" in present:
        await repository.reconcile_shift_patterns(plan.patterns)
        await repository.reconcile_shift_exceptions(plan.exceptions)
    if "units" in present:
        await repository.reconcile_oee_units(plan.units)
        await repository.reconcile_ideal_cycle_times(plan.cycle_times)
    if "reasons" in present:
        await repository.reconcile_state_reason_rules(plan.state_reason_rules)
    return {
        "products": len(plan.products),
        "downtime_reasons": len(plan.reasons),
        "shift_patterns": len(plan.patterns),
        "shift_exceptions": len(plan.exceptions),
        "oee_units": len(plan.units),
        "ideal_cycle_times": len(plan.cycle_times),
        "state_reason_rules": len(plan.state_reason_rules),
    }


__all__ = ["OeeSeedPlan", "apply_plan", "plan_from_oee_config", "read_oee_conf"]
