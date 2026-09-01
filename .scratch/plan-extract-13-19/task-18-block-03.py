LEGACY_PLC_SENSORS = {
    ("001", "G1"): {"Temperature": (75.0, 2.0, "°C"), "Pressure": (150.0, 5.0, "psi")},
    ("002", "FillingMachine"): {"FlowRate": (450.0, 20.0, "L/min")},
}


@pytest.mark.parametrize("key", sorted(LEGACY_PLC_SENSORS))
def test_legacy_plc_templates_moved_across_unchanged(raw, key):
    """Spec 8.5 and 12: the pre-existing PLC signals must publish exactly as they did.

    `sensors:` became `signals:` and the file changed, but `equipment` decides the topic and
    base_value/variation/unit decide the payload, so those four are what this asserts. A
    `shape` key appearing on any of them would also be a change - `noise` is the default and
    the old generator had no other behaviour.
    """
    device_id, equipment = key
    sensors = LEGACY_PLC_SENSORS[key]
    template = next(item for item in raw["production"]["devices"] if str(item["id"]) == device_id)
    assert template["equipment"] == equipment
    assert template.get("target") is None, "an absent target means every production cell, which is what create_plc did"
    assert set(template["signals"]) == set(sensors)
    for name, (base_value, variation, unit) in sensors.items():
        signal = template["signals"][name]
        assert signal["base_value"] == base_value
        assert signal["variation"] == variation
        assert signal["unit"] == unit
        assert "shape" not in signal


def test_the_weather_station_reports_the_plant_context(raw):
    """The station must not be a second, disagreeing model of the same weather.

    SiteState already derives all five of these from plant.yaml. SolarIrradiance is exempt:
    PlantContext has no sunlight, so a `diurnal` of its own is the only option.
    """
    signals = next(item for item in raw["safety"]["devices"] if item["id"] == "WS-01")["signals"]
    from_context = {
        "AmbientTemp": "ctx.ambient_temp_c",
        "RelativeHumidity": "ctx.ambient_rh_pct",
        "WetBulbTemp": "ctx.wet_bulb_temp_c",
        "WindSpeed": "ctx.wind_speed_ms",
        "BarometricPressure": "ctx.barometric_mbar",
    }
    for name, path in from_context.items():
        assert signals[name]["shape"] == "derived"
        assert path in signals[name]["expr"], f"{name} must read {path}"
    assert signals["SolarIrradiance"]["shape"] == "diurnal"


def test_packml_state_code_maps_every_state(raw):
    """A state missing from the map publishes its own name where an integer is expected.

    SteppedSignal._translate falls through to the raw value on a miss, so an incomplete map
    fails as a type surprise on a consumer rather than at load time. Only this test catches it.
    """
    signals = next(item for item in raw["production"]["devices"] if item["id"] == "MES-01")["signals"]
    assert set(signals["PackMlStateCode"]["map"]) == set(PACKML_STATES)
    assert set(signals["DowntimeReason"]["map"]) == set(PACKML_STATES)
