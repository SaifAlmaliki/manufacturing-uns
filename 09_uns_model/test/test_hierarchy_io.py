"""Tests for `hierarchy_io`: read/write `plant.yaml` and derive enterprise settings.

No database, no real conf directory: every test copies a minimal snippet into a
`tmp_path` and asserts on the round-trip. The shipped `conf/simulator/plant.yaml`
uses a list-of-objects sites shape, so `save_plant_tree` must emit that shape to
keep the file loadable by the simulator.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from uns_model.hierarchy import (
    HierarchyArea,
    HierarchyCell,
    HierarchyLine,
    HierarchySite,
    HierarchyTree,
)
from uns_model.hierarchy_io import (
    apply_enterprise_to_settings,
    load_plant_tree,
    save_plant_tree,
    write_enterprise_settings,
)

# ---------------------------------------------------------------------------
# Fixtures: minimal copies of the shipped shapes.
# ---------------------------------------------------------------------------

MINIMAL_PLANT_YAML = """\
enterprise: OldCo
sites:
  - name: Site1
    areas:
      - name: RawWater
        kind: production
        lines:
          - name: Train1
            cells: [V101, V102]
plant: {}
profiles:
  wtp:
    tier_scale: 1.0
    sites: [Site1]
    families: [wtp]
"""

MINIMAL_SETTINGS_YAML = """\
default:
  platform:
    instance_name: "Instance01"
    organization_name: "OldCo"
    display_name: "OldCo UNS"
graphdb:
  mqtt:
    topics: ["test/uns/#", "OtherCorp/#", "spBv1.0/uns_group/#"]
historian:
  mqtt:
    topics: ["test/uns/#", "OtherCorp/#", "spBv1.0/#"]
kafka_mapper:
  mqtt:
    topics: ["test/uns/#", "OtherCorp/#"]
dynaconf_merge: true
"""


def _write_plant(conf_dir: Path, text: str = MINIMAL_PLANT_YAML) -> Path:
    (conf_dir / "simulator").mkdir(parents=True, exist_ok=True)
    path = conf_dir / "simulator" / "plant.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _write_settings(conf_dir: Path, text: str = MINIMAL_SETTINGS_YAML) -> Path:
    path = conf_dir / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _sample_tree() -> HierarchyTree:
    return HierarchyTree(
        enterprise="Contoso",
        sites=(
            HierarchySite(
                name="Nord",
                areas=(
                    HierarchyArea(
                        name="RawWater",
                        kind="production",
                        lines=(HierarchyLine(name="Train1", cells=(HierarchyCell("V101"), HierarchyCell("V102"))),),
                    ),
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# load_plant_tree
# ---------------------------------------------------------------------------


def test_load_plant_tree_reads_the_shipped_list_shape(tmp_path: Path):
    _write_plant(tmp_path)

    tree = load_plant_tree(tmp_path)

    assert tree.enterprise == "OldCo"
    assert tree.sites == (
        HierarchySite(
            name="Site1",
            areas=(
                HierarchyArea(
                    name="RawWater",
                    kind="production",
                    lines=(HierarchyLine(name="Train1", cells=(HierarchyCell("V101"), HierarchyCell("V102"))),),
                ),
            ),
        ),
    )


def test_load_plant_tree_defaults_missing_area_kind_to_production(tmp_path: Path):
    _write_plant(
        tmp_path,
        """\
enterprise: E
sites:
  - name: S
    areas:
      - name: A
        lines:
          - name: L
            cells: [C1]
