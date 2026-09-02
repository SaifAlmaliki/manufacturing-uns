"""Reading machine samples out of the historian's narrow metrics table.

Every statement here is written to hit `idx_uns_metrics_topic_metric_time (topic,
metric_name, time DESC)`, which already exists. Nothing in this module reads the JSONB
`unifiednamespace` table or the continuous aggregates: the aggregates average, and an OEE
counter delta cannot be taken from an average.

A metric binding is `<segments below the Asset>/<payload leaf>` - the same meaning
`TopicBinding.metric_path` already carries. Splitting at the last slash gives the MQTT topic
and the flattened leaf name, which is `value` for every signal the simulator publishes.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import text
from uns_model.engine import Database

from uns_oee.counters import Sample
from uns_oee.states import StateSample

LOGGER = logging.getLogger(__name__)

#: The metrics table comes from configuration, not from a request, but it is interpolated
#: into SQL - so it is checked against this rather than trusted.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: How far before a shift start the "last known value" query is allowed to reach. Bounded so
#: a unit that stopped publishing months ago cannot make Timescale walk every chunk backwards.
DEFAULT_PRIOR_LOOKBACK_HOURS = 72


@dataclass(frozen=True, slots=True)
class MetricRef:
    """One addressable series: an MQTT topic and a flattened payload leaf name."""

    topic: str
    metric_name: str


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """What the input window looked like, cheaply enough to re-read often.

    Row count and latest sample time. Late-arriving data changes one or both, which is the
    signal to recompute the shift and supersede the stored revision.

    `manual_digest` is the third input and does not come from the historian: an operator
    reassigning a downtime reason changes the arithmetic without changing a single sample.
    Left at "-" here and filled in by the pipeline, which is where the reasons are read.
    """

    row_count: int = 0
    max_time: datetime | None = None
    manual_digest: str = "-"

    @property
    def is_empty(self) -> bool:
        """Whether the historian had anything to say. Manual reasons do not make a shift
        non-empty: a reason attached to a stop that no longer has samples behind it is not
        input data."""
        return self.row_count == 0

    def as_text(self) -> str:
        """The stored form. Stable across runs - two formats would look like late data."""
        return (
            f"{self.row_count}:"
            f"{self.max_time.isoformat() if self.max_time else '-'}:"
            f"{self.manual_digest}"
        )

    def with_manual(self, digest: str) -> Fingerprint:
        """This fingerprint plus the operator's contribution to the inputs."""
        return replace(self, manual_digest=digest)

    @staticmethod
    def source_part(stored: str) -> str:
        """The historian half of a stored fingerprint, without the operator's digest.

        The parser lives beside the formatter so the two cannot drift. It exists because
        "the data changed" and "someone reassigned a reason" are different events, and
        `uns_oee_late_data_detected_total` must only count the first.
        """
        return stored.rpartition(":")[0]


def split_metric_key(asset_path: str, metric_key: str) -> MetricRef:
    """Resolve an Asset path plus a binding into a topic and a metric name."""
    stripped_key = metric_key.strip("/")
    below_asset, _, metric_name = stripped_key.rpartition("/")
    if not below_asset or not metric_name:
        raise ValueError(
            f"metric binding {metric_key!r} must be at least one topic segment followed by a "
            f"payload leaf, e.g. 'Cell1/MES-01/Status/PackMlState/value'"
        )
    topic = f"{asset_path.strip('/')}/{below_asset}"
    return MetricRef(topic=topic, metric_name=metric_name)


def window_sql(table: str, value_column: str) -> str:
    """Every sample of one series inside a closed window, oldest first."""
    return (
        f"SELECT time, {value_column} FROM {table} "
        f"WHERE topic = :topic AND metric_name = :metric_name "
        f"AND time >= :start AND time <= :end AND {value_column} IS NOT NULL "
        f"ORDER BY time"
    )


def prior_sql(table: str, value_column: str) -> str:
    """The last sample of one series before a window, within a bounded lookback."""
    return (
        f"SELECT time, {value_column} FROM {table} "
        f"WHERE topic = :topic AND metric_name = :metric_name "
        f"AND time < :start AND time >= :lookback_from AND {value_column} IS NOT NULL "
        f"ORDER BY time DESC LIMIT 1"
    )


def fingerprint_sql(table: str, pair_count: int) -> str:
    """Row count and latest sample time across several series. Empty string for no series."""
    if pair_count <= 0:
        return ""
    return (
        f"SELECT count(*), max(time) FROM {table} "
        f"WHERE {_pair_predicate(pair_count)} AND time >= :start AND time <= :end"
    )


