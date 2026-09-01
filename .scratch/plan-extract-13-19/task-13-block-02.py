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
