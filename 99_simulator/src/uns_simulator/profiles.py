"""Turn conf/simulator/*.yaml into DeviceSpec objects.

A device template says what a device is and, through `target`, where it belongs. Without
`target` the simulator could only do a cartesian product of templates and cells, which is
why it could never have had a compressor house and a filling line at the same time.

Every failure in this module names the offending key. A profile that silently produces the
wrong device inventory is far more expensive to debug than one that refuses to load.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml
from uns_config import resolve_conf_dir

from uns_simulator.models import ISA95Hierarchy, expand_hierarchy_paths
from uns_simulator.plant import PlantContext
from uns_simulator.signals import SignalSpec, order_signals, spec_from_config

LOGGER = logging.getLogger(__name__)

TARGET_KEYS = frozenset({"site", "area", "line", "cell", "kind"})


@dataclass(frozen=True)
class DeviceSpec:
    """One resolved device: a location, a signal set, and the lines it serves."""

    id: str
    equipment: str
    family: str
    tier: str
    path: ISA95Hierarchy
    signals: tuple[SignalSpec, ...]
    serves: tuple[str, ...] = ()
    enabled: bool = True

    @property
    def topic_prefix(self) -> str:
        return "/".join((self.path.enterprise, self.path.site, self.path.area, self.path.line, self.path.cell, self.equipment))


def matches_target(path: ISA95Hierarchy, target: Mapping[str, Any] | None) -> bool:
    """Does `path` satisfy `target`?

    `None` means production areas only - the implicit meaning of today's templates, kept so
    existing configuration behaves the same. `{}` means everywhere, utilities included.
    Every key present must match; a key absent is a wildcard. Values may be a string or a
    list of strings.
    """
    if target is None:
        return path.kind == "production"
    if unknown := set(target) - TARGET_KEYS:
        allowed = ", ".join(sorted(TARGET_KEYS))
        raise ValueError(f"unknown target selector(s): {', '.join(sorted(unknown))} (allowed: {allowed})")
    for key, wanted in target.items():
        actual = getattr(path, key)
        allowed_values = wanted if isinstance(wanted, list | tuple | set) else [wanted]
        if actual not in allowed_values:
            return False
    return True


def expand_template(template: Mapping[str, Any], paths: Sequence[ISA95Hierarchy], family: str) -> list[DeviceSpec]:
    """Create one DeviceSpec per hierarchy path the template's `target` matches."""
    device_id = template.get("id")
    equipment = template.get("equipment")
    if not device_id:
        raise ValueError(f"device template in family {family!r} is missing 'id'")
    if not equipment:
        raise ValueError(f"device template {device_id!r} in family {family!r} is missing 'equipment'")

    tier = str(template.get("tier", "process"))
    serves = tuple(str(name) for name in template.get("serves") or ())
    raw_signals: Mapping[str, Any] = template.get("signals") or {}

    specs = []
    for name, raw in raw_signals.items():
        raw = raw or {}
        # Spec 11 and 14: `unit` is required on every signal, and this is the only place
        # it can be caught. An absent Unit of Measure is not a cosmetic omission - the
        # frontend and Metric Definitions key off it, and a signal published without one
        # is indistinguishable from a signal whose unit was simply forgotten. Dimensionless
        # ratios declare `unit: "1"` rather than omitting the key, so the omission stays
        # unambiguous.
        if "unit" not in raw or str(raw["unit"]).strip() == "":
            raise ValueError(
                f"device template {device_id!r} signal {name!r}: 'unit' is required (use \"1\" for a dimensionless ratio)"
            )
        specs.append(spec_from_config(name, {"tier": tier, **raw}))
    try:
        ordered = tuple(order_signals(specs))
    except ValueError as exc:
        raise ValueError(f"device template {device_id!r}: {exc}") from exc

    devices: list[DeviceSpec] = []
    for path in paths:
        if not matches_target(path, template.get("target")):
            continue
        devices.append(
            DeviceSpec(
                id=f"{device_id}@{path.site}.{path.area}.{path.line}.{path.cell}",
                equipment=str(equipment),
                family=family,
                tier=tier,
                path=path,
                signals=ordered,
                serves=serves,
                enabled=bool(template.get("enabled", True)),
            )
        )
    if not devices:
        LOGGER.warning("device template %s (family %s) matched no hierarchy path", device_id, family)
    return devices


