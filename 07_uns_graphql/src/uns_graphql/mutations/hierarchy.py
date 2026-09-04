"""Write the plant hierarchy to YAML, reseed the Asset Model, and migrate prefixes.

YAML stays the reviewable source of truth (ADR-0005 addendum). This mutation is
how the console writes it. A failed migrate does not roll the files back: the
admin retries migrate only.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import strawberry
import yaml
from graphql import GraphQLError
from uns_config import resolve_conf_dir
from uns_model.engine import Database
from uns_model.hierarchy import HierarchyTree, PrefixRename, validate_renames, validate_tree
from uns_model.hierarchy_io import load_plant_tree, save_plant_tree, write_enterprise_settings
from uns_model.repositories import AssetModelRepository
from uns_model.seed import apply_plan, plan_from_hierarchy_tree

from uns_graphql.auth.require import require
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


def _conf_dir() -> Path:
    return resolve_conf_dir()


def _job_path(conf_dir: Path) -> Path:
    return conf_dir / "simulator" / JOB_FILENAME


def _idle_job() -> HierarchyMigrateJob:
    return HierarchyMigrateJob(status=_JOB_IDLE)


def _load_job(conf_dir: Path) -> HierarchyMigrateJob:
    path = _job_path(conf_dir)
    if not path.is_file():
        return _idle_job()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return _idle_job()
    status = str(raw.get("status") or _JOB_IDLE)
    rewritten = raw.get("rewritten")
    return HierarchyMigrateJob(
        status=status,
        old_prefix=raw.get("old_prefix") or raw.get("oldPrefix"),
        new_prefix=raw.get("new_prefix") or raw.get("newPrefix"),
        rewritten=int(rewritten) if rewritten is not None else None,
        error=raw.get("error"),
    )


def _save_job(conf_dir: Path, job: HierarchyMigrateJob) -> None:
    path = _job_path(conf_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "status": job.status,
        "old_prefix": job.old_prefix,
        "new_prefix": job.new_prefix,
        "rewritten": job.rewritten,
        "error": job.error,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


async def _rewrite_historian(old_prefix: str, new_prefix: str) -> int:
    return await HistorianRepository(Database.shared("graphql")).rewrite_topic_prefix(
        old_prefix, new_prefix
    )


async def _rewrite_graph(old_prefix: str, new_prefix: str) -> int:
    return await rewrite_graph_prefix(old_prefix, new_prefix)


async def _reseed(tree: HierarchyTree) -> None:
    repository = AssetModelRepository(Database.shared("graphql"))
    await apply_plan(repository, plan_from_hierarchy_tree(tree))


async def _run_migrate(
    conf_dir: Path, renames: list[PrefixRename]
) -> HierarchyMigrateJob:
    rewritten = 0
    current: PrefixRename | None = None
    try:
        for current in renames:
            _save_job(
                conf_dir,
                HierarchyMigrateJob(
                    status=_JOB_RUNNING,
                    old_prefix=current.old_prefix,
                    new_prefix=current.new_prefix,
                    rewritten=rewritten,
                    error=None,
                ),
            )
            rewritten += await _rewrite_historian(current.old_prefix, current.new_prefix)
            rewritten += await _rewrite_graph(current.old_prefix, current.new_prefix)
        job = HierarchyMigrateJob(
            status=_JOB_DONE,
            old_prefix=current.old_prefix if current else None,
            new_prefix=current.new_prefix if current else None,
            rewritten=rewritten,
            error=None,
        )
        _save_job(conf_dir, job)
        return job
    except Exception as exc:
        LOGGER.exception("Hierarchy prefix migrate failed")
        job = HierarchyMigrateJob(
            status=_JOB_FAILED,
            old_prefix=current.old_prefix if current else None,
            new_prefix=current.new_prefix if current else None,
            rewritten=rewritten,
            error=str(exc),
        )
        _save_job(conf_dir, job)
        return job


@strawberry.type(description="Read the plant hierarchy stored in plant.yaml")
class Query:
    @strawberry.field(description="The ISA-95 tree from conf/simulator/plant.yaml.")
    async def get_hierarchy(self) -> HierarchyTreeType:
        return HierarchyTreeType.from_tree(load_plant_tree(_conf_dir()))


@strawberry.type(description="Persist the plant hierarchy and migrate renamed prefixes")
class Mutation:
    """Role each field needs is in auth/require.py, not in these resolvers."""

    @strawberry.mutation(
        description="Replace plant.yaml with the submitted tree, derive branding, reseed "
        "the Asset Model, and migrate renamed prefixes. Rejects a second rename while a "
        "migrate job is already running."
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

        if prefix_renames and _load_job(conf_dir).status == _JOB_RUNNING:
            raise GraphQLError(
                "Cannot apply renames while a hierarchy migrate job is already running"
            )

        new_tree = tree.to_tree()
        validate_tree(new_tree)
        previous = load_plant_tree(conf_dir)
        if prefix_renames:
            validate_renames(new_tree, previous, prefix_renames)

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
        description="Retry a failed prefix migrate. YAML is not rewritten: the tree is "
        "already stored. No-op when there is no failed job."
    )
    async def retry_hierarchy_migrate(self, info: strawberry.Info) -> HierarchyMigrateJob:
        require(info, "retryHierarchyMigrate")
        conf_dir = _conf_dir()
        job = _load_job(conf_dir)
        if job.status != _JOB_FAILED:
            return job
        if not job.old_prefix or not job.new_prefix:
            raise ValueError("no failed migrate prefixes to retry")
        return await _run_migrate(
            conf_dir, [PrefixRename(old_prefix=job.old_prefix, new_prefix=job.new_prefix)]
        )
