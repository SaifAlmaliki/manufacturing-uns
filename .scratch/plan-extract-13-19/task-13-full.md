## Task 13: Persistent MQTT transport

`devices.py:84` opens and closes a broker connection *for every single message*. At today's 6 signals that is invisible; at ~400 signals with a 1 s tier it is thousands of TCP handshakes a minute, and it makes the connection state unobservable — which is why sub-project B's `broker_connected` could not be reported. This task also fixes the client-id collision at `devices.py:34` (`f"graphql-{time.time()}-..."`: wrong prefix, and `time.time()` collides when devices are constructed in the same millisecond).

**Files:**
- Modify: `99_simulator/src/uns_simulator/devices.py:29-96`
- Test: `99_simulator/test/test_devices.py`

**Interfaces:**
- Consumes: `MQTTConfig` (unchanged).
- Produces on `AsyncMQTTDevice`: attributes `.client_id: str`, `.connected: bool`, `.publish_ok: int`, `.publish_fail: int`, `.reconnects: int`, `.last_error: str | None`, `.last_publish_ts: float | None`; methods `async connect(self) -> bool`, `async disconnect(self) -> None`, and `health(self) -> dict[str, Any]` (the body sub-project B publishes as device health). `publish_parameter`'s signature is unchanged.

- [ ] **Step 1: Write the failing tests**

The existing `DummyClient` in `test_devices.py` records `(topic, parsed)` on publish and supports `__aenter__`/`__aexit__`. Extend it in place so it can also count context entries and be told to fail:

```python
# in 99_simulator/test/test_devices.py, extend the existing DummyClient
class DummyClient:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        self.published: list[tuple[str, dict]] = []
        self.enter_count = 0
        self.fail_on_enter = 0
        self.fail_on_publish = False

    async def __aenter__(self):
        self.enter_count += 1
        if self.fail_on_enter > 0:
            self.fail_on_enter -= 1
            raise OSError("broker refused the connection")
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    async def publish(self, topic, payload, **kwargs):  # noqa: ARG002
        if self.fail_on_publish:
            raise OSError("broker went away")
        self.published.append((topic, json.loads(payload)))
```

Keep whatever attributes the existing four tests already rely on. Then add:

```python
# append to 99_simulator/test/test_devices.py
@pytest.mark.asyncio
async def test_client_id_is_unique_per_device_and_names_the_simulator():
    first = AsyncMQTTDevice("dev-a", FakeHierarchy(), {})
    second = AsyncMQTTDevice("dev-a", FakeHierarchy(), {})
    assert first.client_id.startswith("uns_simulator-")
    assert "dev-a" in first.client_id
    assert first.client_id != second.client_id


@pytest.mark.asyncio
async def test_the_connection_is_opened_once_for_many_publishes():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    for index in range(20):
        assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, f"S{index}", {"value": index})
    assert device.client.enter_count == 1, "one connection, not one per message"
    assert len(device.client.published) == 20  # noqa: PLR2004
    assert device.connected is True
    assert device.publish_ok == 20  # noqa: PLR2004
    assert device.publish_fail == 0


@pytest.mark.asyncio
async def test_connect_retries_with_backoff_and_counts_reconnects(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(devices.asyncio, "sleep", fake_sleep)
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    device.client.fail_on_enter = 3
    assert await device.connect() is True
    assert device.connected is True
    assert sleeps == [1.0, 2.0, 4.0], "backoff must double"
    assert device.reconnects == 3  # noqa: PLR2004


@pytest.mark.asyncio
async def test_backoff_is_capped_at_the_configured_retry_interval(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(devices.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(devices.MQTTConfig, "retry_interval", 5, raising=False)
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    device.client.fail_on_enter = 6
    await device.connect()
    assert max(sleeps) == 5.0  # noqa: PLR2004
    assert sleeps[-1] == 5.0  # noqa: PLR2004


@pytest.mark.asyncio
async def test_a_publish_failure_marks_the_device_disconnected_and_is_counted():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    device.client.fail_on_publish = True
    assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1}) is False
    assert device.connected is False
    assert device.publish_fail == 1
    assert "broker went away" in device.last_error


@pytest.mark.asyncio
async def test_a_publish_failure_is_followed_by_a_reconnect_on_the_next_attempt():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    device.client.fail_on_publish = True
    await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1})
    device.client.fail_on_publish = False
    assert await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 2}) is True
    assert device.client.enter_count == 2  # noqa: PLR2004


@pytest.mark.asyncio
async def test_disconnect_is_idempotent():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.connect()
    await device.disconnect()
    await device.disconnect()
    assert device.connected is False


@pytest.mark.asyncio
async def test_health_reports_the_publish_counters():
    device = AsyncMQTTDevice("dev", FakeHierarchy(), {})
    await device.publish_parameter("G1", ParameterType.PROCESS_VALUE, "S", {"value": 1})
    health = device.health()
    assert health["connected"] is True
    assert health["publish_ok"] == 1
    assert health["publish_fail"] == 0
    assert health["last_error"] is None
    assert isinstance(health["last_publish_ts"], float)
```

Add `import json` and `from uns_simulator.devices import AsyncMQTTDevice` to the test file's imports if not already present.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/test_devices.py -v`
Expected: the four pre-existing tests still pass; the new ones fail on `AttributeError: 'AsyncMQTTDevice' object has no attribute 'client_id'`.

- [ ] **Step 3: Replace `AsyncMQTTDevice.__init__` (`devices.py:29-50`)**