TIER_DEFAULTS: dict[str, float] = {
    "fast": 1.0,
    "process": 5.0,
    "energy": 15.0,
    "status": 30.0,
    "meter": 900.0,
    "lab": 1800.0,
    "event": 0.0,
}

FAMILIES: tuple[str, ...] = ("wtp",)


@dataclass
class LoadReport:
    """What the loader saw. Rendered by sub-project B's GET /simulator/diagnostics."""

    devices: int = 0
    signals: int = 0
    per_family: dict[str, int] = field(default_factory=dict)
    per_tier: dict[str, int] = field(default_factory=dict)
    serves_links: int = 0
    unmatched_templates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "devices": self.devices,
            "signals": self.signals,
            "per_family": dict(self.per_family),
            "per_tier": dict(self.per_tier),
            "serves_links": self.serves_links,
            "unmatched_templates": list(self.unmatched_templates),
            "warnings": list(self.warnings),
        }


@dataclass
class LoadedProfile:
    """Everything the simulator needs to run, resolved and validated."""

    name: str
    seed: int
    tier_scale: float
    tiers: dict[str, float]
    families: dict[str, bool]
    sites: tuple[str, ...]
    max_cells_per_line: int | None
    devices: tuple[DeviceSpec, ...]
    context: PlantContext
    report: LoadReport

    def messages_per_second(self) -> dict[str, float]:
        """Periodic publish rate per cadence tier, for the volume guard and the control API.

        Counts periodic publishing only. A `tier` whose interval is 0.0 - `event`, by
        default - publishes on change and contributes nothing here, which is honest rather
        than convenient: the two `bernoulli_event` detector faults in safety.yaml average
        about one message a fortnight each, and rounding that to zero is the right rounding.

        A signal on an unrecognised tier is skipped rather than crashing a status endpoint;
        `test_volume.py` is what makes such a signal fail loudly at the right time.
        """
        rates = dict.fromkeys(self.tiers, 0.0)
        for device in self.devices:
            if not device.enabled:
                continue
            for signal in device.signals:
                interval = self.tiers.get(signal.tier, 0.0)
                if interval > 0.0:
                    rates[signal.tier] += 1.0 / interval
        return rates


def filter_paths(
    paths: Sequence[ISA95Hierarchy],
    *,
    sites: Sequence[str] | None = None,
    max_cells_per_line: int | None = None,
) -> list[ISA95Hierarchy]:
    """Narrow the expanded hierarchy the way spec 7.2's profile keys say to.

    `sites` naming a site that is not in the hierarchy is an error rather than an empty
    result: a profile that quietly resolves to nothing is the hardest kind of typo to see.
    """
    if sites is not None:
        wanted = list(dict.fromkeys(str(name) for name in sites))
        available = {path.site for path in paths}
        if unknown := [name for name in wanted if name not in available]:
            raise ValueError(
                f"profile site(s) {', '.join(unknown)} are not in the hierarchy (available: {', '.join(sorted(available))})"
            )
        paths = [path for path in paths if path.site in set(wanted)]

    if max_cells_per_line is None:
        return list(paths)
    if max_cells_per_line < 1:
        raise ValueError(f"max_cells_per_line must be at least 1, got {max_cells_per_line}")

    # Declaration order, not sorted order: the profile author's first cell is the one kept.
    seen: dict[tuple[str, str, str], int] = {}
    kept: list[ISA95Hierarchy] = []
    for path in paths:
        key = (path.site, path.area, path.line)
        count = seen.get(key, 0)
        if count >= max_cells_per_line:
            continue
        seen[key] = count + 1
        kept.append(path)
    return kept


