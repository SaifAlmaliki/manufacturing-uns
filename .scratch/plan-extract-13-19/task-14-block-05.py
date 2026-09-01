# append to 99_simulator/test/test_devices.py
@pytest.mark.asyncio
async def test_scada_reports_the_real_connected_device_count():
    scada = devices.SCADA(FakeHierarchy(), {})
    scada.connected_devices = 47
    status = await scada.generate_system_status()
    assert status["connected_devices"] == 47  # noqa: PLR2004
