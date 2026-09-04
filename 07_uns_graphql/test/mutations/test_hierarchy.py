"""Saving the plant hierarchy through the schema, with rewrites and conf faked.

No live Neo4j or historian: the rewrite functions are replaced, and plant.yaml /
settings.yaml live in a tmp conf_dir. Auth cells live in test/auth; these tests
are about order, files, and the migrate job.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from uns_graphql.auth.context import CONTEXT_KEY
from uns_graphql.auth.token import Identity
from uns_graphql.uns_graphql_app import UNSGraphql

ADMIN = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000099",
        username="ada.admin",
        roles=frozenset({"admin"}),
    )
}
VIEWER = {
    CONTEXT_KEY: Identity(
        subject="00000000-0000-0000-0000-000000000003",
        username="val.viewer",
        roles=frozenset({"viewer"}),
    )
}

PLANT_YAML = """\
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

SETTINGS_YAML = """\
default:
  platform:
    instance_name: "Instance01"
    organization_name: "OldCo"
    display_name: "OldCo UNS"
graphdb:
  mqtt:
    topics: ["test/uns/#", "OldCo/#"]
historian:
  mqtt:
    topics: ["test/uns/#", "OldCo/#"]
kafka_mapper:
  mqtt:
    topics: ["test/uns/#", "OldCo/#"]
"""

GET_HIERARCHY = """
    { getHierarchy { enterprise sites { name areas { name kind lines { name cells } } } } }
"""

SAVE_HIERARCHY = """
    mutation Save($tree: HierarchyTreeInput!, $renames: [PrefixRenameInput!]!) {
        saveHierarchy(tree: $tree, renames: $renames) {
            tree { enterprise sites { name areas { name kind lines { name cells } } } }
            job { oldPrefix newPrefix status rewritten error }
        }
    }
"""

RETRY_MIGRATE = """
    mutation { retryHierarchyMigrate { oldPrefix newPrefix status rewritten error } }
"""

TREE_SITE1 = {
    "enterprise": "OldCo",
    "sites": [
        {
            "name": "Site1",
            "areas": [
                {
                    "name": "RawWater",
                    "kind": "production",
                    "lines": [{"name": "Train1", "cells": ["V101", "V102"]}],
                }
            ],
        }
    ],
}

TREE_NORD = {
    "enterprise": "OldCo",
    "sites": [
        {
            "name": "Nord",
            "areas": [
                {
                    "name": "RawWater",
                    "kind": "production",
                    "lines": [{"name": "Train1", "cells": ["V101", "V102"]}],
                }
            ],
        }
    ],
}

SITE_RENAME = [{"oldPrefix": "OldCo/Site1", "newPrefix": "OldCo/Nord"}]

REWRITE_HISTORIAN = "uns_graphql.mutations.hierarchy._rewrite_historian"
REWRITE_GRAPH = "uns_graphql.mutations.hierarchy._rewrite_graph"
RESEED = "uns_graphql.mutations.hierarchy._reseed"
CONF_DIR = "uns_graphql.mutations.hierarchy._conf_dir"


def _write_conf(conf_dir: Path) -> None:
    (conf_dir / "simulator").mkdir(parents=True, exist_ok=True)
    (conf_dir / "simulator" / "plant.yaml").write_text(PLANT_YAML, encoding="utf-8")
    (conf_dir / "settings.yaml").write_text(SETTINGS_YAML, encoding="utf-8")


def _job_path(conf_dir: Path) -> Path:
    return conf_dir / "simulator" / "hierarchy_job.yaml"


def _write_job(conf_dir: Path, **fields: object) -> None:
    _job_path(conf_dir).write_text(yaml.safe_dump(fields), encoding="utf-8")


def _read_job(conf_dir: Path) -> dict:
    return yaml.safe_load(_job_path(conf_dir).read_text(encoding="utf-8")) or {}


def _read_plant(conf_dir: Path) -> dict:
    return yaml.safe_load((conf_dir / "simulator" / "plant.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def conf_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_conf(tmp_path)
    monkeypatch.setattr(CONF_DIR, lambda: tmp_path)
    return tmp_path


@pytest.mark.asyncio(loop_scope="function")
async def test_get_hierarchy_reads_plant_yaml(conf_dir: Path):  # noqa: ARG001
    result = await UNSGraphql.schema.execute(GET_HIERARCHY)

    assert result.errors is None
    tree = result.data["getHierarchy"]
    assert tree["enterprise"] == "OldCo"
    assert tree["sites"][0]["name"] == "Site1"
    assert tree["sites"][0]["areas"][0]["lines"][0]["cells"] == ["V101", "V102"]


@pytest.mark.asyncio(loop_scope="function")
async def test_save_hierarchy_writes_yaml_and_reseeds_without_migrate(conf_dir: Path):
    added = {
        "enterprise": "OldCo",
        "sites": [
            {
                "name": "Site1",
                "areas": [
                    {
                        "name": "RawWater",
                        "kind": "production",
                        "lines": [{"name": "Train1", "cells": ["V101", "V102", "V103"]}],
                    }
                ],
            }
        ],
    }
    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock) as historian,
        patch(REWRITE_GRAPH, new_callable=AsyncMock) as graph,
        patch(RESEED, new_callable=AsyncMock) as reseed,
    ):
        result = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": added, "renames": []},
            context_value=ADMIN,
        )

    assert result.errors is None
    saved = result.data["saveHierarchy"]
    assert saved["tree"]["sites"][0]["areas"][0]["lines"][0]["cells"] == ["V101", "V102", "V103"]
    assert saved["job"]["status"] == "idle"
    plant = _read_plant(conf_dir)
    assert plant["sites"][0]["areas"][0]["lines"][0]["cells"] == ["V101", "V102", "V103"]
    settings = yaml.safe_load((conf_dir / "settings.yaml").read_text(encoding="utf-8"))
    assert settings["default"]["platform"]["organization_name"] == "OldCo"
    reseed.assert_awaited()
    historian.assert_not_awaited()
    graph.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_save_hierarchy_migrates_historian_then_graph(conf_dir: Path):
    order: list[str] = []

    async def historian(old_prefix: str, new_prefix: str) -> int:
        order.append(f"historian:{old_prefix}->{new_prefix}")
        return 4

    async def graph(old_prefix: str, new_prefix: str) -> int:
        order.append(f"graph:{old_prefix}->{new_prefix}")
        return 1

    with (
        patch(REWRITE_HISTORIAN, side_effect=historian),
        patch(REWRITE_GRAPH, side_effect=graph),
        patch(RESEED, new_callable=AsyncMock),
    ):
        result = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": TREE_NORD, "renames": SITE_RENAME},
            context_value=ADMIN,
        )

    assert result.errors is None
    job = result.data["saveHierarchy"]["job"]
    assert job["status"] == "done"
    assert job["oldPrefix"] == "OldCo/Site1"
    assert job["newPrefix"] == "OldCo/Nord"
    assert job["rewritten"] == 5
    assert _read_plant(conf_dir)["sites"][0]["name"] == "Nord"
    assert order == ["historian:OldCo/Site1->OldCo/Nord", "graph:OldCo/Site1->OldCo/Nord"]
    stored = _read_job(conf_dir)
    assert stored["status"] == "done"


