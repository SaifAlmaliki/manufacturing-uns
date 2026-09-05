"""Catalog → ServerConfig translation for the OPC UA connector.

The console's Connectivity catalog is the source of truth for which servers to
dial and which nodes to subscribe to. `servers_from_catalog` is the pure fold
that turns catalog specs into the `ServerConfig`/`TagConfig` the supervisor
already consumes; `main.py` calls it on startup, falling back to YAML when the
catalog is empty or unreachable so YAML-only deploys still work.
"""

from collections.abc import Mapping, Sequence

from uns_model.connectivity import ConnectivityServerSpec, ConnectivityTagSpec
from uns_opcua.opcua_config import ServerConfig, TagConfig

DEFAULT_PUBLISHING_INTERVAL_MS = 200


def servers_from_catalog(
    servers: Sequence[ConnectivityServerSpec],
    tags_by_server_id: Mapping[str, Sequence[ConnectivityTagSpec]],
) -> tuple[ServerConfig, ...]:
    """
    Fold the catalog into the supervisor's `ServerConfig` shape.

    Only subscribed tags are carried; a server with zero subscribed tags (or no
    entry in `tags_by_server_id`) is skipped, so a partially-configured catalog
    does not produce a collector that dials a PLC with nothing to read.

    Each subscribed tag becomes a `TagConfig` whose `asset` and `mqtt_topic` are
    the engineer-edited topic: the catalog owns the topic, and the supervisor
    republishes the node under it verbatim.
    """
    configs: list[ServerConfig] = []
    for server in servers:
        subscribed = [tag for tag in tags_by_server_id.get(server.id, ()) if tag.subscribed]
        if not subscribed:
            continue
        configs.append(
            ServerConfig(
                name=server.name,
                url=server.endpoint,
                publishing_interval_ms=DEFAULT_PUBLISHING_INTERVAL_MS,
                tags=tuple(
                    TagConfig(
                        node_id=tag.node_id,
                        asset=tag.mqtt_topic,
                        metric_path="",
                        mqtt_topic=tag.mqtt_topic,
                    )
                    for tag in subscribed
                ),
            )
        )
    return tuple(configs)
