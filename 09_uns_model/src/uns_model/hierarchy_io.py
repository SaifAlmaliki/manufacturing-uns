"""Read/write the ISA-95 tree in `conf/settings.yaml` and derive branding/mapper filters.

The plant lives in `default.hierarchy` of the same settings file every
deployment already mounts. That tree is the plant — OPC UA, Modbus, or
any other publisher is just a source of signals on it.
`saveHierarchy` writes that block, then derives branding and mapper topic
filters from the enterprise name. Separate `plant.yaml` files and a legacy
`simulator.hierarchy` key are load fallbacks for old checkouts only.

Sites are stored as a list of objects (`{name, areas: [...]}`).
`tree_to_mapping` is the shared projection used here and by seed.
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML

from uns_model.hierarchy import (
    HierarchyTree,
    tree_from_mapping,
    tree_to_mapping,
)

PLANT_SUBDIR = "hierarchy"
PLANT_FILENAME = "plant.yaml"
SIMULATOR_SUBDIR = "simulator"
SETTINGS_FILENAME = "settings.yaml"

_TEST_UNS_FILTER = "test/uns/#"
_SPARKPLUG_PREFIX = "spBv1.0"


# ---------------------------------------------------------------------------
# hierarchy in settings.yaml (plant.yaml is load-only fallback)
# ---------------------------------------------------------------------------


def _hierarchy_path(conf_dir: Path) -> Path:
    return conf_dir / PLANT_SUBDIR / PLANT_FILENAME


def _simulator_plant_path(conf_dir: Path) -> Path:
    return conf_dir / SIMULATOR_SUBDIR / PLANT_FILENAME


def _settings_path(conf_dir: Path) -> Path:
    return conf_dir / SETTINGS_FILENAME


def _hierarchy_mapping(block: Any) -> dict[str, Any] | None:
    if isinstance(block, dict) and block.get("enterprise") is not None:
        return block
    return None


def _hierarchy_from_settings_doc(doc: Any) -> dict[str, Any] | None:
    """Return `default.hierarchy`, then legacy `simulator.hierarchy`."""
    if not isinstance(doc, dict):
        return None
    default = doc.get("default")
    if isinstance(default, dict):
        hierarchy = _hierarchy_mapping(default.get("hierarchy"))
        if hierarchy is not None:
            return hierarchy
    simulator = doc.get("simulator")
    if isinstance(simulator, dict):
        return _hierarchy_mapping(simulator.get("hierarchy"))
    return None


def load_plant_tree(conf_dir: Path) -> HierarchyTree:
    """Load the ISA-95 tree from `conf_dir/settings.yaml` `default.hierarchy`.

    Falls back to `simulator.hierarchy`, then `hierarchy/plant.yaml`, then
    `simulator/plant.yaml` so an old checkout or a settings-only test fixture
    still loads.
    """
    settings_path = _settings_path(conf_dir)
    if settings_path.is_file():
        with settings_path.open("r", encoding="utf-8") as fh:
            settings_doc = yaml.safe_load(fh) or {}
        hierarchy = _hierarchy_from_settings_doc(settings_doc)
        if hierarchy is not None:
            return tree_from_mapping(hierarchy)

    path = _hierarchy_path(conf_dir)
    if not path.is_file():
        path = _simulator_plant_path(conf_dir)
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return tree_from_mapping(doc)


def save_plant_tree(conf_dir: Path, tree: HierarchyTree) -> None:
    """Persist `tree` to `conf_dir/settings.yaml` `default.hierarchy`.

    That is the same file production already ships. A leftover
    `simulator.hierarchy` is removed so the tree is not written twice. When
    settings.yaml is missing, write `hierarchy/plant.yaml` so a bare conf dir
    still round-trips. The write is atomic.
    """
    mapped = tree_to_mapping(tree)
    settings_path = _settings_path(conf_dir)
    if settings_path.is_file():
        yaml_rt = _rt_yaml()
        text = settings_path.read_text(encoding="utf-8")
        doc = yaml_rt.load(text) or {}
        if not isinstance(doc, dict):
            raise ValueError("settings.yaml must parse to a mapping at the top level")
        default = doc.get("default")
        if not isinstance(default, dict):
            default = {}
            doc["default"] = default
        default["hierarchy"] = mapped
        simulator = doc.get("simulator")
        if isinstance(simulator, dict) and "hierarchy" in simulator:
            del simulator["hierarchy"]
        stream = StringIO()
        yaml_rt.dump(doc, stream)
        _atomic_write_text(settings_path, stream.getvalue())
    else:
        path = _hierarchy_path(conf_dir)
        _atomic_write_yaml(path, mapped)


# ---------------------------------------------------------------------------
# settings.yaml
# ---------------------------------------------------------------------------


def _rt_yaml() -> YAML:
    """Round-trip loader/dumper so settings.yaml comments and key order survive a save."""
    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 4096
    yaml_rt.default_flow_style = False
    return yaml_rt


def apply_enterprise_to_settings(settings_text: str, enterprise: str) -> str:
    """Return `settings_text` with branding and mapper filters derived from `enterprise`.

    Sets `default.platform.organization_name` to `enterprise` and
    `default.platform.display_name` to `f"{enterprise} UNS"`. In the `graphdb`,
    `historian`, and `kafka_mapper` environments, any `mqtt.topics` entry of the
    form `Something/#` that is not `test/uns/#` and not Sparkplug
    (`spBv1.0...`) is replaced with `f"{enterprise}/#"`. `test/uns/#` and
    Sparkplug entries are kept; duplicate replaced filters collapse to one.
    """
    yaml_rt = _rt_yaml()
    doc = yaml_rt.load(settings_text) or {}
    if not isinstance(doc, dict):
        raise ValueError("settings.yaml must parse to a mapping at the top level")

    default = doc.get("default")
    if isinstance(default, dict):
        platform = default.get("platform")
        if not isinstance(platform, dict):
            platform = {}
            default["platform"] = platform
        platform["organization_name"] = enterprise
        platform["display_name"] = f"{enterprise} UNS"

    new_filter = f"{enterprise}/#"
    for env in ("graphdb", "historian", "kafka_mapper"):
        env_block = doc.get(env)
        if not isinstance(env_block, dict):
            continue
        mqtt = env_block.get("mqtt")
        if not isinstance(mqtt, dict):
            continue
        topics = mqtt.get("topics")
        if not isinstance(topics, list):
            continue
        rewritten = _rewrite_topic_filters(list(topics), new_filter)
        if list(topics) != rewritten:
            topics.clear()
            topics.extend(rewritten)

    stream = StringIO()
    yaml_rt.dump(doc, stream)
    return stream.getvalue()


def write_enterprise_settings(conf_dir: Path, enterprise: str) -> None:
    """Apply `apply_enterprise_to_settings` to `conf_dir/settings.yaml` in place."""
    path = conf_dir / SETTINGS_FILENAME
    text = path.read_text(encoding="utf-8")
    new_text = apply_enterprise_to_settings(text, enterprise)
    _atomic_write_text(path, new_text)


def _rewrite_topic_filters(topics: list[Any], new_filter: str) -> list[str]:
    rewritten: list[str] = []
    for topic in topics:
        topic_str = str(topic)
        if topic_str == _TEST_UNS_FILTER or topic_str.startswith(_SPARKPLUG_PREFIX):
            rewritten.append(topic_str)
        elif topic_str.endswith("/#"):
            rewritten.append(new_filter)
        else:
            rewritten.append(topic_str)
    # Collapse duplicates that arise when several `Something/#` filters map to
    # the same enterprise filter, preserving first-seen order.
    seen: set[str] = set()
    result: list[str] = []
    for topic in rewritten:
        if topic not in seen:
            seen.add(topic)
            result.append(topic)
    return result


# ---------------------------------------------------------------------------
# atomic write helpers
# ---------------------------------------------------------------------------


def _atomic_write_yaml(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False, default_flow_style=False)
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


__all__ = [
    "load_plant_tree",
    "save_plant_tree",
    "apply_enterprise_to_settings",
    "write_enterprise_settings",
]