def earliest_sql(table: str, pair_count: int) -> str:
    """The first sample time across several series. Used once, to bound the backfill."""
    if pair_count <= 0:
        return ""
    return f"SELECT min(time) FROM {table} WHERE {_pair_predicate(pair_count)}"


def pair_params(refs: Sequence[MetricRef]) -> dict[str, str]:
    """Bound parameters for `_pair_predicate`, in the same order."""
    parameters: dict[str, str] = {}
    for index, ref in enumerate(refs):
        parameters[f"topic_{index}"] = ref.topic
        parameters[f"metric_{index}"] = ref.metric_name
    return parameters


def _pair_predicate(pair_count: int) -> str:
    """`(topic, metric_name) IN ((:topic_0, :metric_0), ...)`.

    A row constructor rather than two `= ANY(...)` clauses, which would match the cross
    product - four topics and two metric names would silently include four pairs nobody asked
    for, and the fingerprint would move for reasons unrelated to the shift.
    """
    pairs = ", ".join(f"(:topic_{index}, :metric_{index})" for index in range(pair_count))
    return f"(topic, metric_name) IN ({pairs})"


class MetricSource:
    """The historian read path for one OEE run.

    Holds no state beyond its connection source, so the pipeline can reuse one instance for a
    thirty-day backfill.
    """

    def __init__(
        self,
        database: Database,
        metrics_table: str = "uns_metrics",
        prior_lookback_hours: int = DEFAULT_PRIOR_LOOKBACK_HOURS,
    ) -> None:
        if not _IDENTIFIER.match(metrics_table):
            raise ValueError(f"metrics table {metrics_table!r} is not a plain SQL identifier")
        self._database = database
        self._table = metrics_table
        self._prior_lookback = timedelta(hours=prior_lookback_hours)

    async def numeric_samples(
        self, ref: MetricRef, start: datetime, end: datetime, *, include_prior: bool = True
    ) -> list[Sample]:
        """Counter readings for one series, with the pre-window baseline unless refused."""
        rows = await self._rows(ref, start, end, "value_double", include_prior)
        return sorted(Sample(at=at, value=float(value)) for at, value in rows if value is not None)

    async def text_samples(
        self, ref: MetricRef, start: datetime, end: datetime, *, include_prior: bool = True
    ) -> list[StateSample]:
        """State or product readings for one series, with the value in force at `start`."""
        rows = await self._rows(ref, start, end, "value_text", include_prior)
        return sorted(StateSample(at=at, state=str(value)) for at, value in rows if value is not None)

    async def fingerprint(
        self, refs: Sequence[MetricRef], start: datetime, end: datetime
    ) -> Fingerprint:
        """One indexed aggregate over every series a unit reads. Cheap enough to re-run often."""
        statement = fingerprint_sql(self._table, len(refs))
        if not statement:
            return Fingerprint()
        parameters = pair_params(refs) | {"start": start, "end": end}
        async with self._database.begin() as connection:
            row = (await connection.execute(text(statement), parameters)).first()
        if row is None:
            return Fingerprint()
        return Fingerprint(row_count=int(row[0] or 0), max_time=row[1])

    async def earliest_sample_at(self, refs: Sequence[MetricRef]) -> datetime | None:
        """The first sample a unit ever published, or `None`. Bounds the startup backfill."""
        statement = earliest_sql(self._table, len(refs))
        if not statement:
            return None
        async with self._database.begin() as connection:
            row = (await connection.execute(text(statement), pair_params(refs))).first()
        return None if row is None else row[0]

    async def _rows(
        self, ref: MetricRef, start: datetime, end: datetime, value_column: str, include_prior: bool
    ) -> list[tuple[datetime, object]]:
        """The window's rows, preceded by the baseline row when one is wanted and exists."""
        base = {"topic": ref.topic, "metric_name": ref.metric_name, "start": start, "end": end}
        rows: list[tuple[datetime, object]] = []
        async with self._database.begin() as connection:
            if include_prior:
                prior = await connection.execute(
                    text(prior_sql(self._table, value_column)),
                    base | {"lookback_from": start - self._prior_lookback},
                )
                rows.extend(prior.fetchall())
            window = await connection.execute(text(window_sql(self._table, value_column)), base)
            rows.extend(window.fetchall())
        return rows


__all__ = [
    "DEFAULT_PRIOR_LOOKBACK_HOURS",
    "Fingerprint",
    "MetricRef",
    "MetricSource",
    "earliest_sql",
    "fingerprint_sql",
    "pair_params",
    "prior_sql",
    "split_metric_key",
    "window_sql",
]
