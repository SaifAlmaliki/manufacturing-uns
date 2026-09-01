# add to simulator.py, module level
def load_simulator_config(settings_obj: Any) -> dict[str, Any]:
    """Assemble the mapping load_profile expects out of the Dynaconf settings object.

    One adapter, so tests hand load_profile a plain dict and never depend on Dynaconf, and
    production has exactly one place where the two representations meet.
    """
    raw: dict[str, Any] = {
        "hierarchy": settings_obj.get("hierarchy") or {},
        "plant": settings_obj.get("plant") or {},
        "profiles": settings_obj.get("profiles") or {},
        "simulation": settings_obj.get("simulation") or {},
    }
    for family in FAMILIES:
        raw[family] = settings_obj.get(family) or {}
    return raw
