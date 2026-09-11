"""Integration tests for edge catalog repository behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uns_config.edge_contracts import EdgeReport
from uns_model.connectivity import ConnectivityRepository, ConnectivityServerSpec
from uns_model.edge_repository import (
    EdgeIdentity,
    EdgeLeaseRejected,
    EdgeRepository,
    EdgeRevisionConflict,
    EdgeScopeViolation,
)
from uns_model.engine import Database
from uns_model.model_config import ModelConfig
from uns_model.tables import ConnectivityServer

TEST_EDGE_A = "pytest-edge-a"
TEST_EDGE_B = "pytest-edge-b"
TEST_SERVER = "pytest-edge-server"


def _desired_document(**overrides) -> dict:
    document = {
        "contract_version": 1,
        "adapters": [],
        "required_route_revision": 1,
        "secret_refs": [],
        "deleted_adapter_ids": [],
    }
    document.update(overrides)
    return document


def _report(
    *,
    edge_id: str,
    boot_id: str,
    report_sequence: int,
    desired_revision: int,
    applied_revision: int,
    applied_digest: str,
    phase: str = "applied",
) -> EdgeReport:
    return EdgeReport(
        edge_id=edge_id,
        boot_id=boot_id,
        report_sequence=report_sequence,
        desired_revision=desired_revision,
        applied_revision=applied_revision,
        applied_digest=applied_digest,
        phase=phase,
        adapter_results=(),
        last_error_code=None,
        versions={},
        capabilities={},
    )


async def _clean(database: Database) -> None:
    async with database.begin() as connection:
        await connection.execute(
            text("DELETE FROM console.connectivity_servers WHERE id = :server_id"),
            {"server_id": TEST_SERVER},
        )
        for edge_id in (TEST_EDGE_A, TEST_EDGE_B):
            await connection.execute(
                text("DELETE FROM edge.devices WHERE edge_id = :edge_id"),
                {"edge_id": edge_id},
            )


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def database():
    config = ModelConfig.from_settings()
    assert config.is_valid()
    db = Database.from_config(config)
    yield db
    await db.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def edge_repo(database: Database):
    await _clean(database)
    repo = EdgeRepository(database)
    await repo.register_device(TEST_EDGE_A)
    await repo.register_device(TEST_EDGE_B)
    yield repo
    await _clean(database)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_save_expected_three_becomes_revision_four(edge_repo: EdgeRepository):
    for expected in (0, 1, 2):
        await edge_repo.save_desired(TEST_EDGE_A, expected, _desired_document())
    saved = await edge_repo.save_desired(TEST_EDGE_A, 3, _desired_document())
    assert saved.revision == 4


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_second_save_at_same_expected_revision_conflicts(edge_repo: EdgeRepository):
    for expected in (0, 1, 2):
        await edge_repo.save_desired(TEST_EDGE_A, expected, _desired_document())
    await edge_repo.save_desired(TEST_EDGE_A, 3, _desired_document())
    with pytest.raises(EdgeRevisionConflict):
        await edge_repo.save_desired(TEST_EDGE_A, 3, _desired_document())
    latest = await edge_repo.latest_desired(TEST_EDGE_A)
    assert latest is not None
    assert latest.revision == 4


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_connection_edit_and_snapshot_rollback_together(database: Database, edge_repo: EdgeRepository):
    async with database.engine.connect() as connection:
        session = AsyncSession(bind=connection, expire_on_commit=False)
        transaction = await connection.begin()
        try:
            session.add(
                ConnectivityServer(
                    id=TEST_SERVER,
                    name="Legacy OPC",
                    protocol="opc_ua",
                    endpoint="opc.tcp://127.0.0.1:4840",
                )
            )
            await edge_repo.save_desired(TEST_EDGE_A, 0, _desired_document(), session=session)
            with pytest.raises(EdgeRevisionConflict):
                await edge_repo.save_desired(TEST_EDGE_A, 0, _desired_document(), session=session)
        finally:
            await transaction.rollback()
            await session.close()

    async with database.session() as session:
        row = (
            await session.execute(select(ConnectivityServer).where(ConnectivityServer.id == TEST_SERVER))
        ).scalar_one_or_none()
        assert row is None
        desired_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM edge.desired_configurations WHERE edge_id = :edge_id"),
                {"edge_id": TEST_EDGE_A},
            )
        ).scalar_one()
        assert desired_count == 0


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_edge_a_cannot_read_or_report_for_edge_b(edge_repo: EdgeRepository):
    await edge_repo.save_desired(TEST_EDGE_A, 0, _desired_document())
    assert await edge_repo.latest_desired(TEST_EDGE_B) is None

    lease = await edge_repo.acquire_lease(TEST_EDGE_A, "boot-a")
    desired = await edge_repo.latest_desired(TEST_EDGE_A)
    assert desired is not None
    report = _report(
        edge_id=TEST_EDGE_B,
        boot_id=lease.boot_id,
        report_sequence=1,
        desired_revision=desired.revision,
        applied_revision=desired.revision,
        applied_digest=desired.digest,
    )
    with pytest.raises(EdgeScopeViolation):
        await edge_repo.accept_report(EdgeIdentity(TEST_EDGE_A), lease, report)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_stale_report_does_not_mark_new_revision_applied(edge_repo: EdgeRepository):
    first = await edge_repo.save_desired(TEST_EDGE_A, 0, _desired_document())
    lease = await edge_repo.acquire_lease(TEST_EDGE_A, "boot-a")
    await edge_repo.accept_report(
        EdgeIdentity(TEST_EDGE_A),
        lease,
        _report(
            edge_id=TEST_EDGE_A,
            boot_id=lease.boot_id,
            report_sequence=1,
            desired_revision=first.revision,
            applied_revision=first.revision,
            applied_digest=first.digest,
        ),
    )
    latest = await edge_repo.save_desired(TEST_EDGE_A, 1, _desired_document())
    stale = _report(
        edge_id=TEST_EDGE_A,
        boot_id=lease.boot_id,
        report_sequence=2,
        desired_revision=first.revision,
        applied_revision=first.revision,
        applied_digest=first.digest,
        phase="applied",
    )
    await edge_repo.accept_report(EdgeIdentity(TEST_EDGE_A), lease, stale)
    async with edge_repo._database.session() as session:  # noqa: SLF001
        device = (
            await session.execute(
                text(
                    "SELECT latest_applied_revision, desired_head_revision "
                    "FROM edge.devices WHERE edge_id = :edge_id"
                ),
                {"edge_id": TEST_EDGE_A},
            )
        ).one()
        assert device.latest_applied_revision == first.revision
        assert device.desired_head_revision == latest.revision


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_report_with_revoked_lease_is_rejected(edge_repo: EdgeRepository):
    saved = await edge_repo.save_desired(TEST_EDGE_A, 0, _desired_document())
    lease = await edge_repo.acquire_lease(TEST_EDGE_A, "boot-a")
    async with edge_repo._database.begin() as connection:  # noqa: SLF001
        await connection.execute(
            text(
                "UPDATE edge.management_leases SET revoked_at = NOW() "
                "WHERE edge_id = :edge_id AND generation = :generation"
            ),
            {"edge_id": TEST_EDGE_A, "generation": lease.generation},
        )
    report = _report(
        edge_id=TEST_EDGE_A,
        boot_id=lease.boot_id,
        report_sequence=1,
        desired_revision=saved.revision,
        applied_revision=saved.revision,
        applied_digest=saved.digest,
    )
    with pytest.raises(EdgeLeaseRejected):
        await edge_repo.accept_report(EdgeIdentity(TEST_EDGE_A), lease, report)


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_apply_report_for_old_desired_while_head_is_newer(edge_repo: EdgeRepository):
    rev1 = await edge_repo.save_desired(TEST_EDGE_A, 0, _desired_document())
    await edge_repo.save_desired(TEST_EDGE_A, 1, _desired_document())
    lease = await edge_repo.acquire_lease(TEST_EDGE_A, "boot-a")
    await edge_repo.accept_report(
        EdgeIdentity(TEST_EDGE_A),
        lease,
        _report(
            edge_id=TEST_EDGE_A,
            boot_id=lease.boot_id,
            report_sequence=1,
            desired_revision=rev1.revision,
            applied_revision=rev1.revision,
            applied_digest=rev1.digest,
        ),
    )
    latest = await edge_repo.latest_desired(TEST_EDGE_A)
    assert latest is not None
    assert latest.revision == 2


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_legacy_rows_stay_unassigned_until_explicit_assignment(
    database: Database,
    edge_repo: EdgeRepository,
):
    connectivity = ConnectivityRepository(database)
    await connectivity.save_server(
        ConnectivityServerSpec(
            id=TEST_SERVER,
            name="Legacy OPC",
            protocol="opc_ua",
            endpoint="opc.tcp://127.0.0.1:4840",
        )
    )
    async with database.session() as session:
        row = (
            await session.execute(select(ConnectivityServer).where(ConnectivityServer.id == TEST_SERVER))
        ).scalar_one()
        assert row.edge_id is None

    assigned = await edge_repo.assign_legacy(TEST_SERVER, TEST_EDGE_A)
    assert assigned.edge_id == TEST_EDGE_A


@pytest.mark.integrationtest
@pytest.mark.asyncio(loop_scope="session")
async def test_report_retention_is_thirty_days(edge_repo: EdgeRepository):
    fixed_now = datetime(2026, 9, 12, tzinfo=UTC)
    repo = EdgeRepository(edge_repo._database, now=lambda: fixed_now)  # noqa: SLF001
    saved = await repo.save_desired(TEST_EDGE_A, 0, _desired_document())
    lease = await repo.acquire_lease(TEST_EDGE_A, "boot-retention")
    row = await repo.accept_report(
        EdgeIdentity(TEST_EDGE_A),
        lease,
        _report(
            edge_id=TEST_EDGE_A,
            boot_id=lease.boot_id,
            report_sequence=1,
            desired_revision=saved.revision,
            applied_revision=saved.revision,
            applied_digest=saved.digest,
        ),
    )
    assert row.retained_until == fixed_now + timedelta(days=30)
