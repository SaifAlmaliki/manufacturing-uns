"""Saving the plant hierarchy through the schema, with rewrites and conf faked.

No live Neo4j or historian: the rewrite functions are replaced, and
settings.yaml / plant.yaml live in a tmp conf_dir. Auth cells live in test/auth;
these tests are about order, files, and the migrate job.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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
    { getHierarchy { enterprise sites { name areas { name kind lines { name cells { name machines } } } } } }
"""

SAVE_HIERARCHY = """
    mutation Save($tree: HierarchyTreeInput!, $renames: [PrefixRenameInput!]!) {
        saveHierarchy(tree: $tree, renames: $renames) {
            tree { enterprise sites { name areas { name kind lines { name cells { name machines } } } } }
            job { oldPrefix newPrefix status rewritten error }
        }
    }
"""

RETRY_MIGRATE = """
    mutation { retryHierarchyMigrate { oldPrefix newPrefix status rewritten error } }
"""

def _cells(*names: str) -> list[dict]:
    return [{"name": name, "machines": []} for name in names]


TREE_SITE1 = {
    "enterprise": "OldCo",
    "sites": [
        {
            "name": "Site1",
            "areas": [
                {
                    "name": "RawWater",
                    "kind": "production",
                    "lines": [{"name": "Train1", "cells": _cells("V101", "V102")}],
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
                    "lines": [{"name": "Train1", "cells": _cells("V101", "V102")}],
                }
            ],
        }
    ],
}

SITE_RENAME = [{"oldPrefix": "OldCo/Site1", "newPrefix": "OldCo/Nord"}]
TWO_SITE_RENAMES = [
    {"oldPrefix": "OldCo/Site1", "newPrefix": "OldCo/Nord"},
    {"oldPrefix": "OldCo/Site2", "newPrefix": "OldCo/Sud"},
]

REWRITE_HISTORIAN = "uns_graphql.mutations.hierarchy._rewrite_historian"
REWRITE_GRAPH = "uns_graphql.mutations.hierarchy._rewrite_graph"
RESEED = "uns_graphql.mutations.hierarchy._reseed"
CONF_DIR = "uns_graphql.mutations.hierarchy._conf_dir"

TWO_SITE_PLANT_YAML = """\
enterprise: OldCo
sites:
  - name: Site1
    areas:
      - name: RawWater
        kind: production
        lines:
          - name: Train1
            cells: [V101, V102]
  - name: Site2
    areas:
      - name: RawWater
        kind: production
        lines:
          - name: Train1
            cells: [V201]
plant: {}
profiles:
  wtp:
    tier_scale: 1.0
    sites: [Site1, Site2]
    families: [wtp]
"""

TREE_TWO_RENAMED = {
    "enterprise": "OldCo",
    "sites": [
        {
            "name": "Nord",
            "areas": [
                {
                    "name": "RawWater",
                    "kind": "production",
                    "lines": [{"name": "Train1", "cells": _cells("V101", "V102")}],
                }
            ],
        },
        {
            "name": "Sud",
            "areas": [
                {
                    "name": "RawWater",
                    "kind": "production",
                    "lines": [{"name": "Train1", "cells": _cells("V201")}],
                }
            ],
        },
    ],
}


def _fresh_started_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_started_at() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _write_conf(conf_dir: Path, plant: str = PLANT_YAML) -> None:
    (conf_dir / "hierarchy").mkdir(parents=True, exist_ok=True)
    (conf_dir / "hierarchy" / "plant.yaml").write_text(plant, encoding="utf-8")
    (conf_dir / "settings.yaml").write_text(SETTINGS_YAML, encoding="utf-8")


def _job_path(conf_dir: Path) -> Path:
    return conf_dir / "hierarchy" / "hierarchy_job.yaml"


def _write_job(conf_dir: Path, **fields: object) -> None:
    path = _job_path(conf_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(fields), encoding="utf-8")


