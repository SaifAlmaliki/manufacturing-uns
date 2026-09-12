"""Shared constants and helpers for outbound edge management jobs."""

from __future__ import annotations

from datetime import timedelta

JOB_KIND_TEST_CONNECTION = "test_connection"
JOB_KIND_BROWSE_TAGS = "browse_tags"
JOB_KINDS = frozenset({JOB_KIND_TEST_CONNECTION, JOB_KIND_BROWSE_TAGS})

JOB_EXPIRY = timedelta(minutes=5)
JOB_EXECUTION = timedelta(seconds=60)
JOB_RESULT_RETENTION = timedelta(hours=24)
MAX_PENDING_JOBS_PER_EDGE = 100
MAX_TAGS_PER_PAGE = 500
MAX_RESULT_BYTES = 1024 * 1024

BROWSE_PROTOCOLS = frozenset({"opc_ua"})


def parse_cursor_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    if "." not in cursor:
        return 0
    try:
        return int(cursor.rsplit(".", 1)[-1])
    except ValueError:
        return 0
