"""Input object for canonical live stream filters (original MQTT browse paths)."""

from typing import Annotated

import strawberry
from pydantic import BaseModel, StringConstraints

from uns_graphql.graphql_config import REGEX_FOR_EXACT_MQTT_TOPIC


class KAFKATopic(BaseModel):
    topic: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            pattern=REGEX_FOR_EXACT_MQTT_TOPIC,
            min_length=1,
            max_length=100,
        ),
    ]


@strawberry.experimental.pydantic.input(
    model=KAFKATopic,
    all_fields=True,
    description=(
        "Exact original MQTT topic to filter live canonical events. "
        "Wildcards and infrastructure Kafka topic names are not supported."
    ),
)
class KAFKATopicInput:
    pass
