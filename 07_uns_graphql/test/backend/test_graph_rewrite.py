"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Rename an ISA-95 graph node when a hierarchy prefix changes.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from uns_graphql.backend.graphdb import GraphDB, rewrite_graph_prefix

# Isolated tree used by the fake session: E/S1/a plus sibling E/S2.
SEED_PATHS = ("E", "E/S1", "E/S2", "E/S1/a")


class _FakeResult:
    def __init__(self, record: dict | None) -> None:
        self._record = record

    async def single(self):
        return self._record


class _FakeSession:
    """In-memory ISA-95 tree: one node_name per segment, chained by parent.

    Interprets Cypher parameters (`segments`, `new_segment`) the production
    query must bind, and records the query text so tests can assert a SET of
    the last segment rather than a string-replace of a stored full topic.
    """

    def __init__(self, paths: tuple[str, ...] = SEED_PATHS) -> None:
        self.nodes: set[str] = set(paths)
        self.runs: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute_write(self, transaction_function, *args, **kwargs):
        return await transaction_function(self, *args, **kwargs)

    async def run(self, query, parameters=None, **kwargs):
        params = {**(parameters or {}), **kwargs}
        self.runs.append((query, params))
        return _FakeResult(self._apply(params))

    @property
    def last_query(self) -> str:
        return self.runs[-1][0]

    @property
    def last_params(self) -> dict:
        return self.runs[-1][1]

    def _apply(self, params: dict) -> dict | None:
        segments = params.get("segments")
        new_segment = params.get("new_segment")
        if not segments or new_segment is None:
            return None
        old_path = "/".join(segments)
        if old_path not in self.nodes:
            return None
        parent = old_path.rsplit("/", 1)[0] if "/" in old_path else None
        new_path = f"{parent}/{new_segment}" if parent is not None else new_segment
        if new_path in self.nodes and new_path != old_path:
            return {"status": "collision"}
        rewritten: set[str] = set()
        for path in self.nodes:
            if path == old_path or path.startswith(old_path + "/"):
                rewritten.add(new_path + path[len(old_path) :])
            else:
                rewritten.add(path)
        self.nodes = rewritten
        return {"status": "renamed"}


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.session_kwargs: dict | None = None

    def session(self, **kwargs):
        self.session_kwargs = kwargs
        return self._session


def _patch_driver(session: _FakeSession):
    driver = _FakeDriver(session)
    return patch.object(GraphDB, "get_graphdb_driver", new=AsyncMock(return_value=driver))


def _assert_sets_last_segment(session: _FakeSession, *, segments: list[str], new_segment: str) -> None:
    query = session.last_query
    compacted = " ".join(query.split())
    assert "SET" in compacted
    assert "node_name" in compacted
    assert "PARENT_OF" in compacted
    assert "REPLACE(" not in compacted.upper()
    assert session.last_params["segments"] == segments
    assert session.last_params["new_segment"] == new_segment


@pytest.mark.asyncio
async def test_rewrite_rejects_identical_prefixes():
    session = _FakeSession()
    with _patch_driver(session):
        with pytest.raises(ValueError):
            await rewrite_graph_prefix("E/S1", "E/S1")
    assert session.runs == []
    assert session.nodes == set(SEED_PATHS)


@pytest.mark.asyncio
async def test_rewrite_rejects_different_parent_paths():
    session = _FakeSession()
    with _patch_driver(session):
        with pytest.raises(ValueError):
            await rewrite_graph_prefix("E/S1", "F/Nord")
    assert session.runs == []


@pytest.mark.asyncio
async def test_rewrite_renames_last_segment_sibling_unchanged():
    session = _FakeSession()
    with _patch_driver(session):
        changed = await rewrite_graph_prefix("E/S1", "E/Nord")
    assert changed == 1
    assert session.nodes == {"E", "E/Nord", "E/S2", "E/Nord/a"}
    _assert_sets_last_segment(session, segments=["E", "S1"], new_segment="Nord")


@pytest.mark.asyncio
async def test_rewrite_raises_when_sibling_already_has_new_name():
    session = _FakeSession((*SEED_PATHS, "E/Nord"))
    with _patch_driver(session):
        with pytest.raises(ValueError):
            await rewrite_graph_prefix("E/S1", "E/Nord")
    assert "E/S1" in session.nodes
    assert "E/Nord" in session.nodes
    assert "E/S2" in session.nodes


