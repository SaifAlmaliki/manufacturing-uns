"""Tests for the OPC UA data-change subscription handler.

The handler mirrors the collector's `SubscriptionHandler` discipline: an asyncua
callback that must not block and must not raise. These tests pin the signature
`(node, val, data)` and the `Good`/`Uncertain`/`Bad` status mapping so a console
subscriber sees the same quality string the bridge publishes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from uns_graphql.subscriptions.opcua import _DataChangeHandler


def _node(node_id: str) -> SimpleNamespace:
    return SimpleNamespace(nodeid=SimpleNamespace(to_string=lambda: node_id))


def _data(status_code: int, value, source_ts=None, server_ts=None) -> SimpleNamespace:
    data_value = SimpleNamespace(
        Value=value,
        SourceTimestamp=source_ts,
        ServerTimestamp=server_ts,
        StatusCode=SimpleNamespace(value=status_code),
    )
    return SimpleNamespace(monitored_item=SimpleNamespace(Value=data_value))


@pytest.mark.asyncio
async def test_datachange_handler_enqueues_with_good_status_for_a_zero_severity_code():
    queue: asyncio.Queue = asyncio.Queue()
    handler = _DataChangeHandler(queue)

    handler.datachange_notification(
        _node("ns=2;s=Temperature"), 21.5, _data(status_code=0, value=21.5)
    )

    row = queue.get_nowait()
    assert row.node_id == "ns=2;s=Temperature"
    assert row.value == 21.5
    assert row.status == "Good"


@pytest.mark.asyncio
async def test_datachange_handler_maps_a_bad_severity_code_to_bad():
    queue: asyncio.Queue = asyncio.Queue()
    handler = _DataChangeHandler(queue)

    # Bad (severity 0b10) — top two bits set, e.g. 0x80000000.
    handler.datachange_notification(
        _node("ns=2;s=Fault"), True, _data(status_code=0x80000000, value=True)
    )

    row = queue.get_nowait()
    assert row.status == "Bad"


@pytest.mark.asyncio
async def test_datachange_handler_does_not_raise_on_a_bad_node():
    """A callback that kills the client task takes the whole subscription with it."""

    class _BrokenNode:
        @property
        def nodeid(self):  # noqa: ANN201
            raise RuntimeError("node went away")

    queue: asyncio.Queue = asyncio.Queue()
    handler = _DataChangeHandler(queue)

    # Should not raise.
    handler.datachange_notification(_BrokenNode(), None, _data(0, None))
    assert queue.empty()
