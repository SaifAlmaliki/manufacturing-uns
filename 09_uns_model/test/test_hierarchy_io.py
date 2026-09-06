"""Tests for `hierarchy_io`: read/write `settings.yaml` hierarchy and branding.

No database, no real conf directory: every test copies a minimal snippet into a
`tmp_path` and asserts on the round-trip. The tree lives in
`default.hierarchy`; `plant.yaml` is only a load fallback.
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

MINIMAL_SETTINGS_WITH_HIERARCHY = """\
default:
  platform:
    instance_name: "Instance01"
    organization_name: "OldCo"
    display_name: "OldCo UNS"
  hierarchy:
    enterprise: OldCo
    sites:
      - name: Site1
        areas:
          - name: RawWater
            kind: production
            lines:
              - name: Train1
                cells: [V101, V102]
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


HIERARCHY_ONLY_YAML = """\
enterprise: OldCo
sites:
  - name: Site1
    areas:
      - name: RawWater
        kind: production
        lines:
          - name: Train1
            cells: [V101, V102]
"""

SIMULATOR_PROFILE_YAML = """\
plant: {}
profiles:
  wtp:
    tier_scale: 1.0
    sites: [Site1]
    families: [wtp]
"""


def _write_plant(conf_dir: Path, text: str = HIERARCHY_ONLY_YAML) -> Path:
    (conf_dir / "hierarchy").mkdir(parents=True, exist_ok=True)
    path = conf_dir / "hierarchy" / "plant.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _write_simulator_profile(conf_dir: Path, text: str = SIMULATOR_PROFILE_YAML) -> Path:
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
                        lines=(HierarchyLine(name="Train1", cells=(HierarchyCell("V101", ("Dryer",)), HierarchyCell("V102"))),),
                    ),
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# load_plant_tree
# ---------------------------------------------------------------------------


def test_load_plant_tree_reads_settings_hierarchy(tmp_path: Path):
    _write_settings(tmp_path, MINIMAL_SETTINGS_WITH_HIERARCHY)

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


def test_load_plant_tree_prefers_settings_over_plant_yaml(tmp_path: Path):
    _write_settings(tmp_path, MINIMAL_SETTINGS_WITH_HIERARCHY)
    _write_plant(
        tmp_path,
        """\
enterprise: FromFile
sites:
  - name: Other
    areas: []
""",
    )

    tree = load_plant_tree(tmp_path)

    assert tree.enterprise == "OldCo"
    assert tree.sites[0].name == "Site1"


def test_load_plant_tree_falls_back_to_legacy_simulator_hierarchy(tmp_path: Path):
    _write_settings(
        tmp_path,
        """\
default:
  platform:
    organization_name: OldCo
simulator:
  hierarchy:
    enterprise: LegacyCo
    sites:
      - name: Site1
        areas:
          - name: RawWater
            kind: production
            lines:
              - name: Train1
                cells: [V101]
""",
    )

    tree = load_plant_tree(tmp_path)

    assert tree.enterprise == "LegacyCo"
    assert tree.sites[0].name == "Site1"


def test_save_moves_legacy_simulator_hierarchy_to_default(tmp_path: Path):
    _write_settings(
        tmp_path,
        """\
default:
  platform:
    organization_name: OldCo
simulator:
  hierarchy:
    enterprise: LegacyCo
    sites: []
  mqtt:
    client_id: uns_simulator_client
""",
    )

    save_plant_tree(tmp_path, _sample_tree())

    doc = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    assert doc["default"]["hierarchy"]["enterprise"] == "Contoso"
    assert "hierarchy" not in doc["simulator"]
    assert doc["simulator"]["mqtt"]["client_id"] == "uns_simulator_client"


def test_load_plant_tree_falls_back_to_plant_yaml(tmp_path: Path):
    _write_plant(tmp_path)

    tree = load_plant_tree(tmp_path)

    assert tree.enterprise == "OldCo"
    assert tree.sites[0].name == "Site1"


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
    _write_settings(tmp_path, MINIMAL_SETTINGS_WITH_HIERARCHY)
    tree = _sample_tree()

    save_plant_tree(tmp_path, tree)

    assert load_plant_tree(tmp_path) == tree


def test_save_writes_the_list_of_objects_sites_shape_into_settings(tmp_path: Path):
    _write_settings(tmp_path, MINIMAL_SETTINGS_YAML)

    save_plant_tree(tmp_path, _sample_tree())

    doc = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    hierarchy = doc["default"]["hierarchy"]
    assert isinstance(hierarchy["sites"], list)
    assert hierarchy["sites"][0]["name"] == "Nord"
    assert hierarchy["sites"][0]["areas"][0]["name"] == "RawWater"
    assert hierarchy["sites"][0]["areas"][0]["kind"] == "production"
    assert hierarchy["sites"][0]["areas"][0]["lines"][0]["name"] == "Train1"
    assert hierarchy["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": ["Dryer"]},
        {"name": "V102", "machines": []},
    ]
    assert "plant" not in hierarchy
    assert "profiles" not in hierarchy


def test_save_defaults_empty_area_kind_to_production(tmp_path: Path):
    _write_settings(tmp_path, MINIMAL_SETTINGS_YAML)

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

    doc = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    assert doc["default"]["hierarchy"]["sites"][0]["areas"][0]["kind"] == "production"


def test_save_uses_an_atomic_write(tmp_path: Path):
    _write_settings(tmp_path, MINIMAL_SETTINGS_YAML)

    save_plant_tree(tmp_path, _sample_tree())

    assert not (tmp_path / "settings.yaml.tmp").exists()
    assert (tmp_path / "settings.yaml").exists()


def test_save_writes_plant_yaml_when_settings_are_missing(tmp_path: Path):
    tree = _sample_tree()

    save_plant_tree(tmp_path, tree)

    assert (tmp_path / "hierarchy" / "plant.yaml").exists()
    assert not (tmp_path / "simulator" / "plant.yaml").exists()
    assert not (tmp_path / "settings.yaml").exists()
    assert load_plant_tree(tmp_path) == tree


def test_load_falls_back_to_simulator_plant_yaml(tmp_path: Path):
    _write_simulator_profile(
        tmp_path,
        MINIMAL_PLANT_YAML,
    )

    tree = load_plant_tree(tmp_path)

    assert tree.enterprise == "OldCo"
    assert tree.sites[0].name == "Site1"


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
    assert "dynaconf_merge: true" in text
    assert "ISA-95 plant tree" in text