""",
    )

    tree = load_plant_tree(tmp_path)

    assert tree.sites[0].areas[0].kind == "production"


# ---------------------------------------------------------------------------
# save_plant_tree
# ---------------------------------------------------------------------------


def test_save_then_load_round_trips_the_tree(tmp_path: Path):
    _write_plant(tmp_path)
    tree = _sample_tree()

    save_plant_tree(tmp_path, tree)

    assert load_plant_tree(tmp_path) == tree


def test_save_writes_the_list_of_objects_sites_shape(tmp_path: Path):
    _write_plant(tmp_path)

    save_plant_tree(tmp_path, _sample_tree())

    doc = yaml.safe_load((tmp_path / "simulator" / "plant.yaml").read_text(encoding="utf-8"))
    assert isinstance(doc["sites"], list)
    assert doc["sites"][0]["name"] == "Nord"
    assert doc["sites"][0]["areas"][0]["name"] == "RawWater"
    assert doc["sites"][0]["areas"][0]["kind"] == "production"
    assert doc["sites"][0]["areas"][0]["lines"][0]["name"] == "Train1"
    assert doc["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": []},
        {"name": "V102", "machines": []},
    ]


def test_save_replaces_enterprise_and_sites_keeps_plant_and_profiles(tmp_path: Path):
    _write_plant(tmp_path)

    save_plant_tree(tmp_path, _sample_tree())

    doc = yaml.safe_load((tmp_path / "simulator" / "plant.yaml").read_text(encoding="utf-8"))
    assert doc["enterprise"] == "Contoso"
    assert doc["plant"] == {}
    assert doc["profiles"]["wtp"]["tier_scale"] == 1.0
    assert doc["profiles"]["wtp"]["families"] == ["wtp"]
    # Site1 rename must not leave a dead profile filter.
    assert doc["profiles"]["wtp"]["sites"] == ["Nord"]


def test_save_defaults_empty_area_kind_to_production(tmp_path: Path):
    _write_plant(tmp_path)

    tree = HierarchyTree(
        enterprise="E",
        sites=(
            HierarchySite(
                name="S",
                areas=(HierarchyArea(name="A", kind="", lines=(HierarchyLine("L", (HierarchyCell("C"),)),)),),
            ),
        ),
    )

    save_plant_tree(tmp_path, tree)

    doc = yaml.safe_load((tmp_path / "simulator" / "plant.yaml").read_text(encoding="utf-8"))
    assert doc["sites"][0]["areas"][0]["kind"] == "production"


def test_save_uses_an_atomic_write(tmp_path: Path):
    _write_plant(tmp_path)

    save_plant_tree(tmp_path, _sample_tree())

    assert not (tmp_path / "simulator" / "plant.yaml.tmp").exists()
    assert (tmp_path / "simulator" / "plant.yaml").exists()


def test_save_creates_the_simulator_dir_when_missing(tmp_path: Path):
    tree = _sample_tree()

    save_plant_tree(tmp_path, tree)

    assert (tmp_path / "simulator" / "plant.yaml").exists()
    assert load_plant_tree(tmp_path) == tree


# ---------------------------------------------------------------------------
# apply_enterprise_to_settings
# ---------------------------------------------------------------------------


def test_apply_enterprise_to_settings_sets_platform_branding():
    text = apply_enterprise_to_settings(MINIMAL_SETTINGS_YAML, "Contoso")

    doc = yaml.safe_load(text)
    assert doc["default"]["platform"]["organization_name"] == "Contoso"
    assert doc["default"]["platform"]["display_name"] == "Contoso UNS"


def test_apply_enterprise_to_settings_rewrites_mapper_topic_filters():
    text = apply_enterprise_to_settings(MINIMAL_SETTINGS_YAML, "Contoso")

    doc = yaml.safe_load(text)
    assert doc["graphdb"]["mqtt"]["topics"] == ["test/uns/#", "Contoso/#", "spBv1.0/uns_group/#"]
    assert doc["historian"]["mqtt"]["topics"] == ["test/uns/#", "Contoso/#", "spBv1.0/#"]
    assert doc["kafka_mapper"]["mqtt"]["topics"] == ["test/uns/#", "Contoso/#"]


def test_apply_enterprise_to_settings_keeps_test_uns_and_sparkplug_entries():
    text = apply_enterprise_to_settings(MINIMAL_SETTINGS_YAML, "Contoso")

    doc = yaml.safe_load(text)
    for env in ("graphdb", "historian", "kafka_mapper"):
        topics = doc[env]["mqtt"]["topics"]
        assert "test/uns/#" in topics
    assert any(t.startswith("spBv1.0") for t in doc["graphdb"]["mqtt"]["topics"])
    assert any(t.startswith("spBv1.0") for t in doc["historian"]["mqtt"]["topics"])


def test_apply_enterprise_to_settings_dedupes_replaced_filters():
    snippet = """\
graphdb:
  mqtt:
    topics: ["test/uns/#", "OldCo/#", "OtherCorp/#", "spBv1.0/#"]
"""
    text = apply_enterprise_to_settings(snippet, "Contoso")

    doc = yaml.safe_load(text)
    assert doc["graphdb"]["mqtt"]["topics"] == ["test/uns/#", "Contoso/#", "spBv1.0/#"]


def test_apply_enterprise_to_settings_preserves_dynaconf_merge():
    text = apply_enterprise_to_settings(MINIMAL_SETTINGS_YAML, "Contoso")

    doc = yaml.safe_load(text)
    assert doc["dynaconf_merge"] is True


def test_apply_enterprise_to_settings_leaves_non_topic_keys_untouched():
    text = apply_enterprise_to_settings(MINIMAL_SETTINGS_YAML, "Contoso")

    doc = yaml.safe_load(text)
    assert doc["default"]["platform"]["instance_name"] == "Instance01"


# ---------------------------------------------------------------------------
# write_enterprise_settings
# ---------------------------------------------------------------------------


def test_write_enterprise_settings_writes_the_derived_file(tmp_path: Path):
    _write_settings(tmp_path)

    write_enterprise_settings(tmp_path, "Contoso")

    doc = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    assert doc["default"]["platform"]["organization_name"] == "Contoso"
    assert doc["graphdb"]["mqtt"]["topics"] == ["test/uns/#", "Contoso/#", "spBv1.0/uns_group/#"]


def test_write_enterprise_settings_uses_an_atomic_write(tmp_path: Path):
    _write_settings(tmp_path)

    write_enterprise_settings(tmp_path, "Contoso")

    assert not (tmp_path / "settings.yaml.tmp").exists()
    assert (tmp_path / "settings.yaml").exists()


def test_apply_enterprise_to_settings_round_trips_the_shipped_file():
    """C1/I8: a hierarchy save must not strip comments or mapper-adjacent blocks."""
    shipped = Path(__file__).resolve().parents[2] / "conf" / "settings.yaml"
    original = shipped.read_text(encoding="utf-8")

    text = apply_enterprise_to_settings(original, "Contoso")

    doc = yaml.safe_load(text)
    assert doc["graphql"]["mqtt"]["topics"] == ["#"]
    assert doc["sparkplugb"]["mqtt"]["topics"] == ["spBv1.0/uns_group/#"]
    assert doc["dynaconf_merge"] is True
    assert doc["graphdb"]["mqtt"]["topics"] == ["test/uns/#", "Contoso/#", "spBv1.0/uns_group/#"]
    assert doc["historian"]["mqtt"]["topics"] == ["test/uns/#", "Contoso/#", "spBv1.0/#"]
    assert doc["kafka_mapper"]["mqtt"]["topics"] == ["test/uns/#", "Contoso/#"]
    assert "docs/adr/0007-simulator-control-api-outside-graphql.md" in text