@pytest.mark.asyncio(loop_scope="function")
async def test_save_hierarchy_rejects_renames_while_a_job_is_running(conf_dir: Path):
    _write_job(conf_dir, status="running", old_prefix="OldCo/Site1", new_prefix="OldCo/Nord")
    original = _read_plant(conf_dir)

    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock) as historian,
        patch(REWRITE_GRAPH, new_callable=AsyncMock) as graph,
        patch(RESEED, new_callable=AsyncMock) as reseed,
    ):
        result = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": TREE_NORD, "renames": SITE_RENAME},
            context_value=ADMIN,
        )

    assert result.errors
    message = result.errors[0].message
    assert "renames" in message
    assert result.errors[0].extensions["field"] == "renames"
    assert _read_plant(conf_dir) == original
    historian.assert_not_awaited()
    graph.assert_not_awaited()
    reseed.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_save_hierarchy_allows_empty_renames_while_a_job_is_running(conf_dir: Path):
    _write_job(conf_dir, status="running", old_prefix="OldCo/Site1", new_prefix="OldCo/Nord")

    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock),
        patch(REWRITE_GRAPH, new_callable=AsyncMock),
        patch(RESEED, new_callable=AsyncMock),
    ):
        result = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": TREE_SITE1, "renames": []},
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveHierarchy"]["job"]["status"] == "running"


@pytest.mark.asyncio(loop_scope="function")
async def test_failed_migrate_does_not_roll_back_yaml(conf_dir: Path):
    async def boom(_old: str, _new: str) -> int:
        raise RuntimeError("graph unreachable")

    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock, return_value=2),
        patch(REWRITE_GRAPH, side_effect=boom),
        patch(RESEED, new_callable=AsyncMock),
    ):
        result = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": TREE_NORD, "renames": SITE_RENAME},
            context_value=ADMIN,
        )

    assert result.errors is None
    job = result.data["saveHierarchy"]["job"]
    assert job["status"] == "failed"
    assert "graph unreachable" in (job["error"] or "")
    assert _read_plant(conf_dir)["sites"][0]["name"] == "Nord"
    assert _read_job(conf_dir)["status"] == "failed"


@pytest.mark.asyncio(loop_scope="function")
async def test_retry_hierarchy_migrate_reruns_a_failed_job(conf_dir: Path):
    _write_job(
        conf_dir,
        status="failed",
        old_prefix="OldCo/Site1",
        new_prefix="OldCo/Nord",
        rewritten=0,
        error="graph unreachable",
    )

    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock, return_value=4) as historian,
        patch(REWRITE_GRAPH, new_callable=AsyncMock, return_value=1) as graph,
        patch(RESEED, new_callable=AsyncMock),
    ):
        result = await UNSGraphql.schema.execute(RETRY_MIGRATE, context_value=ADMIN)

    assert result.errors is None
    job = result.data["retryHierarchyMigrate"]
    assert job["status"] == "done"
    assert job["rewritten"] == 5
    historian.assert_awaited_once_with("OldCo/Site1", "OldCo/Nord")
    graph.assert_awaited_once_with("OldCo/Site1", "OldCo/Nord")


@pytest.mark.asyncio(loop_scope="function")
async def test_a_viewer_cannot_save_hierarchy(conf_dir: Path):  # noqa: ARG001
    result = await UNSGraphql.schema.execute(
        SAVE_HIERARCHY,
        variable_values={"tree": TREE_SITE1, "renames": []},
        context_value=VIEWER,
    )

    assert result.errors
    assert "admin" in result.errors[0].message
    assert "saveHierarchy" in result.errors[0].message


@pytest.mark.asyncio(loop_scope="function")
async def test_a_viewer_cannot_retry_hierarchy_migrate(conf_dir: Path):  # noqa: ARG001
    result = await UNSGraphql.schema.execute(RETRY_MIGRATE, context_value=VIEWER)

    assert result.errors
    assert "admin" in result.errors[0].message
    assert "retryHierarchyMigrate" in result.errors[0].message
