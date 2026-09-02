"""Tests for uns_oee.publisher - the topic, the payload, and one connection.

The payload numbers here are spec section 11's worked example, so a change to the rounding
or to a field name fails against the document rather than against a copy of it.
"""

import json
from datetime import datetime, timezone

import pytest

from uns_oee.oee_config import OeeConfig
from uns_oee.oee_calc import ShiftMetrics
from uns_oee.publisher import (
    PAYLOAD_FIELDS,
    PAYLOAD_SOURCE,
    ResultPublisher,
    epoch_millis,
    equipment_of,
    shift_oee_payload,
    shift_oee_topic,
)
from uns_oee.shift_calendar import ShiftWindow

LINE = "CovestroAG/Dormagen/Production/Line1"
WINDOW = ShiftWindow(
    start=datetime(2026, 9, 7, 4, tzinfo=timezone.utc),
    end=datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
    label="A",
)
CONFIG = OeeConfig(mqtt_host="localhost")


def metrics() -> ShiftMetrics:
    return ShiftMetrics(
        loading_time_s=27000.0,
        run_time_s=24084.0,
        planned_down_s=1800.0,
        unplanned_down_s=2916.0,
        good_count=12840.0,
        reject_count=182.0,
        total_count=13022.0,
        availability=0.892,
        performance=0.841,
        performance_raw=0.841,
        quality=0.952,
        oee=0.714,
        status="OK",
    )


class FakeClient:
    """An aiomqtt.Client stand-in: an async context manager with a publish."""

    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[tuple[str, str, int, bool]] = []
        self.fail = fail
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> "FakeClient":
        self.entered += 1
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        self.exited += 1
        return False

    async def publish(self, topic, payload, qos=0, retain=False) -> None:
        if self.fail:
            raise RuntimeError("broker unreachable")
        self.messages.append((topic, payload, qos, retain))


def test_the_topic_is_the_asset_path_plus_the_kpi_parameter():
    assert shift_oee_topic(LINE) == f"{LINE}/KPI/ShiftOee"


def test_equipment_is_the_last_segment_of_the_asset_path():
    assert equipment_of(LINE) == "Line1"
    assert equipment_of("Line1") == "Line1"


def test_the_headline_value_is_oee_as_a_percentage():
    payload = shift_oee_payload(LINE, WINDOW, metrics(), revision=1)
    assert payload["value"] == 71.4
    assert payload["unit"] == "%"


def test_every_factor_is_a_percentage_and_no_count_is():
    payload = shift_oee_payload(LINE, WINDOW, metrics(), revision=1)
    assert payload["availability"] == 89.2
    assert payload["performance"] == 84.1
    assert payload["quality"] == 95.2
    assert payload["good_count"] == 12840.0
    assert payload["reject_count"] == 182.0
    assert payload["total_count"] == 13022.0


def test_the_timestamp_is_shift_end_in_epoch_milliseconds():
    payload = shift_oee_payload(LINE, WINDOW, metrics(), revision=1)
    assert payload["timestamp"] == epoch_millis(WINDOW.end)
    assert payload["shift_start"] == epoch_millis(WINDOW.start)
    assert payload["timestamp"] > payload["shift_start"]


def test_an_undefined_factor_stays_null_so_the_historian_writes_no_row():
    blank = ShiftMetrics(status="NO_LOADING_TIME")
    payload = shift_oee_payload(LINE, WINDOW, blank, revision=1)
    assert payload["value"] is None
    assert payload["availability"] is None
    assert payload["quality"] is None
    assert payload["status"] == "NO_LOADING_TIME"


def test_the_shift_label_source_and_revision_travel_with_the_payload():
    payload = shift_oee_payload(LINE, WINDOW, metrics(), revision=3)
    assert payload["shift_label"] == "A"
    assert payload["source"] == PAYLOAD_SOURCE
    assert payload["equipment"] == "Line1"
    assert payload["revision"] == 3


def test_the_payload_has_exactly_the_documented_field_set():
    assert set(shift_oee_payload(LINE, WINDOW, metrics(), revision=1)) == PAYLOAD_FIELDS


@pytest.mark.asyncio
async def test_publishing_sends_one_json_message_at_the_configured_qos():
    client = FakeClient()
    publisher = ResultPublisher(CONFIG, client_factory=lambda: client)

    assert await publisher.publish(LINE, WINDOW, metrics(), revision=1) is True

    topic, body, qos, retain = client.messages[0]
    assert topic == f"{LINE}/KPI/ShiftOee"
    assert json.loads(body)["value"] == 71.4
    assert qos == CONFIG.mqtt_qos
    assert retain is False
    assert publisher.published == 1
    await publisher.aclose()


@pytest.mark.asyncio
async def test_a_second_publish_reuses_the_one_connection():
    client = FakeClient()
    publisher = ResultPublisher(CONFIG, client_factory=lambda: client)

    await publisher.publish(LINE, WINDOW, metrics(), revision=1)
    await publisher.publish(LINE, WINDOW, metrics(), revision=2)

    assert client.entered == 1
    assert len(client.messages) == 2
    await publisher.aclose()


@pytest.mark.asyncio
async def test_a_broker_failure_is_reported_not_raised():
    publisher = ResultPublisher(CONFIG, client_factory=lambda: FakeClient(fail=True))

    assert await publisher.publish(LINE, WINDOW, metrics(), revision=1) is False
    assert publisher.failed == 1
    assert publisher.published == 0
    assert not publisher.connected


@pytest.mark.asyncio
async def test_a_failure_drops_the_connection_so_the_next_call_reconnects():
    clients = [FakeClient(fail=True), FakeClient()]
    publisher = ResultPublisher(CONFIG, client_factory=lambda: clients.pop(0))

    assert await publisher.publish(LINE, WINDOW, metrics(), revision=1) is False
    assert await publisher.publish(LINE, WINDOW, metrics(), revision=1) is True
    assert publisher.failed == 1
    assert publisher.published == 1
    await publisher.aclose()


@pytest.mark.asyncio
async def test_closing_an_unconnected_publisher_is_not_an_error():
    publisher = ResultPublisher(CONFIG, client_factory=FakeClient)
    await publisher.aclose()
    assert not publisher.connected
