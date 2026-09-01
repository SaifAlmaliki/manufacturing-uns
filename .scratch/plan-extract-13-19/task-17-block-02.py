def test_asset_health_is_excluded_from_the_small_profile(raw):
    """Spec 9: asset_health publishes on the `fast` tier, so `small` must not load it.

    `small` is the shipped default and its whole purpose is to keep the graphdb mapper's
    per-topic-level MERGE load survivable. A fast-tier family creeping into it would undo
    that quietly - the simulator would still work, and Neo4j would simply fall behind.
    """
    small = load_profile(raw, "small")
    assert "asset_health" not in small.report.per_family
    assert small.families["asset_health"] is False
    assert load_profile(raw, "full").report.per_family["asset_health"] == 7  # noqa: PLR2004


def test_every_asset_health_signal_is_on_a_deliberate_tier(raw):
    """A `fast` tier is 1 s per signal per device; nothing lands there by accident.

    Counters and the ISO 4406 oil class are explicitly demoted, so this test is what stops
    a 15-minute register from being republished every second on 7 devices.
    """
    slow = {"RunHours": "meter", "StartCount": "meter", "LubeOilParticleCount": "status"}
    for template in raw["asset_health"]["devices"]:
        assert template["tier"] == "fast"
        for name, signal in template["signals"].items():
            assert signal.get("tier") == slow.get(name), f"{template['id']}/{name} is on the wrong tier"