def build_plant_context(paths: Sequence[ISA95Hierarchy], raw_plant: Mapping[str, Any], seed: int) -> PlantContext:
    """Build the PlantContext from the same paths the devices are targeted at."""
    context = PlantContext(global_seed=seed)
    context.enterprise = str((raw_plant.get("enterprise") or "AcmeWater"))
    for path in paths:
        if path.site not in context.sites:
            context.add_site(path.site)
    return context


def _resolve_families(profile_name: str, selection: Mapping[str, Any]) -> dict[str, bool]:
    """Spec 7.2's `families` is a list of names, not a mapping of flags."""
    raw_families = selection.get("families")
    if raw_families is None:
        raw_families = []
    if isinstance(raw_families, Mapping) or isinstance(raw_families, str):
        raise ValueError(
            f"profile {profile_name!r}: 'families' must be a list of family names, got {type(raw_families).__name__}"
        )
    named = [str(name) for name in raw_families]
    if unknown := sorted(set(named) - set(FAMILIES)):
        raise ValueError(f"unknown family/families in profile {profile_name!r}: {', '.join(unknown)}")
    return {family: family in set(named) for family in FAMILIES}


def _resolve_tiers(raw: Mapping[str, Any], tier_scale: float) -> dict[str, float]:
    """Merge `simulation.tiers` onto the defaults, then apply the profile's `tier_scale`."""
    tiers = dict(TIER_DEFAULTS)
    simulation: Mapping[str, Any] = raw.get("simulation") or {}
    overrides: Mapping[str, Any] = simulation.get("tiers") or {}
    if not overrides and (legacy := simulation.get("interval")) is not None:
        # Spec 12: a flat `simulation.interval` was the only cadence knob before tiers
        # existed, and it published every sensor. With no `simulation.tiers` block it still
        # means "how often process values publish", so an untouched settings.yaml keeps the
        # rate it has today instead of silently jumping to the 5 s default.
        tiers["process"] = float(legacy)
    for name, interval in overrides.items():
        if name not in TIER_DEFAULTS:
            raise ValueError(f"unknown cadence tier {name!r} (known tiers: {', '.join(sorted(TIER_DEFAULTS))})")
        if float(interval) < 0.0:
            raise ValueError(f"cadence tier {name!r} must not be negative, got {interval}")
        tiers[name] = float(interval)
    # `event` is 0.0 meaning "on change". Scaling zero keeps it zero, which is what we want:
    # a slow profile must not turn an event topic into a slow periodic one.
    return {name: interval * tier_scale for name, interval in tiers.items()}


