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

The whole loop: samples in the historian, a shift computed, a message on the broker, and a
payload the historian can store again.

Needs a migrated database and an MQTT broker on localhost - `docker compose up -d
uns_mqtt_broker uns_timescale_db tsdb_setup_script asset_model_setup`. The database
seeding, the shift and the expected numbers all come from `test_integration`, which is on
the pytest `pythonpath` (root `pyproject.toml`); this file adds only the broker.

The simulator is not started. What matters here is that the loop closes - that the engine's
payload is one `flatten_payload_to_metrics` can turn into rows, with the metric names the
dashboards read - and calling the historian's real flattener on the real payload shows that
exactly, without waiting a simulated plant-hour for a nondeterministic number.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path

import aiomqtt
import pytest
from sqlalchemy import text
from uns_historian.metric_flattener import flatten_payload_to_metrics

from uns_oee.master_data import MasterDataLoader
from uns_oee.oee_config import OeeConfig
from uns_oee.pipeline import ACTION_COMPUTED, ACTION_REPUBLISHED, ShiftPipeline
from uns_oee.publisher import PAYLOAD_FIELDS, PAYLOAD_SOURCE, ResultPublisher, shift_oee_topic
from uns_oee.shift_calendar import ShiftWindow
from uns_oee.sources import MetricSource
from uns_oee.store import ResultStore

# Root pythonpath lists 09_uns_model/test before 12_uns_oee/test, and both files
# are named test_integration.py. Load the sibling by path so collection does not
# bind COMPUTED_AT / seeded from the model package. Pytest still finds the
# fixtures because they are bound in this module's globals.
_INTEGRATION_PATH = Path(__file__).resolve().parent / "test_integration.py"
_spec = importlib.util.spec_from_file_location("_oee_test_integration", _INTEGRATION_PATH)
assert _spec is not None and _spec.loader is not None
_integration = importlib.util.module_from_spec(_spec)
sys.modules["_oee_test_integration"] = _integration
_spec.loader.exec_module(_integration)

COMPUTED_AT = _integration.COMPUTED_AT
EXPECTED_AVAILABILITY = _integration.EXPECTED_AVAILABILITY
EXPECTED_OEE = _integration.EXPECTED_OEE
EXPECTED_PERFORMANCE = _integration.EXPECTED_PERFORMANCE
EXPECTED_QUALITY = _integration.EXPECTED_QUALITY
LINE_PATH = _integration.LINE_PATH
WINDOW = _integration.WINDOW
database = _integration.database
seeded = _integration.seeded
unit = _integration.unit

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

pytestmark = [
    pytest.mark.integrationtest,
    pytest.mark.asyncio(loop_scope="session"),
    # Same group as the SQL tests: they write the same Asset branch, and this file also
    # binds a fixed MQTT client id.
    pytest.mark.xdist_group(name="oee_database"),
]

CONFIG = OeeConfig(mqtt_host="localhost")
TOPIC = shift_oee_topic(LINE_PATH)
# Long enough for a local broker round trip, short enough that the retain test - which is a
# test that nothing arrives - does not dominate the suite.
RECEIVE_TIMEOUT_S = 10.0
SILENCE_TIMEOUT_S = 2.0


def _pipeline(database, publisher) -> ShiftPipeline:
    return ShiftPipeline(
        MetricSource(database), MasterDataLoader(database), ResultStore(database), publisher
    )


async def _listen_while(
    action: Callable[[], Awaitable[None]], *, timeout: float = RECEIVE_TIMEOUT_S
) -> dict | None:
    """Subscribe, run `action`, and return the first payload on TOPIC, or None on silence.

    The subscription is established before `action` runs, because nothing is retained: a
    subscriber that arrives after the publish sees nothing, which is the point of the
    retain test below and would be a race in every other test here.
    """
    async with aiomqtt.Client(
        hostname=CONFIG.mqtt_host,
        port=CONFIG.mqtt_port,
        identifier="pytest-oee-listener",
        protocol=aiomqtt.ProtocolVersion(CONFIG.mqtt_version),
    ) as client:
        await client.subscribe(TOPIC, qos=CONFIG.mqtt_qos)
        await action()
        try:
            async with asyncio.timeout(timeout):
                async for message in client.messages:
                    return json.loads(message.payload)
        except TimeoutError:
            return None
    return None


