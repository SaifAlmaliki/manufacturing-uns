"""Write the plant hierarchy to YAML, reseed the Asset Model, and migrate prefixes.

`settings.yaml` `simulator.hierarchy` stays the reviewable source of truth
(ADR-0005 addendum). This mutation is how the console writes it. A failed
migrate does not roll the file back: the admin retries migrate only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import strawberry
import yaml
from graphql import GraphQLError
from uns_config import get_settings, resolve_conf_dir
from uns_model.engine import Database
from uns_model.hierarchy import (
    HierarchyArea,
    HierarchyLine,
    HierarchySite,
    HierarchyTree,
    PrefixRename,
    validate_renames,
    validate_tree,
)
from uns_model.topic_path import join_segments
from uns_model.hierarchy_io import load_plant_tree, save_plant_tree, write_enterprise_settings
from uns_model.repositories import AssetModelRepository
from uns_model.seed import apply_plan, plan_from_hierarchy_tree

from uns_graphql.auth.require import require
from uns_graphql.auth.scope import AccessScope, scope_from_info
from uns_graphql.backend.graphdb import rewrite_graph_prefix
from uns_graphql.backend.historian import HistorianRepository
from uns_graphql.input.hierarchy import HierarchyTreeInput, PrefixRenameInput
from uns_graphql.type.hierarchy import HierarchyMigrateJob, HierarchySaveResult, HierarchyTreeType

LOGGER = logging.getLogger(__name__)

JOB_FILENAME = "hierarchy_job.yaml"
_JOB_RUNNING = "running"
_JOB_DONE = "done"
_JOB_FAILED = "failed"
_JOB_IDLE = "idle"
STALE_RUNNING_AFTER = timedelta(minutes=5)
_MIGRATE_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _migrate_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _MIGRATE_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _MIGRATE_LOCKS[loop] = lock
    return lock


def _conf_dir() -> Path:
    return resolve_conf_dir()


def _job_path(conf_dir: Path) -> Path:
    return conf_dir / "simulator" / JOB_FILENAME


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


@dataclass
class _JobRecord:
    status: str
    pending: list[PrefixRename] = field(default_factory=list)
    old_prefix: str | None = None
    new_prefix: str | None = None
    rewritten: int | None = None
    error: str | None = None
    started_at: str | None = None

    def to_graphql(self) -> HierarchyMigrateJob:
        return HierarchyMigrateJob(
            status=self.status,
            old_prefix=self.old_prefix,
            new_prefix=self.new_prefix,
            rewritten=self.rewritten,
            error=self.error,
        )


def _idle_record() -> _JobRecord:
    return _JobRecord(status=_JOB_IDLE)


def _current_pair(pending: list[PrefixRename]) -> tuple[str | None, str | None]:
    if not pending:
        return None, None
    return pending[0].old_prefix, pending[0].new_prefix


def _pending_from_raw(raw: dict) -> list[PrefixRename]:
    pending = raw.get("pending")
    if isinstance(pending, list) and pending:
        result: list[PrefixRename] = []
        for item in pending:
            if not isinstance(item, dict):
                continue
            old = item.get("old") or item.get("old_prefix")
            new = item.get("new") or item.get("new_prefix")
            if old and new:
                result.append(PrefixRename(old_prefix=str(old), new_prefix=str(new)))
        if result:
            return result
    old = raw.get("old_prefix") or raw.get("oldPrefix")
    new = raw.get("new_prefix") or raw.get("newPrefix")
    if old and new:
        return [PrefixRename(old_prefix=str(old), new_prefix=str(new))]
    return []


def _parse_started_at(value: object) -> datetime | None:
    if isinstance(value, datetime):
        started = value
    elif isinstance(value, str) and value:
        try:
            started = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return started


def _is_stale_running(raw: dict) -> bool:
    if str(raw.get("status") or "") != _JOB_RUNNING:
        return False
    started = _parse_started_at(raw.get("started_at"))
    if started is None:
        return True
    return _now() - started > STALE_RUNNING_AFTER


def _record_from_raw(raw: dict) -> _JobRecord:
    pending = _pending_from_raw(raw)
    status = str(raw.get("status") or _JOB_IDLE)
    error = raw.get("error")
    if status == _JOB_RUNNING and _is_stale_running(raw):
        status = _JOB_FAILED
        error = error or "migrate job stalled (process died while running)"
    rewritten = raw.get("rewritten")
    old_prefix = raw.get("old_prefix") or raw.get("oldPrefix")
    new_prefix = raw.get("new_prefix") or raw.get("newPrefix")
    if pending and not old_prefix:
        old_prefix, new_prefix = _current_pair(pending)
    return _JobRecord(
        status=status,
        pending=pending,
        old_prefix=str(old_prefix) if old_prefix else None,
        new_prefix=str(new_prefix) if new_prefix else None,
        rewritten=int(rewritten) if rewritten is not None else None,
        error=str(error) if error else None,
        started_at=str(raw["started_at"]) if raw.get("started_at") is not None else None,
    )


def _load_record(conf_dir: Path) -> _JobRecord:
    path = _job_path(conf_dir)
    if not path.is_file():
        return _idle_record()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return _idle_record()
    return _record_from_raw(raw)


def _load_job(conf_dir: Path) -> HierarchyMigrateJob:
    return _load_record(conf_dir).to_graphql()


def _save_record(conf_dir: Path, record: _JobRecord) -> None:
    path = _job_path(conf_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "status": record.status,
        "old_prefix": record.old_prefix,
        "new_prefix": record.new_prefix,
        "rewritten": record.rewritten,
        "error": record.error,
        "started_at": record.started_at,
        "pending": [{"old": item.old_prefix, "new": item.new_prefix} for item in record.pending],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def _running_record(
    pending: list[PrefixRename],
    *,
    rewritten: int = 0,
    started_at: str | None = None,
) -> _JobRecord:
    old_prefix, new_prefix = _current_pair(pending)
    return _JobRecord(
        status=_JOB_RUNNING,
        pending=list(pending),
        old_prefix=old_prefix,
        new_prefix=new_prefix,
        rewritten=rewritten,
        error=None,
        started_at=started_at or _now_iso(),
    )


async def _rewrite_historian(old_prefix: str, new_prefix: str) -> int:
    return await HistorianRepository(Database.shared("graphql")).rewrite_topic_prefix(
        old_prefix, new_prefix
    )


async def _rewrite_graph(old_prefix: str, new_prefix: str) -> int:
    return await rewrite_graph_prefix(old_prefix, new_prefix)


async def _reseed(tree: HierarchyTree) -> None:
    settings = get_settings("simulator")
    extra = {
        "plc": settings.get("plc"),
        "equipment": settings.get("equipment"),
    }
    repository = AssetModelRepository(Database.shared("graphql"))
    await apply_plan(repository, plan_from_hierarchy_tree(tree, extra=extra))


async def _run_migrate(
    conf_dir: Path,
    renames: list[PrefixRename],
    *,
    started_at: str | None = None,
    rewritten: int = 0,
) -> HierarchyMigrateJob:
    pending = list(renames)
    started = started_at or _now_iso()
    last_old: str | None = None
    last_new: str | None = None
    try:
        while pending:
            current = pending[0]
            last_old, last_new = current.old_prefix, current.new_prefix
            _save_record(
                conf_dir,
                _running_record(pending, rewritten=rewritten, started_at=started),
            )
            rewritten += await _rewrite_historian(current.old_prefix, current.new_prefix)
            rewritten += await _rewrite_graph(current.old_prefix, current.new_prefix)
            pending = pending[1:]
        record = _JobRecord(
            status=_JOB_DONE,
            pending=[],
            old_prefix=last_old,
            new_prefix=last_new,
            rewritten=rewritten,
            error=None,
            started_at=started,
        )
        _save_record(conf_dir, record)
        return record.to_graphql()
    except Exception as exc:
        LOGGER.exception("Hierarchy prefix migrate failed")
        record = _JobRecord(
            status=_JOB_FAILED,
            pending=pending,
            old_prefix=pending[0].old_prefix if pending else last_old,
            new_prefix=pending[0].new_prefix if pending else last_new,
            rewritten=rewritten,
            error=str(exc),
            started_at=started,
        )
        _save_record(conf_dir, record)
        return record.to_graphql()


def _filter_hierarchy(scope: AccessScope, tree: HierarchyTree) -> HierarchyTree:
    """Drop sites/areas/lines/cells whose joined path is outside the caller's scope.

    A parent stays if any child remains, so an operator rooted at an Area still
    sees the Site above it.
    """
    if scope.unrestricted:
        return tree
    sites: list[HierarchySite] = []
    for site in tree.sites:
        site_path = join_segments(tree.enterprise, site.name)
        areas: list[HierarchyArea] = []
        for area in site.areas:
            area_path = join_segments(site_path, area.name)
            lines: list[HierarchyLine] = []
            for line in area.lines:
                line_path = join_segments(area_path, line.name)
                cells = [
                    cell
                    for cell in line.cells
                    if scope.covers_path(join_segments(line_path, cell.name))
                ]
                if cells or scope.covers_path(line_path):
                    lines.append(HierarchyLine(name=line.name, cells=tuple(cells)))
            if lines or scope.covers_path(area_path):
                areas.append(HierarchyArea(name=area.name, kind=area.kind, lines=tuple(lines)))
        if areas or scope.covers_path(site_path):
            sites.append(HierarchySite(name=site.name, areas=tuple(areas)))
    return HierarchyTree(enterprise=tree.enterprise, sites=tuple(sites))


@strawberry.type(description="Read the plant hierarchy stored in settings.yaml")
class Query:
    @strawberry.field(description="The ISA-95 tree from conf/settings.yaml simulator.hierarchy.")
    async def get_hierarchy(self, info: strawberry.Info) -> HierarchyTreeType:
        tree = load_plant_tree(_conf_dir())
        scope = await scope_from_info(info)
        return HierarchyTreeType.from_tree(_filter_hierarchy(scope, tree))


@strawberry.type(description="Persist the plant hierarchy and migrate renamed prefixes")
class Mutation:
    """Role each field needs is in auth/require.py, not in these resolvers."""

    @strawberry.mutation(
        description="Replace settings.yaml simulator.hierarchy with the submitted tree, derive branding, reseed "
        "the Asset Model, and migrate renamed prefixes. Prefix migrate runs inline in this "
        "GraphQL request until historian and graph rewrites finish; the caller observes "
        "done or failed, not running. A running job file is for crash recovery and Retry, "
        "not for polling. Rejects a second rename while a migrate job is already running."
    )
    async def save_hierarchy(
        self,
        info: strawberry.Info,
        tree: HierarchyTreeInput,
        renames: list[PrefixRenameInput],
    ) -> HierarchySaveResult:
        require(info, "saveHierarchy")
        conf_dir = _conf_dir()
        prefix_renames = [item.to_rename() for item in renames]

        async with _migrate_lock():
            if prefix_renames and _load_job(conf_dir).status == _JOB_RUNNING:
                raise GraphQLError(
                    "Cannot apply renames while a hierarchy migrate job is already running",
                    extensions={"field": "renames"},
                )

            new_tree = tree.to_tree()
            validate_tree(new_tree)
            previous = load_plant_tree(conf_dir)
            if prefix_renames:
                validate_renames(new_tree, previous, prefix_renames)
                _save_record(conf_dir, _running_record(prefix_renames))

            save_plant_tree(conf_dir, new_tree)
            write_enterprise_settings(conf_dir, new_tree.enterprise)
            await _reseed(new_tree)

            if prefix_renames:
                job = await _run_migrate(conf_dir, prefix_renames)
            else:
                job = _load_job(conf_dir)

        LOGGER.info(
            "Hierarchy saved enterprise=%s sites=%s job=%s",
            new_tree.enterprise,
            len(new_tree.sites),
            job.status,
        )
        return HierarchySaveResult(tree=HierarchyTreeType.from_tree(new_tree), job=job)

    @strawberry.mutation(
        description="Retry a failed or stalled prefix migrate. YAML is not rewritten: the "
        "tree is already stored. Adopts a failed job or a running job (including a stale "
        "running file left by a crash) and resumes from the first unfinished rename. "
        "No-op when there is no such job."
    )
    async def retry_hierarchy_migrate(self, info: strawberry.Info) -> HierarchyMigrateJob:
        require(info, "retryHierarchyMigrate")
        conf_dir = _conf_dir()
        async with _migrate_lock():
            record = _load_record(conf_dir)
            if record.status not in {_JOB_FAILED, _JOB_RUNNING}:
                return record.to_graphql()
            if not record.pending:
                raise ValueError("no failed migrate prefixes to retry")
            return await _run_migrate(
                conf_dir,
                record.pending,
                rewritten=record.rewritten or 0,
            )
