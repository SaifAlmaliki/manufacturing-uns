# 99_simulator/test/test_conf_files.py
"""The real conf/simulator/*.yaml files, loaded from disk.

Every other suite hands `load_profile` a dict, which is what keeps them fast and
hermetic - and also what makes them blind to the files that actually ship. This is the
only place that would notice a family file nobody wrote, a device that lost half its
signals in transcription, or a `serves` path naming a line the hierarchy renamed.

The two tables are the point of the file. Asserting a single total device count would
pass just as happily on a wrong total that I miscomputed; a count per template cannot,
because a missing device names itself.
"""

from pathlib import Path

import pytest

from uns_simulator.plant import PACKML_STATES
from uns_simulator.profiles import load_profile, read_simulator_conf

CONF_DIR = Path(__file__).resolve().parents[2] / "conf"

# Signals declared by each device template, per spec 8.1-8.2. Tasks 17 and 18 extend
# these tables as they add family files; a family named in a profile whose file does not
# exist yet contributes nothing and is not an error, which is spec 14's
# land-one-family-at-a-time mitigation working as intended.
EXPECTED_SIGNAL_COUNT = {
    "energy": {"EM-01": 17, "EM-02": 17, "TR-01": 6, "MCC-01": 6, "MCC-02": 6},
    "water": {"FM-01": 5, "DEMIN-01": 6, "CT-01": 11, "CT-02": 11, "EFF-01": 9},
    "utilities": {
        "CMP-01": 8,
        "CMP-02": 8,
        "CMP-03": 8,
        "DRY-01": 4,
        "AH-01": 4,
        "AH-02": 4,
        "BLR-01": 11,
        "SH-01": 3,
        "CR-01": 4,
        "N2-01": 5,
        "N2H-01": 2,
        "AHU-01": 8,
        "CH-01": 7,
    },
    "asset_health": {"VIB-01": 15, "VIB-02": 12},
    "production": {"MES-01": 15, "QA-01": 6, "LAB-01": 6, "001": 2, "002": 1},
    "safety": {"GD-01": 7, "GD-02": 7, "CEMS-01": 9, "SIS-01": 6, "WS-01": 9},
}

EXPECTED_DEVICE_COUNT = {
    "energy": {"EM-01": 1, "EM-02": 1, "TR-01": 1, "MCC-01": 1, "MCC-02": 1},
    "water": {"FM-01": 2, "DEMIN-01": 1, "CT-01": 1, "CT-02": 1, "EFF-01": 1},
    "utilities": {
        "CMP-01": 1,
        "CMP-02": 1,
        "CMP-03": 1,
        "DRY-01": 1,
        "AH-01": 1,
        "AH-02": 1,
        "BLR-01": 1,
        "SH-01": 1,
        "CR-01": 1,
        "N2-01": 1,
        "N2H-01": 1,
        "AHU-01": 1,
        "CH-01": 1,
    },
    # VIB-01 lands on every Production cell: Dormagen Line1/Cell1, Line1/Cell2,
    # Line2/Cell1, and Krefeld Line1/Cell1. VIB-02 lands on the three compressor cells.
    "asset_health": {"VIB-01": 4, "VIB-02": 3},
    # MES-01, QA-01 and the two legacy PLC templates land on all four Production cells.
    # LAB-01 is Dormagen's Quality area only.
    "production": {"MES-01": 4, "QA-01": 4, "LAB-01": 1, "001": 4, "002": 4},
    # GD_Zone1 and WS_01 exist at both sites; GD_Zone2 and Stack_S1 are Dormagen-only.
    "safety": {"GD-01": 2, "GD-02": 1, "CEMS-01": 1, "SIS-01": 1, "WS-01": 2},
}

FAMILY_TEMPLATES = [
    (family, template_id, count) for family, table in EXPECTED_SIGNAL_COUNT.items() for template_id, count in table.items()
]


@pytest.fixture(scope="module")
def raw():
    return read_simulator_conf(CONF_DIR)


def test_plant_yaml_supplies_the_hierarchy_at_the_top_level(raw):
    """Spec 7.2 writes `enterprise:` and `sites:` at the top of plant.yaml."""
    assert raw["hierarchy"]["enterprise"] == "CovestroAG"
    assert [site["name"] for site in raw["hierarchy"]["sites"]] == ["Dormagen", "Krefeld"]
    assert "profiles" not in raw["hierarchy"]
    assert "plant" not in raw["hierarchy"]