@pytest.fixture
def publisher():
    """The real publisher against the real broker."""
    return ResultPublisher(CONFIG)


async def test_a_computed_shift_arrives_on_the_units_own_kpi_topic(seeded, unit, publisher):
    """
    The one assertion that no unit test can fake: the message is on the broker, on the
    Asset's own path, and it carries the numbers that were stored.
    """
    engine = _pipeline(seeded, publisher)

    payload = await _listen_while(lambda: engine.run_shift(unit, WINDOW, COMPUTED_AT))
    await publisher.aclose()

    assert payload is not None, f"nothing arrived on {TOPIC} within {RECEIVE_TIMEOUT_S}s"
    assert payload["value"] == pytest.approx(round(EXPECTED_OEE * 100, 1))
    assert payload["availability"] == pytest.approx(round(EXPECTED_AVAILABILITY * 100, 1))
    assert payload["performance"] == pytest.approx(round(EXPECTED_PERFORMANCE * 100, 1))
    assert payload["quality"] == pytest.approx(round(EXPECTED_QUALITY * 100, 1))
    assert payload["equipment"] == "Line1"
    assert payload["source"] == PAYLOAD_SOURCE
    assert payload["status"] == "OK"
    assert payload["revision"] == 1


async def test_the_delivered_payload_has_every_field_section_11_documents(seeded, unit, publisher):
    """
    Field for field against the spec, after a JSON round trip through a real broker - which
    is where a `datetime` that was never converted to epoch milliseconds would surface as a
    serialisation error rather than as a wrong number.
    """
    engine = _pipeline(seeded, publisher)

    payload = await _listen_while(lambda: engine.run_shift(unit, WINDOW, COMPUTED_AT))
    await publisher.aclose()

    assert payload is not None
    assert set(payload) == set(PAYLOAD_FIELDS)
    assert payload["unit"] == "%"
    assert payload["shift_label"] == "A"
    # Epoch milliseconds, not ISO strings: the historian maps `timestamp` to its `time` column.
    assert payload["shift_start"] == pytest.approx(WINDOW.start.timestamp() * 1000.0)
    assert payload["timestamp"] == pytest.approx(WINDOW.end.timestamp() * 1000.0)
    assert payload["timestamp"] > payload["shift_start"]


async def test_the_historian_turns_the_payload_back_into_metric_rows(seeded, unit, publisher):
    """
    The loop closing. `flatten_payload_to_metrics` is the historian's own function, so this
    is what `uns_metrics` would actually hold - and the four numeric names asserted here are
    the ones the enriched views, the graph database and the alert engine key on.
    """
    engine = _pipeline(seeded, publisher)
    payload = await _listen_while(lambda: engine.run_shift(unit, WINDOW, COMPUTED_AT))
    await publisher.aclose()
    assert payload is not None

    rows = flatten_payload_to_metrics(payload)
    by_name = {name: (number, word) for name, number, word in rows}

    # A flat payload means one row per field, with no dotted paths to guess at.
    assert set(by_name) == set(PAYLOAD_FIELDS)
    assert by_name["value"] == (pytest.approx(round(EXPECTED_OEE * 100, 1)), None)
    for factor in ("availability", "performance", "quality"):
        number, word = by_name[factor]
        assert number is not None, f"{factor} must be numeric or the trend cannot plot it"
        assert word is None
    # Strings stay strings; the CHECK constraint on uns_metrics allows exactly one of the two.
    assert by_name["unit"] == (None, "%")
    assert by_name["source"] == (None, PAYLOAD_SOURCE)
    assert by_name["status"] == (None, "OK")
    for number, word in by_name.values():
        assert (number is None) != (word is None), "uns_metrics allows exactly one value column"


