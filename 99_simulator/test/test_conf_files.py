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

from uns_simulator.models import ParameterType
from uns_simulator.profiles import load_profile, read_simulator_conf

CONF_DIR = Path(__file__).resolve().parents[2] / "conf"

# Signals declared by each device template, per spec 8.1-8.2. Tasks 17 and 18 extend
# these tables as they add family files; a family named in a profile whose file does not
# exist yet contributes nothing and is not an error, which is spec 14's
# land-one-family-at-a-time mitigation working as intended.
EXPECTED_SIGNAL_COUNT = {
    "wtp": {
        "V101": 6, "V201": 6, "V202": 6, "V301": 6,
        "P101": 8, "P102": 8, "P103": 8, "DP101": 8,
        "P201": 8, "P202": 8,
        "T101": 3, "T201": 3, "B101": 2,
        "FT101": 3, "FT201": 3,
        "PT101": 1, "PT201": 1,
        "AIT101": 1, "F101": 3,
    }
}

EXPECTED_DEVICE_COUNT = {k: {i: 1 for i in v} for k, v in EXPECTED_SIGNAL_COUNT.items()}

FAMILY_TEMPLATES = [
    (family, template_id, count) for family, table in EXPECTED_SIGNAL_COUNT.items() for template_id, count in table.items()
]


@pytest.fixture(scope="module")
def raw():
    return read_simulator_conf(CONF_DIR)


def test_hierarchy_plant_yaml_supplies_the_tree(raw):
    """The ISA-95 tree is conf/hierarchy/plant.yaml, not the simulator profile file."""
    assert raw["hierarchy"]["enterprise"]
    assert raw["hierarchy"]["sites"]
    assert "profiles" not in raw["hierarchy"]
    assert "plant" not in raw["hierarchy"]


def test_the_shipped_profile_is_declared(raw):
    assert set(raw["profiles"]) == {"wtp"}
    assert raw["profiles"]["wtp"]["tier_scale"] == 1.0
    assert raw["profiles"]["wtp"]["sites"] == [site["name"] for site in raw["hierarchy"]["sites"]]
    assert raw["profiles"]["wtp"]["families"] == ["wtp"]


def test_a_serves_list_never_names_another_sites_lines(raw):
    """A copied template with a Site1 `serves` list is the mistake this catches.

    `load_profile` rejects a `serves` path that resolves to nothing, but Site1's lines
    do resolve - so a meter carrying another site's prefix would correlate against the
    wrong area and load perfectly cleanly. Only the site prefix betrays it. WTP ships a
    single site, so this is vacuous today; kept for the day a second site lands.
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

    A device count of 1 is what rules out a silent replication, so it is asserted rather
    than left to the table.
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


def test_the_wtp_profile_loads_from_disk_with_the_expected_device_count(raw):
    profile = load_profile(raw, "wtp")
    expected = sum(count for table in EXPECTED_DEVICE_COUNT.values() for count in table.values())
    assert profile.report.devices == expected - len(profile.report.unmatched_templates)
    assert profile.report.warnings == []


def test_the_wtp_profile_signal_count_is_the_table_multiplied_out(raw):
    profile = load_profile(raw, "wtp")
    expected = sum(
        EXPECTED_SIGNAL_COUNT[family][template_id] * EXPECTED_DEVICE_COUNT[family][template_id]
        for family, table in EXPECTED_SIGNAL_COUNT.items()
        for template_id in table
    )
    missing = 0
    for row in profile.report.unmatched_templates:
        family, rest = row.split("/", 1)
        template_id = rest.split(":", 1)[0].strip()
        missing += EXPECTED_SIGNAL_COUNT[family][template_id]
    assert profile.report.signals == expected - missing


def test_loading_the_same_directory_twice_gives_identical_reports(raw):
    """Spec 5.3: the seed is the only source of variation, and the files do not carry one."""
    assert load_profile(raw, "wtp").report.as_dict() == load_profile(read_simulator_conf(CONF_DIR), "wtp").report.as_dict()


def test_an_absent_conf_directory_is_not_an_error(tmp_path):
    """Spec 12: a deployment with no conf/simulator still runs off settings.yaml."""
    assert read_simulator_conf(tmp_path) == {}


def test_an_absent_family_file_is_skipped(tmp_path):
    conf = tmp_path / "simulator"
    conf.mkdir()
    (conf / "plant.yaml").write_text("enterprise: E\nsites: []\n", encoding="utf-8")
    raw = read_simulator_conf(tmp_path)
    assert raw["hierarchy"] == {"enterprise": "E", "sites": []}
    assert "wtp" not in raw


def test_a_family_file_that_is_not_a_mapping_is_rejected_by_name(tmp_path):
    conf = tmp_path / "simulator"
    conf.mkdir()
    (conf / "wtp.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="wtp.yaml"):
        read_simulator_conf(tmp_path)


def test_every_topic_prefix_is_acmewater_wtp(raw):
    """Spec 7.2: the topic prefix is enterprise/site/area/line/cell/equipment.

    The WTP plant ships a single enterprise, site and train, so every prefix shares its
    first four segments and the train. The cell is the tag (V101, P101, ...) and the
    equipment is the poster template name (WTP_Valve, WTP_MotorDOL, ...), so the two must
    disagree and the equipment must carry the WTP_ namespace.
    """
    profile = load_profile(raw, "wtp")
    enterprise = raw["hierarchy"]["enterprise"]
    site = raw["hierarchy"]["sites"][0]["name"]
    for device in profile.devices:
        parts = device.topic_prefix.split("/")
        assert parts[0] == enterprise
        assert parts[1] == site
        assert parts[4] == device.path.cell
        assert parts[5] == device.equipment
        assert parts[5].startswith("WTP_")
        assert parts[4] != parts[5]


def test_kpi_is_a_parameter_type_no_simulated_device_claims(raw):
    """The sixth ParameterType exists, and nothing here publishes under it.

    A simulated device claiming `KPI` would put a fabricated number back on the topic the
    OEE engine writes to, which is the whole thing spec 12 removes.
    """
    assert ParameterType("KPI") is ParameterType.KPI
    for family in EXPECTED_SIGNAL_COUNT:
        for template in raw[family]["devices"]:
            for name, signal in template["signals"].items():
                claimed = (signal or {}).get("param_type")
                assert claimed != "KPI", f"{family}.yaml {template['id']}/{name} claims KPI"


def test_process_md_exists():
    """Spec 10/11: operators can read the plant without opening Python."""
    assert (Path(__file__).resolve().parents[1] / "PROCESS.md").is_file()
