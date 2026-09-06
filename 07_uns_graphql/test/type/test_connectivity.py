"""GraphQL connectivity enums must match the database vocabularies."""

from enum import Enum

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
    SignalDataType,
    SignalSemanticClass,
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