def test_both_shipped_profiles_are_declared(raw):
    assert set(raw["profiles"]) == {"small", "full"}
    assert raw["profiles"]["small"]["tier_scale"] == 6.0
    assert raw["profiles"]["small"]["sites"] == ["Dormagen"]
    assert raw["profiles"]["small"]["max_cells_per_line"] == 1
    assert raw["profiles"]["full"]["sites"] == ["Dormagen", "Krefeld"]


def test_a_serves_list_never_names_another_sites_lines(raw):
    """A copied template with a Dormagen `serves` list is the mistake this catches.

    `load_profile` rejects a `serves` path that resolves to nothing, but Dormagen's lines
    do resolve - so a Krefeld meter carrying them would correlate against the wrong site's
    production and load perfectly cleanly. Only the site prefix betrays it.
    """
    for family in EXPECTED_SIGNAL_COUNT:
        for template in raw[family]["devices"]:
            site = (template.get("target") or {}).get("site")
            if site is None:
                continue  # covered by the next test instead
            for served in template.get("serves") or []:
                assert served.startswith(f"{site}/"), f"{template['id']} serves {served} but sits on {site}"


def test_a_template_carrying_serves_never_replicates(raw):
    """The other half of the guard above, for templates that omit `target.site`.

    `TR-01` and `MCC-01` leave `site` out because `Transformer_T1` and `MCC_Production` are
    Dormagen-only cell names. If a Krefeld cell were ever given one of those names they
    would replicate silently, and the copy would carry Dormagen's `serves` list. A device
    count of 1 is what rules that out, so it is asserted rather than left to the table.
    """
    for family, table in EXPECTED_DEVICE_COUNT.items():
        for template in raw[family]["devices"]:
            if template.get("serves"):
                assert table[str(template["id"])] == 1, f"{template['id']} carries `serves` and replicates"


@pytest.mark.parametrize(("family", "template_id", "expected"), FAMILY_TEMPLATES)
def test_each_template_declares_the_expected_signal_count(raw, family, template_id, expected):
    by_id = {str(template["id"]): template for template in raw[family]["devices"]}
    assert len(by_id[template_id]["signals"]) == expected


def test_the_family_files_declare_exactly_the_expected_templates(raw):
    for family, table in EXPECTED_SIGNAL_COUNT.items():
        declared = [str(template["id"]) for template in raw[family]["devices"]]
        assert sorted(declared) == sorted(table), f"{family}.yaml template ids drifted from the table"
        assert len(declared) == len(set(declared)), f"{family}.yaml declares a duplicate id"


def test_every_signal_in_every_family_file_declares_a_unit(raw):
    """`expand_template` enforces this too; this test names the file and the signal."""
    for family in EXPECTED_SIGNAL_COUNT:
        for template in raw[family]["devices"]:
            for name, signal in template["signals"].items():
                unit = (signal or {}).get("unit")
                assert unit is not None and str(unit).strip(), f"{family}.yaml {template['id']}/{name} has no unit"


def test_the_full_profile_loads_from_disk_with_the_expected_device_count(raw):
    profile = load_profile(raw, "full")
    expected = sum(count for table in EXPECTED_DEVICE_COUNT.values() for count in table.values())
    assert profile.report.devices == expected
    assert profile.report.warnings == []
    assert profile.report.unmatched_templates == []


def test_the_full_profile_signal_count_is_the_table_multiplied_out(raw):
    profile = load_profile(raw, "full")
    expected = sum(
        EXPECTED_SIGNAL_COUNT[family][template_id] * EXPECTED_DEVICE_COUNT[family][template_id]
        for family, table in EXPECTED_SIGNAL_COUNT.items()
        for template_id in table
    )
    assert profile.report.signals == expected


def test_the_small_profile_drops_krefeld_and_the_second_cell(raw):
    small = load_profile(raw, "small")
    full = load_profile(raw, "full")
    assert small.report.devices < full.report.devices
    assert {device.path.site for device in small.devices} == {"Dormagen"}
    assert small.tiers["process"] == pytest.approx(30.0), "5 s process tier times a tier_scale of 6"


def test_loading_the_same_directory_twice_gives_identical_reports(raw):
    """Spec 5.3: the seed is the only source of variation, and the files do not carry one."""
    assert load_profile(raw, "full").report.as_dict() == load_profile(read_simulator_conf(CONF_DIR), "full").report.as_dict()