async def test_an_undefined_factor_produces_no_row_rather_than_a_zero(seeded, unit, publisher):
    """
    A shift with no samples is `NO_INPUT_DATA` with null factors, and a null leaf must
    vanish. A zero here would be indistinguishable from a genuinely terrible shift and
    would drag every hourly and daily rollup down with it.
    """
    engine = _pipeline(seeded, publisher)
    # A window a week before any sample exists: the calendar offers it, the data does not.
    empty = ShiftWindow(
        start=WINDOW.start - timedelta(days=7), end=WINDOW.end - timedelta(days=7), label="A"
    )

    payload = await _listen_while(lambda: engine.run_shift(unit, empty, COMPUTED_AT))
    await publisher.aclose()

    assert payload is not None
    assert payload["status"] == "NO_INPUT_DATA"
    assert payload["value"] is None
    rows = {name for name, _, _ in flatten_payload_to_metrics(payload)}
    assert "value" not in rows
    assert "availability" not in rows
    # The identifying fields still arrive, so the empty shift is visible as an empty shift.
    assert {"status", "source", "equipment", "shift_start", "timestamp"} <= rows


async def test_nothing_is_retained_on_the_kpi_topic(seeded, unit, publisher):
    """
    A shift result is a historical fact stamped at its own `shift_end`. Retained, the broker
    would hand the last closed shift to every new subscriber as though it were the current
    one - and a live tile would show yesterday's night shift all morning.
    """
    engine = _pipeline(seeded, publisher)
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    await publisher.aclose()

    late = await _listen_while(lambda: asyncio.sleep(0), timeout=SILENCE_TIMEOUT_S)

    assert late is None, "the shift result was published with retain=True"


async def test_a_broker_outage_leaves_the_result_unpublished_and_the_next_pass_sends_it(
    seeded, unit
):
    """
    The whole retry mechanism, which has no queue and no backoff: `publish` returns False,
    `published_at` stays NULL, and the next scan sees an unpublished result and sends it.
    Both halves are needed - either one alone loses the shift or duplicates it.
    """
    # Port 1 is privileged and nothing listens on it: a connection refusal, not a timeout.
    offline = OeeConfig(mqtt_host="localhost", mqtt_port=1)
    down = ResultPublisher(offline)
    engine = _pipeline(seeded, down)

    outcome = await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    await down.aclose()

    assert outcome.action == ACTION_COMPUTED, "the result is computed and stored regardless"
    assert outcome.published is False
    assert down.failed >= 1
    async with seeded.begin() as connection:
        published_at = (
            await connection.execute(
                text("SELECT published_at FROM oee.shift_result WHERE oee_unit_id = :unit"),
                {"unit": unit.unit_id},
            )
        ).scalar()
    assert published_at is None, "an unsent result must stay unsent, or it is lost"

    # The broker comes back. Nothing about the inputs changed, so this is a republish of the
    # same revision - not a new one, and not a no-op.
    recovered = ResultPublisher(CONFIG)
    retry = _pipeline(seeded, recovered)
    payload = await _listen_while(
        lambda: retry.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(minutes=5))
    )
    await recovered.aclose()

    assert payload is not None, "the retry never reached the broker"
    assert payload["revision"] == 1
    async with seeded.begin() as connection:
        published_at = (
            await connection.execute(
                text("SELECT published_at FROM oee.shift_result WHERE oee_unit_id = :unit"),
                {"unit": unit.unit_id},
            )
        ).scalar()
    assert published_at is not None


async def test_a_republished_result_is_not_a_new_revision(seeded, unit, publisher):
    """
    `ACTION_REPUBLISHED` exists so that a broker outage does not inflate the revision
    number. A restatement means the numbers changed; a resend does not, and an auditor
    reading `revision 4` must be able to conclude the shift really was restated three times.
    """
    engine = _pipeline(seeded, publisher)
    await engine.run_shift(unit, WINDOW, COMPUTED_AT)
    async with seeded.begin() as connection:
        await connection.execute(
            text("UPDATE oee.shift_result SET published_at = NULL WHERE oee_unit_id = :unit"),
            {"unit": unit.unit_id},
        )

    again = await engine.run_shift(unit, WINDOW, COMPUTED_AT + timedelta(minutes=5))
    await publisher.aclose()

    assert again.action == ACTION_REPUBLISHED
    assert again.revision == 1
    assert publisher.published == 2