```python
    def __init__(self, device_id: str, hierarchy: ISA95Hierarchy, mqtt_config: dict[str, Any]):
        self.device_id = device_id
        self.hierarchy = hierarchy
        self.mqtt_config = mqtt_config

        # uuid4, not time.time(): devices are constructed in a tight loop and a timestamp
        # collides. A duplicate client id makes the broker evict the earlier connection.
        self.client_id = f"uns_simulator-{device_id}-{uuid.uuid4().hex[:8]}"

        self.connected = False
        self.publish_ok = 0
        self.publish_fail = 0
        self.reconnects = 0
        self.last_error: str | None = None
        self.last_publish_ts: float | None = None
        self._stack: contextlib.AsyncExitStack | None = None
        self._running = False

        self.client = aiomqtt.Client(
            identifier=self.client_id,
            clean_session=MQTTConfig.clean_session,
            protocol=MQTTConfig.version,
            transport=MQTTConfig.transport,
            hostname=MQTTConfig.host,
            port=MQTTConfig.port,
            username=MQTTConfig.username,
            password=MQTTConfig.password,
            keepalive=MQTTConfig.keep_alive,
            tls_params=MQTTConfig.tls_params,
            tls_insecure=MQTTConfig.tls_insecure,
        )

        LOGGER.info("Initialized device: %s (client id %s)", device_id, self.client_id)
```

Replace `import random` / `import time` usage at the top with `import contextlib` and `import uuid` added to the import block. Leave `random` imported — `PLC`, `SCADA` and `HMI` still use it. Drop `import time` if nothing else uses it; ruff `F401` will say.

- [ ] **Step 4: Add `connect`, `disconnect` and `health`, and rewrite the publish body**

```python
    async def connect(self) -> bool:
        """Open one long-lived broker connection, retrying with exponential backoff.

        Backoff doubles from 1 s and is capped at MQTTConfig.retry_interval, so a broker
        that is down at startup does not turn into a hot loop and does not give up either.
        """
        if self.connected:
            return True
        cap = float(getattr(MQTTConfig, "retry_interval", 10) or 10)
        delay = 1.0
        while True:
            self._stack = contextlib.AsyncExitStack()
            try:
                await self._stack.enter_async_context(self.client)
            except Exception as exc:
                self.reconnects += 1
                self.last_error = str(exc)
                await self._stack.aclose()
                self._stack = None
                LOGGER.warning(
                    "Device %s could not connect (%s); retrying in %.1fs", self.device_id, exc, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, cap)
                continue
            self.connected = True
            LOGGER.info("Device %s connected to the broker", self.device_id)
            return True

    async def disconnect(self) -> None:
        """Close the connection. Safe to call when already disconnected."""
        self.connected = False
        if self._stack is None:
            return
        stack, self._stack = self._stack, None
        try:
            await stack.aclose()
        except Exception as exc:
            LOGGER.debug("Device %s disconnect raised %s", self.device_id, exc)

    def health(self) -> dict[str, Any]:
        """Connection and publish counters. Published as device health by sub-project B."""
        return {
            "device_id": self.device_id,
            "client_id": self.client_id,
            "connected": self.connected,
            "publish_ok": self.publish_ok,
            "publish_fail": self.publish_fail,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "last_publish_ts": self.last_publish_ts,
        }
```

Then in `publish_parameter`, replace the `async with self.client:` block (`devices.py:83-88`) with:

```python
            if not self.connected:
                await self.connect()

            await self.client.publish(topic, json.dumps(enriched_data))
            self.publish_ok += 1
            self.last_publish_ts = datetime.now().timestamp()
            LOGGER.debug(
                "Device %s published to %s: %s", self.device_id, topic, enriched_data.get("value", "N/A")
            )
            return True
```

and in the trailing `except Exception as e:` handler, mark the device as needing a reconnect before returning `False`:

```python
        except Exception as e:
            self.publish_fail += 1
            self.last_error = str(e)
            self.connected = False
            await self.disconnect()
            LOGGER.error("Publish error in device %s: %s", self.device_id, e)
            return False
```

Do not add counters to the `json.JSONDecodeError` branch — a malformed payload is a programming error in the caller, not a transport failure, and conflating the two would make `publish_fail` useless as a broker-health signal. Keep that branch returning `False` as it does today.

`test_the_connection_is_opened_once_for_many_publishes` passes because `connect()` is a no-op once `self.connected` is true; `test_a_publish_failure_is_followed_by_a_reconnect_on_the_next_attempt` passes because the failure path clears it. The pre-existing `test_publish_parameter_enriches_and_publishes`, which assigns `plc.client = DummyClient()` and calls `publish_parameter` directly, still passes: `connect()` enters the dummy's context successfully.

- [ ] **Step 5: Add `stop()` calling `disconnect()`**

`AsyncMQTTDevice.stop` (`devices.py:131-134`) currently only flips `_running`. Make it release the connection too:

```python
    async def stop(self) -> None:
        """Stop device operation and release the broker connection."""
        self._running = False
        await self.disconnect()
        LOGGER.info("Device %s stopped", self.device_id)
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -v`
Expected: all pass, including the four pre-existing `test_devices.py` tests and `test_hierarchy.py`'s `len(plcs) == 4`.

- [ ] **Step 7: Lint and commit**

```bash
cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/devices.py 99_simulator/test/test_devices.py
git commit -m "fix(simulator): reuse one MQTT connection per device with backoff and unique client ids"
```

---

