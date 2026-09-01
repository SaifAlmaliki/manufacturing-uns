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