def test_an_absent_conf_directory_is_not_an_error(tmp_path):
    """Spec 12: a deployment with no conf/simulator still runs off settings.yaml."""
    assert read_simulator_conf(tmp_path) == {}


def test_an_absent_family_file_is_skipped(tmp_path):
    conf = tmp_path / "simulator"
    conf.mkdir()
    (conf / "plant.yaml").write_text("enterprise: E\nsites: []\n", encoding="utf-8")
    raw = read_simulator_conf(tmp_path)
    assert raw["hierarchy"] == {"enterprise": "E", "sites": []}
    assert "energy" not in raw


def test_a_family_file_that_is_not_a_mapping_is_rejected_by_name(tmp_path):
    conf = tmp_path / "simulator"
    conf.mkdir()
    (conf / "energy.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="energy.yaml"):
        read_simulator_conf(tmp_path)


def test_asset_health_is_excluded_from_the_small_profile(raw):
    """Spec 9: asset_health publishes on the `fast` tier, so `small` must not load it.

    `small` is the shipped default and its whole purpose is to keep the graphdb mapper's
    per-topic-level MERGE load survivable. A fast-tier family creeping into it would undo
    that quietly - the simulator would still work, and Neo4j would simply fall behind.
    """
    small = load_profile(raw, "small")
    assert "asset_health" not in small.report.per_family
    assert small.families["asset_health"] is False
    assert load_profile(raw, "full").report.per_family["asset_health"] == 7


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


LEGACY_PLC_SENSORS = {
    ("001", "G1"): {"Temperature": (75.0, 2.0, "°C"), "Pressure": (150.0, 5.0, "psi")},
    ("002", "FillingMachine"): {"FlowRate": (450.0, 20.0, "L/min")},
}


@pytest.mark.parametrize("key", sorted(LEGACY_PLC_SENSORS))
def test_legacy_plc_templates_moved_across_unchanged(raw, key):
    """Spec 8.5 and 12: the pre-existing PLC signals must publish exactly as they did.

    `sensors:` became `signals:` and the file changed, but `equipment` decides the topic and
    base_value/variation/unit decide the payload, so those four are what this asserts. A
    `shape` key appearing on any of them would also be a change - `noise` is the default and
    the old generator had no other behaviour.
    """
    device_id, equipment = key
    sensors = LEGACY_PLC_SENSORS[key]
    template = next(item for item in raw["production"]["devices"] if str(item["id"]) == device_id)
    assert template["equipment"] == equipment
    assert template.get("target") is None, "an absent target means every production cell, which is what create_plc did"
    assert set(template["signals"]) == set(sensors)
    for name, (base_value, variation, unit) in sensors.items():
        signal = template["signals"][name]
        assert signal["base_value"] == base_value
        assert signal["variation"] == variation
        assert signal["unit"] == unit
        assert "shape" not in signal


def test_the_weather_station_reports_the_plant_context(raw):
    """The station must not be a second, disagreeing model of the same weather.

    SiteState already derives all five of these from plant.yaml. SolarIrradiance is exempt:
    PlantContext has no sunlight, so a `diurnal` of its own is the only option.
    """
    signals = next(item for item in raw["safety"]["devices"] if item["id"] == "WS-01")["signals"]
    from_context = {
        "AmbientTemp": "ctx.ambient_temp_c",
        "RelativeHumidity": "ctx.ambient_rh_pct",
        "WetBulbTemp": "ctx.wet_bulb_temp_c",
        "WindSpeed": "ctx.wind_speed_ms",
        "BarometricPressure": "ctx.barometric_mbar",
    }
    for name, path in from_context.items():
        assert signals[name]["shape"] == "derived"
        assert path in signals[name]["expr"], f"{name} must read {path}"
    assert signals["SolarIrradiance"]["shape"] == "diurnal"


def test_packml_state_code_maps_every_state(raw):
    """A state missing from the map publishes its own name where an integer is expected.

    SteppedSignal._translate falls through to the raw value on a miss, so an incomplete map
    fails as a type surprise on a consumer rather than at load time. Only this test catches it.
    """
    signals = next(item for item in raw["production"]["devices"] if item["id"] == "MES-01")["signals"]
    assert set(signals["PackMlStateCode"]["map"]) == set(PACKML_STATES)
    assert set(signals["DowntimeReason"]["map"]) == set(PACKML_STATES)
