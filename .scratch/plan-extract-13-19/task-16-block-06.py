def load_simulator_config(settings_obj: Any, conf_dir: Path | None = None) -> dict[str, Any]:
    """Assemble the mapping load_profile expects, files layered over Dynaconf.

    One adapter, so tests hand load_profile a plain dict and never depend on Dynaconf, and
    production has exactly one place where the two representations meet.

    `conf/simulator/*.yaml` wins over `settings.yaml` key by key, and only where the file
    supplies something. Whole-mapping replacement would be wrong in one direction and a
    deep merge wrong in the other: `simulation` only ever lives in settings.yaml, and a
    `hierarchy` half from each file would be a plant nobody authored. Per-key overlay is
    what keeps spec 12's promise that an untouched deployment with no conf/simulator/
    behaves exactly as it does today.
    """
    raw: dict[str, Any] = {
        "hierarchy": settings_obj.get("hierarchy") or {},
        "plant": settings_obj.get("plant") or {},
        "profiles": settings_obj.get("profiles") or {},
        "simulation": settings_obj.get("simulation") or {},
    }
    for family in FAMILIES:
        raw[family] = settings_obj.get(family) or {}
    for key, value in read_simulator_conf(conf_dir).items():
        if value:
            raw[key] = value
    return raw
