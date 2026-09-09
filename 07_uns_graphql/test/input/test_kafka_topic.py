"""Validation tests for live stream MQTT topic filters."""

import pytest
import strawberry
from pydantic import ValidationError

from uns_graphql.input.kafka import KAFKATopic, KAFKATopicInput

test_data_valid = [
    "Enterprise/PlantA/Area/Line/Device/Temperature",
    "Enterprise/PlantA/Area/Line",
    "valid_topic_1",
    "topic_123_with_underscores",
]

test_data_invalid = [
    "",
    "topic_with_invalid@character",
    "a" * 101,
    None,
    123,
    "graphql_test_a.b.c",
    "Enterprise/+/Temperature",
    "Enterprise/#",
    "uns.historic-events",
]


@pytest.mark.parametrize("topic", test_data_valid)
def test_valid_topics(topic):
    kafka_topic = KAFKATopic(topic=topic)
    assert kafka_topic.topic == topic


@pytest.mark.parametrize("topic", test_data_valid)
def test_valid_topics_input(topic):
    kafka_topic_input = KAFKATopicInput.from_pydantic(KAFKATopic(topic=topic))
    assert kafka_topic_input.topic == topic


@pytest.mark.parametrize("topic", test_data_invalid)
def test_invalid_topics(topic):
    with pytest.raises(ValidationError):
        KAFKATopic(topic=topic)


@pytest.mark.parametrize("topic", test_data_invalid)
def test_invalid_topics_input(topic):
    with pytest.raises(ValidationError):
        KAFKATopicInput.from_pydantic(KAFKATopic(topic=topic))


@pytest.mark.parametrize("topic", test_data_valid)
def test_strawberry_type(topic: str):
    @strawberry.type
    class Query:
        @strawberry.field
        def get_topic(self, inputs: KAFKATopicInput) -> str:
            return inputs.topic

    schema = strawberry.Schema(query=Query, types=[KAFKATopicInput])
    result = schema.execute_sync(
        query="query ($inputs: KAFKATopicInput!) { getTopic(inputs: $inputs) }",
        root_value=Query(),
        variable_values={"inputs": {"topic": topic}},
    )
    assert not result.errors
