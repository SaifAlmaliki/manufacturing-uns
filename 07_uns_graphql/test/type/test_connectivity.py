"""GraphQL connectivity enums must match the database vocabularies."""

from enum import Enum
from types import SimpleNamespace

import pytest
from uns_model.tables import (
    CONNECTIVITY_AUTH_MODES,
    CONNECTIVITY_SECURITY_MODES,
    CONNECTIVITY_SECURITY_POLICIES,
    SIGNAL_DATA_TYPES,
    SIGNAL_SEMANTIC_CLASSES,
)

from uns_graphql.type.connectivity import (
    ConnectivityAuthMode,
    ConnectivitySecurityMode,
    ConnectivitySecurityPolicy,
    ConnectivityTagType,
    SignalDataType,
    SignalSemanticClass,
    SubscribedSignalType,
)


@pytest.mark.parametrize(
    "graphql_enum, vocabulary",
    [
        (ConnectivityAuthMode, CONNECTIVITY_AUTH_MODES),
        (ConnectivitySecurityPolicy, CONNECTIVITY_SECURITY_POLICIES),
        (ConnectivitySecurityMode, CONNECTIVITY_SECURITY_MODES),
        (SignalSemanticClass, SIGNAL_SEMANTIC_CLASSES),
        (SignalDataType, SIGNAL_DATA_TYPES),
    ],
)
def test_enums_match_the_database_vocabulary(graphql_enum: type[Enum], vocabulary: tuple[str, ...]):
    assert {member.value for member in graphql_enum} == set(vocabulary)


def _tag_ns(*, asset: object | None = None, **fields: object) -> SimpleNamespace:
    values = dict(
        server_id="s1",
        node_id="ns=2;s=Temperature",
        browse_path="Objects/Temperature",
        display_name="Temperature",
        mqtt_topic="enterprise/site/temperature",
        subscribed=True,
        created_at=None,
        updated_at=None,
        asset_id=42 if asset is not None else None,
        asset=asset,
        unit_of_measure=None,
        semantic_class=None,
        data_type=None,
        labels=[],
    )
    values.update(fields)
    return SimpleNamespace(**values)


def test_from_tag_returns_asset_path_and_display_name():
    tag = _tag_ns(asset=SimpleNamespace(path="AcmeWater/Site1/Furnace", name="Furnace 1"))
    mapped = ConnectivityTagType.from_tag(tag)
    assert mapped.asset_path == "AcmeWater/Site1/Furnace"
    assert mapped.asset_display_name == "Furnace 1"


def test_from_tag_uses_segment_when_display_name_is_null():
    tag = _tag_ns(
        asset=SimpleNamespace(path="AcmeWater/Site1/Furnace", display_name=None, segment="Furnace"),
    )
    mapped = ConnectivityTagType.from_tag(tag)
    assert mapped.asset_path == "AcmeWater/Site1/Furnace"
    assert mapped.asset_display_name == "Furnace"


def test_subscribed_signal_from_tag_returns_asset_path_and_display_name():
    tag = _tag_ns(asset=SimpleNamespace(path="AcmeWater/Site1/Furnace", name="Furnace 1"))
    mapped = SubscribedSignalType.from_tag(tag, server_name="PLC1")
    assert mapped.asset_path == "AcmeWater/Site1/Furnace"
    assert mapped.asset_display_name == "Furnace 1"
