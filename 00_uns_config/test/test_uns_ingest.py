"""The Unified Namespace ingest policy is one module, used by every Mapper."""

from uns_config.loader import get_settings
from uns_config.uns_ingest import (
    MAPPER_ENVS,
    MAPPER_UNS_TOPICS,
    PLATFORM_OBSERVABILITY_PREFIX,
    classify_event_kind,
    is_historic_event_topic,
)


def test_plant_topics_are_historic_events():
    assert is_historic_event_topic("Server/OpcPlc/Telemetry/WaterTreatmentPlant/FT201/Value")
    assert is_historic_event_topic("HalabjaWTP/Halabja/Distribution/Train1/FT201")
    assert is_historic_event_topic("test/uns/edge/sim")
    assert is_historic_event_topic("spBv1.0/uns_group/DDATA/edge/device")


def test_platform_observability_is_not_a_historic_event():
    assert not is_historic_event_topic(f"{PLATFORM_OBSERVABILITY_PREFIX}simulator/Instance01/status")
    assert not is_historic_event_topic("uns/platform/simulator/Instance01/device/main-meter/health")
    assert not is_historic_event_topic("")


def test_mapper_subscription_is_the_whole_namespace():
    assert MAPPER_UNS_TOPICS == ["#"]


def test_shipped_mapper_environments_subscribe_to_the_uns():
    for env in MAPPER_ENVS:
        get_settings.cache_clear()
        settings = get_settings(env)
        assert settings.get("mqtt.topics") == MAPPER_UNS_TOPICS
    get_settings.cache_clear()


def test_classify_event_kind_for_uns_telemetry():
    assert classify_event_kind("Enterprise/PlantA/Device/Temperature") == "telemetry"


def test_classify_event_kind_for_sparkplug_transport_and_control():
    assert classify_event_kind("spBv1.0/uns_group/NDATA/eon1") == "sparkplug_raw"
    assert classify_event_kind("spBv1.0/uns_group/DDATA/eon1/device1") == "sparkplug_raw"
    assert classify_event_kind("spBv1.0/uns_group/NBIRTH/eon1") == "lifecycle"
    assert classify_event_kind("spBv1.0/uns_group/NDEATH/eon1") == "lifecycle"
    assert classify_event_kind("spBv1.0/STATE/scada_1") == "lifecycle"
    assert classify_event_kind("spBv1.0/uns_group/NCMD/eon1") == "command"
    assert classify_event_kind("spBv1.0/uns_group/DCMD/eon1/device1") == "command"