def load_profile(raw: Mapping[str, Any], profile_name: str = "full", *, seed: int | None = None) -> LoadedProfile:
    """Resolve a profile into devices, a plant context and a load report.

    `raw` is the merged conf/simulator mapping. Every validation error names the offending
    key, because the alternative - a profile that loads and produces the wrong plant - costs
    far more to diagnose.
    """
    profiles: Mapping[str, Any] = raw.get("profiles") or {}
    selection = profiles.get(profile_name)
    if selection is None:
        known = ", ".join(sorted(profiles)) or "none"
        raise ValueError(f"unknown profile {profile_name!r} (known profiles: {known})")

    families = _resolve_families(profile_name, selection)

    tier_scale = float(selection.get("tier_scale", 1.0))
    if tier_scale <= 0.0:
        raise ValueError(f"profile {profile_name!r}: tier_scale must be positive, got {tier_scale}")
    tiers = _resolve_tiers(raw, tier_scale)

    resolved_seed = int(seed if seed is not None else (raw.get("simulation") or {}).get("seed", 0))

    raw_sites = selection.get("sites")
    max_cells = selection.get("max_cells_per_line")
    max_cells_per_line = int(max_cells) if max_cells is not None else None
    raw_plant: Mapping[str, Any] = raw.get("plant") or {}
    hierarchy: Mapping[str, Any] = raw.get("hierarchy") or {}
    all_paths = expand_hierarchy_paths(hierarchy)
    paths = filter_paths(
        all_paths,
        sites=[str(name) for name in raw_sites] if raw_sites is not None else None,
        max_cells_per_line=max_cells_per_line,
    )
    context = build_plant_context(paths, raw_plant, resolved_seed)
    if hierarchy.get("enterprise"):
        context.enterprise = str(hierarchy["enterprise"])

    report = LoadReport()
    devices: list[DeviceSpec] = []
    seen_template_ids: set[str] = set()
    for family in FAMILIES:
        if not families[family]:
            continue
        for template in (raw.get(family) or {}).get("devices") or []:
            template_id = str(template.get("id", "<missing id>"))
            if template_id in seen_template_ids:
                raise ValueError(f"duplicate device template id {template_id!r} in family {family!r}")
            seen_template_ids.add(template_id)
            expanded = expand_template(template, paths, family)
            if not expanded:
                report.unmatched_templates.append(f"{family}/{template_id}: target matched no hierarchy path")
                continue
            devices.extend(expanded)

    for device in devices:
        report.per_family[device.family] = report.per_family.get(device.family, 0) + 1
        for spec in device.signals:
            if spec.tier not in tiers:
                raise ValueError(
                    f"device {device.id!r} signal {spec.name!r}: unknown tier {spec.tier!r} "
                    f"(known tiers: {', '.join(sorted(tiers))})"
                )
            report.per_tier[spec.tier] = report.per_tier.get(spec.tier, 0) + 1
        report.signals += len(device.signals)
        report.serves_links += len(device.serves)
    report.devices = len(devices)

    if not devices:
        report.warnings.append(f"profile {profile_name!r} resolved to zero devices")

    return LoadedProfile(
        name=profile_name,
        seed=resolved_seed,
        tier_scale=tier_scale,
        tiers=tiers,
        families=families,
        sites=tuple(dict.fromkeys(path.site for path in paths)),
        max_cells_per_line=max_cells_per_line,
        devices=tuple(devices),
        context=context,
        report=report,
    )


SIMULATOR_CONF_SUBDIR: Final = "simulator"

# Everything in plant.yaml that is *not* one of these is hierarchy. Lifting by exclusion
# rather than by an allow-list means a future hierarchy key needs no change here.
_PLANT_NON_HIERARCHY_KEYS: Final = frozenset({"plant", "profiles"})


def _read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    """Parse one file, or None if it is absent. A non-mapping top level is fatal."""
    if not path.is_file():
        return None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{path.name}: expected a YAML mapping at the top level, got {type(loaded).__name__}")
    return dict(loaded)


def read_simulator_conf(conf_dir: Path | None = None) -> dict[str, Any]:
    """Read conf/simulator/*.yaml into the mapping `load_profile` consumes.

    Not routed through `uns_config.get_settings()`: that function hardcodes
    `settings_files=["settings.yaml", ".secrets.yaml"]` for all nine modules, so widening
    it for the simulator's benefit would change config loading platform-wide (spec 7.1).

    Absent files are skipped rather than defaulted. That is what lets spec 14's
    land-one-family-at-a-time work, and what keeps spec 12's promise that a deployment
    with no conf/simulator/ still runs off `simulator.hierarchy` in settings.yaml.
    """
    directory = (conf_dir if conf_dir is not None else resolve_conf_dir()) / SIMULATOR_CONF_SUBDIR
    raw: dict[str, Any] = {}

    if (plant_doc := _read_yaml_mapping(directory / "plant.yaml")) is not None:
        raw["hierarchy"] = {key: value for key, value in plant_doc.items() if key not in _PLANT_NON_HIERARCHY_KEYS}
        raw["plant"] = plant_doc.get("plant") or {}
        raw["profiles"] = plant_doc.get("profiles") or {}

    for family in FAMILIES:
        if (family_doc := _read_yaml_mapping(directory / f"{family}.yaml")) is not None:
            raw[family] = family_doc

    LOGGER.info("Read simulator configuration from %s: %s", directory, ", ".join(sorted(raw)) or "nothing")
    return raw