def _read_job(conf_dir: Path) -> dict:
    return yaml.safe_load(_job_path(conf_dir).read_text(encoding="utf-8")) or {}


def _read_plant(conf_dir: Path) -> dict:
    settings = yaml.safe_load((conf_dir / "settings.yaml").read_text(encoding="utf-8")) or {}
    default = settings.get("default") or {}
    hierarchy = default.get("hierarchy") if isinstance(default, dict) else None
    if not (isinstance(hierarchy, dict) and hierarchy.get("enterprise") is not None):
        hierarchy = (settings.get("simulator") or {}).get("hierarchy")
    if isinstance(hierarchy, dict) and hierarchy.get("enterprise") is not None:
        return hierarchy
    return yaml.safe_load((conf_dir / "hierarchy" / "plant.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def conf_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_conf(tmp_path)
    monkeypatch.setattr(CONF_DIR, lambda: tmp_path)
    return tmp_path


@pytest.mark.asyncio(loop_scope="function")
async def test_get_hierarchy_reads_plant_yaml(conf_dir: Path):  # noqa: ARG001
    result = await UNSGraphql.schema.execute(GET_HIERARCHY, context_value=ADMIN)

    assert result.errors is None
    tree = result.data["getHierarchy"]
    assert tree["enterprise"] == "OldCo"
    assert tree["sites"][0]["name"] == "Site1"
    assert tree["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": []},
        {"name": "V102", "machines": []},
    ]


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
                        "lines": [{"name": "Train1", "cells": _cells("V101", "V102", "V103")}],
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
    assert saved["tree"]["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": []},
        {"name": "V102", "machines": []},
        {"name": "V103", "machines": []},
    ]
    assert saved["job"]["status"] == "idle"
    plant = _read_plant(conf_dir)
    assert plant["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": []},
        {"name": "V102", "machines": []},
        {"name": "V103", "machines": []},
    ]
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
    _write_job(
        conf_dir,
        status="running",
        old_prefix="OldCo/Site1",
        new_prefix="OldCo/Nord",
        started_at=_fresh_started_at(),
        pending=[{"old": "OldCo/Site1", "new": "OldCo/Nord"}],
    )
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
    _write_job(
        conf_dir,
        status="running",
        old_prefix="OldCo/Site1",
        new_prefix="OldCo/Nord",
        started_at=_fresh_started_at(),
        pending=[{"old": "OldCo/Site1", "new": "OldCo/Nord"}],
    )

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
async def test_retry_adopts_a_stale_running_job_without_deleting_the_file(conf_dir: Path):
    _write_job(
        conf_dir,
        status="running",
        old_prefix="OldCo/Site1",
        new_prefix="OldCo/Nord",
        started_at=_stale_started_at(),
        pending=[{"old": "OldCo/Site1", "new": "OldCo/Nord"}],
        rewritten=0,
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
    assert _job_path(conf_dir).is_file()
    assert _read_job(conf_dir)["status"] == "done"


@pytest.mark.asyncio(loop_scope="function")
async def test_stale_running_job_is_reported_as_failed_so_the_console_can_retry(
    conf_dir: Path,
):
    _write_job(
        conf_dir,
        status="running",
        old_prefix="OldCo/Site1",
        new_prefix="OldCo/Nord",
        started_at=_stale_started_at(),
        pending=[{"old": "OldCo/Site1", "new": "OldCo/Nord"}],
    )

    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock) as historian,
        patch(REWRITE_GRAPH, new_callable=AsyncMock),
        patch(RESEED, new_callable=AsyncMock),
    ):
        result = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": TREE_SITE1, "renames": []},
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveHierarchy"]["job"]["status"] == "failed"
    historian.assert_not_awaited()