@pytest.mark.asyncio
async def test_rewrite_returns_zero_when_old_node_absent():
    session = _FakeSession(("E", "E/S2"))
    with _patch_driver(session):
        changed = await rewrite_graph_prefix("E/S1", "E/Nord")
    assert changed == 0
    assert session.nodes == {"E", "E/S2"}


@pytest.mark.asyncio
async def test_rewrite_renames_enterprise_root():
    session = _FakeSession(SEED_PATHS)
    with _patch_driver(session):
        changed = await rewrite_graph_prefix("E", "Nord")
    assert changed == 1
    assert session.nodes == {"Nord", "Nord/S1", "Nord/S2", "Nord/S1/a"}
    _assert_sets_last_segment(session, segments=["E"], new_segment="Nord")


def _enterprise(kind: str) -> str:
    """Fresh root name per invocation so parallel xdist workers cannot share a tree."""
    return f"pytest-graph-rewrite-{kind}-{uuid4().hex}"


SEED_CYPHER = """
CREATE (e:ENTERPRISE {node_name: $enterprise})
CREATE (e)-[:PARENT_OF]->(s1:FACILITY {node_name: 'S1'})
CREATE (e)-[:PARENT_OF]->(s2:FACILITY {node_name: 'S2'})
CREATE (s1)-[:PARENT_OF]->(a:AREA {node_name: 'a'})
"""
WIPE_CYPHER = """
MATCH (e {node_name: $enterprise})
OPTIONAL MATCH (e)-[:PARENT_OF*0..10]->(n)
DETACH DELETE e, n
"""
SITE_NAMES_CYPHER = """
MATCH (e {node_name: $enterprise})-[:PARENT_OF]->(site)
RETURN site.node_name AS name ORDER BY name
"""
CHILD_NAMES_CYPHER = """
MATCH (e {node_name: $enterprise})-[:PARENT_OF]->(site {node_name: $site})-[:PARENT_OF]->(child)
RETURN child.node_name AS name ORDER BY name
"""


async def _run(session, query: str, **params):
    result = await session.run(query, **params)
    return await result.consume()


async def _values(session, query: str, **params) -> list:
    result = await session.run(query, **params)
    return [record["name"] async for record in result]


@pytest.mark.asyncio
@pytest.mark.integrationtest
@pytest.mark.xdist_group(name="graphql_graph_rewrite")
async def test_rewrite_graph_prefix_renames_node_in_neo4j():
    enterprise = _enterprise("rename")
    driver = await GraphDB.get_graphdb_driver()
    try:
        async with driver.session() as session:
            await _run(session, WIPE_CYPHER, enterprise=enterprise)
            await _run(session, SEED_CYPHER, enterprise=enterprise)
        try:
            changed = await rewrite_graph_prefix(f"{enterprise}/S1", f"{enterprise}/Nord")
            assert changed == 1
            async with driver.session() as session:
                assert await _values(session, SITE_NAMES_CYPHER, enterprise=enterprise) == ["Nord", "S2"]
                assert await _values(session, CHILD_NAMES_CYPHER, enterprise=enterprise, site="Nord") == ["a"]
        finally:
            async with driver.session() as session:
                await _run(session, WIPE_CYPHER, enterprise=enterprise)
    finally:
        await GraphDB.release_graphdb_driver()


@pytest.mark.asyncio
@pytest.mark.integrationtest
@pytest.mark.xdist_group(name="graphql_graph_rewrite")
async def test_rewrite_graph_prefix_collision_in_neo4j():
    enterprise = _enterprise("collision")
    driver = await GraphDB.get_graphdb_driver()
    try:
        async with driver.session() as session:
            await _run(session, WIPE_CYPHER, enterprise=enterprise)
            await _run(session, SEED_CYPHER, enterprise=enterprise)
            await _run(
                session,
                """
                MATCH (e {node_name: $enterprise})
                CREATE (e)-[:PARENT_OF]->(:FACILITY {node_name: 'Nord'})
                """,
                enterprise=enterprise,
            )
        try:
            with pytest.raises(ValueError):
                await rewrite_graph_prefix(f"{enterprise}/S1", f"{enterprise}/Nord")
            async with driver.session() as session:
                assert await _values(session, SITE_NAMES_CYPHER, enterprise=enterprise) == ["Nord", "S1", "S2"]
        finally:
            async with driver.session() as session:
                await _run(session, WIPE_CYPHER, enterprise=enterprise)
    finally:
        await GraphDB.release_graphdb_driver()

