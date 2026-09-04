"""Read/write `conf/simulator/plant.yaml` and derive enterprise branding/mapper filters.

The shipped `plant.yaml` is the reviewable source of truth for the ISA-95 tree.
The console writes it through GraphQL on a hierarchy save, then derives the
branding and mapper topic filters in `conf/settings.yaml` from the enterprise
name. This module owns the YAML I/O so the rest of `uns_model` stays free of
file concerns.

Sites are stored as a list of objects (`{name, areas: [...]}`) because that is
the shape the WTP simulator and `tree_from_mapping` already consume. The
companion `tree_to_sites_mapping` returns a dict-of-names for in-memory rename
operations; that dict is never written to disk by this module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from uns_model.hierarchy import (
    DEFAULT_AREA_KIND,
    HierarchyArea,
    HierarchyLine,
    HierarchySite,
    HierarchyTree,
    tree_from_mapping,
)

PLANT_SUBDIR = "simulator"
PLANT_FILENAME = "plant.yaml"
SETTINGS_FILENAME = "settings.yaml"

_TEST_UNS_FILTER = "test/uns/#"
_SPARKPLUG_PREFIX = "spBv1.0"


# ---------------------------------------------------------------------------
# plant.yaml
# ---------------------------------------------------------------------------


def load_plant_tree(conf_dir: Path) -> HierarchyTree:
    """Load the ISA-95 tree from `conf_dir/simulator/plant.yaml`."""
    path = conf_dir / PLANT_SUBDIR / PLANT_FILENAME
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return tree_from_mapping(doc)


def save_plant_tree(conf_dir: Path, tree: HierarchyTree) -> None:
    """Persist `tree` to `conf_dir/simulator/plant.yaml`.

    Loads the existing document so `plant`, `profiles.wtp.tier_scale`, and
    `profiles.wtp.families` survive a save that only changes the hierarchy.
    `enterprise` and `sites` are replaced, and `profiles.wtp.sites` is reset to
    the new site names so a Site1 rename does not leave a dead profile filter.
    The write is atomic: a `.tmp` file is replaced into place.
    """
    path = conf_dir / PLANT_SUBDIR / PLANT_FILENAME
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            doc: dict[str, Any] = yaml.safe_load(fh) or {}
    else:
        doc = {}

    doc["enterprise"] = tree.enterprise
    doc["sites"] = [_site_to_mapping(site) for site in tree.sites]

    profiles = doc.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        doc["profiles"] = profiles
    wtp = profiles.get("wtp")
    if not isinstance(wtp, dict):
        wtp = {}
        profiles["wtp"] = wtp
    wtp["sites"] = [site.name for site in tree.sites]

    _atomic_write_yaml(path, doc)


def _site_to_mapping(site: HierarchySite) -> dict[str, Any]:
    return {
        "name": site.name,
        "areas": [_area_to_mapping(area) for area in site.areas],
    }


def _area_to_mapping(area: HierarchyArea) -> dict[str, Any]:
    return {
        "name": area.name,
        "kind": area.kind or DEFAULT_AREA_KIND,
        "lines": [_line_to_mapping(line) for line in area.lines],
    }


def _line_to_mapping(line: HierarchyLine) -> dict[str, Any]:
    return {"name": line.name, "cells": list(line.cells)}


# ---------------------------------------------------------------------------
# settings.yaml
# ---------------------------------------------------------------------------


def apply_enterprise_to_settings(settings_text: str, enterprise: str) -> str:
    """Return `settings_text` with branding and mapper filters derived from `enterprise`.

    Sets `default.platform.organization_name` to `enterprise` and
    `default.platform.display_name` to `f"{enterprise} UNS"`. In the `graphdb`,
    `historian`, and `kafka_mapper` environments, any `mqtt.topics` entry of the
    form `Something/#` that is not `test/uns/#` and not Sparkplug
    (`spBv1.0...`) is replaced with `f"{enterprise}/#"`. `test/uns/#` and
    Sparkplug entries are kept; duplicate replaced filters collapse to one.
    """
    doc = yaml.safe_load(settings_text) or {}
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
        mqtt["topics"] = _rewrite_topic_filters(topics, new_filter)

    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)


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