@pytest.mark.asyncio(loop_scope="function")
async def test_failed_mid_batch_keeps_remaining_renames_and_retry_resumes(conf_dir: Path):
    _write_conf(conf_dir, TWO_SITE_PLANT_YAML)

    async def boom_on_second(old_prefix: str, new_prefix: str) -> int:
        if old_prefix.endswith("Site2"):
            raise RuntimeError("historian unavailable")
        return 2

    with (
        patch(REWRITE_HISTORIAN, side_effect=boom_on_second),
        patch(REWRITE_GRAPH, new_callable=AsyncMock, return_value=1),
        patch(RESEED, new_callable=AsyncMock),
    ):
        failed = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": TREE_TWO_RENAMED, "renames": TWO_SITE_RENAMES},
            context_value=ADMIN,
        )

    assert failed.errors is None
    assert failed.data["saveHierarchy"]["job"]["status"] == "failed"
    stored = _read_job(conf_dir)
    assert stored["pending"] == [
        {"old": "OldCo/Site2", "new": "OldCo/Sud"},
    ]

    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock, return_value=2) as historian,
        patch(REWRITE_GRAPH, new_callable=AsyncMock, return_value=1) as graph,
        patch(RESEED, new_callable=AsyncMock),
    ):
        retried = await UNSGraphql.schema.execute(RETRY_MIGRATE, context_value=ADMIN)

    assert retried.errors is None
    assert retried.data["retryHierarchyMigrate"]["status"] == "done"
    historian.assert_awaited_once_with("OldCo/Site2", "OldCo/Sud")
    graph.assert_awaited_once_with("OldCo/Site2", "OldCo/Sud")


@pytest.mark.asyncio(loop_scope="function")
async def test_save_writes_running_before_reseed(conf_dir: Path):
    saw_running = asyncio.Event()
    release = asyncio.Event()

    async def slow_reseed(_tree) -> None:
        job = _read_job(conf_dir)
        if job.get("status") == "running":
            saw_running.set()
        await release.wait()

    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock, return_value=1),
        patch(REWRITE_GRAPH, new_callable=AsyncMock, return_value=1),
        patch(RESEED, side_effect=slow_reseed),
    ):
        task = asyncio.create_task(
            UNSGraphql.schema.execute(
                SAVE_HIERARCHY,
                variable_values={"tree": TREE_NORD, "renames": SITE_RENAME},
                context_value=ADMIN,
            )
        )
        await asyncio.wait_for(saw_running.wait(), timeout=2)
        stored = _read_job(conf_dir)
        assert stored["status"] == "running"
        assert stored["pending"] == [{"old": "OldCo/Site1", "new": "OldCo/Nord"}]
        release.set()
        result = await task

    assert result.errors is None
    assert result.data["saveHierarchy"]["job"]["status"] == "done"


@pytest.mark.asyncio(loop_scope="function")
async def test_save_hierarchy_persists_authored_machines(conf_dir: Path):
    tree = {
        "enterprise": "OldCo",
        "sites": [
            {
                "name": "Site1",
                "areas": [
                    {
                        "name": "RawWater",
                        "kind": "production",
                        "lines": [
                            {
                                "name": "Train1",
                                "cells": [{"name": "V101", "machines": ["Dryer"]}],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    with (
        patch(REWRITE_HISTORIAN, new_callable=AsyncMock),
        patch(REWRITE_GRAPH, new_callable=AsyncMock),
        patch(RESEED, new_callable=AsyncMock) as reseed,
    ):
        result = await UNSGraphql.schema.execute(
            SAVE_HIERARCHY,
            variable_values={"tree": tree, "renames": []},
            context_value=ADMIN,
        )

    assert result.errors is None
    cells = result.data["saveHierarchy"]["tree"]["sites"][0]["areas"][0]["lines"][0]["cells"]
    assert cells == [{"name": "V101", "machines": ["Dryer"]}]
    assert _read_plant(conf_dir)["sites"][0]["areas"][0]["lines"][0]["cells"] == [
        {"name": "V101", "machines": ["Dryer"]}
    ]
    reseed.assert_awaited()


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
