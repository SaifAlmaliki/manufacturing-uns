"""
Supervisor for the OPC UA edge connector.

One process, one asyncio task per OPC UA server, one shared spool. Per-server task
supervision is what provides isolation — a PLC that is down or misconfigured must not
affect the others — so process boundaries are not needed for it. A plant with enough
servers to saturate one process would want a container per server instead.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime

from uns_model.connectivity import ConnectivityRepository
from uns_model.engine import Database
from uns_opcua import prometheus_metrics as metrics
from uns_opcua.catalog import servers_from_catalog
from uns_opcua.collector import Collector
from uns_opcua.forwarder import Forwarder, SpoolWriter, opened_spool
from uns_opcua.model_check import report_at_startup
from uns_opcua.opcua_config import MQTTConfig, OpcUaConfig, ServerConfig, SpoolConfig
from uns_opcua.spool import Spool, SpoolRow
from uns_opcua.tag_map import TagBinding, build_bindings, find_conflicts

LOGGER = logging.getLogger(__name__)

CATALOG_MODEL_ENV = "opcua"
CATALOG_POLL_INTERVAL_S = 5.0


def build_bindings_for_all(servers: Sequence[ServerConfig]) -> list[TagBinding]:
    """Resolve every tag of every server, and refuse a mapping that cannot be right."""
    bindings = [binding for server in servers for binding in build_bindings(server)]
    conflicts = find_conflicts(bindings)
    if conflicts:
        for conflict in conflicts:
            LOGGER.error("Configuration conflict: %s", conflict)
        raise ValueError(f"{len(conflicts)} conflict(s) in the opcua tag configuration")
    return bindings


async def load_servers_from_catalog(repository: ConnectivityRepository) -> tuple[ServerConfig, ...]:
    """
    Read the Connectivity catalog and fold it into `ServerConfig`s.

    Returns () when the catalog is empty or unreachable, so the caller can fall
    back to YAML. A catalog read failure is logged, not raised: a console that
    is briefly down must not stop an edge connector that already has a working
    YAML mapping.
    """
    try:
        servers = await repository.list_servers()
        tags_by_server_id = {server.id: await repository.list_subscribed_tags(server.id) for server in servers}
    except Exception:
        LOGGER.warning("Connectivity catalog read failed; falling back to opcua.servers", exc_info=True)
        return ()
    return servers_from_catalog(servers, tags_by_server_id)


def resolve_servers(catalog_servers: Sequence[ServerConfig]) -> tuple[ServerConfig, ...]:
    """Prefer the catalog when it yields servers with subscribed tags; else YAML."""
    return tuple(catalog_servers) if catalog_servers else OpcUaConfig.servers


def should_reload(prev: datetime | None, current: datetime | None) -> bool:
    """
    True when the catalog moved, or when it appears for the first time after a
    YAML-only startup.

    A catalog that goes from reachable to unreachable (current is None) does not
    trigger a reload: the running collectors keep going rather than being torn
    down to fall back to YAML. A catalog that was unreachable at startup
    (prev is None) and becomes reachable (current is set) does trigger, so the
    connector picks up the catalog the moment the console is back.
    """
    return current is not None and current != prev


async def _safe_catalog_updated_at(repository: ConnectivityRepository) -> datetime | None:
    """`catalog_updated_at`, or None when the catalog is unreachable or empty."""
    try:
        return await repository.catalog_updated_at()
    except Exception:
        return None


async def _poll_and_reload(
    repository: ConnectivityRepository,
    connector_task: asyncio.Task,
    last_updated_at: datetime | None,
    *,
    interval_s: float = CATALOG_POLL_INTERVAL_S,
) -> datetime | None:
    """
    Poll `catalog_updated_at` and cancel `connector_task` when it moves.

    Returns the timestamp that triggered the reload so the supervisor can use it
    as the baseline for the next poll. A poll that raises is treated as None:
    the supervisor keeps the current connectors rather than tearing them down.
    """
    while True:
        await asyncio.sleep(interval_s)
        current = await _safe_catalog_updated_at(repository)
        if should_reload(last_updated_at, current):
            LOGGER.info(
                "Connectivity catalog changed (updated_at %s -> %s); reloading connectors",
                last_updated_at,
                current,
            )
            connector_task.cancel()
            return current


async def run_connector(
    servers: Sequence[ServerConfig],
    spool_config: SpoolConfig,
    client_id: str,
    qos: int,
    queue_maxsize: int,
    forward_batch_size: int,
    backoff_max_s: float,
    model_check: bool,
) -> None:
    """Start the pipeline and run until cancelled."""
    if not servers:
        LOGGER.warning("No opcua.servers are configured; nothing to collect")
        return

    bindings = build_bindings_for_all(servers)
    queue: asyncio.Queue[SpoolRow] = asyncio.Queue(maxsize=queue_maxsize)

    async with opened_spool(Spool(spool_config)) as spool:
        tasks: list[asyncio.Task] = []
        try:
            if model_check:
                # Fire and forget: publishing must never wait on Postgres.
                tasks.append(asyncio.create_task(report_at_startup(bindings), name="model_check"))

            tasks.append(
                asyncio.create_task(
                    SpoolWriter(spool=spool, queue=queue).run(),
                    name="spool_writer",
                )
            )
            tasks.append(
                asyncio.create_task(
                    Forwarder(
                        spool=spool,
                        client_id=client_id,
                        qos=qos,
                        batch_size=forward_batch_size,
                        backoff_max_s=backoff_max_s,
                    ).run(),
                    name="forwarder",
                )
            )
            for server in servers:
                collector = Collector(
                    server=server,
                    bindings=[b for b in bindings if b.server_name == server.name],
                    queue=queue,
                    client_id=client_id,
                    qos=qos,
                    backoff_max_s=backoff_max_s,
                )
                tasks.append(asyncio.create_task(collector.run(), name=f"collector:{server.name}"))

            LOGGER.info(
                "OPC UA connector running: %s server(s), %s tag(s), client_id=%s",
                len(servers),
                len(bindings),
                client_id,
            )
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def _idle_when_no_servers() -> None:
    """Stay alive so a stock container still serves /metrics with nothing to collect."""
    LOGGER.warning("No opcua.servers are configured; idling so /metrics remains available")
    await asyncio.Event().wait()


async def run_connector_keeping_metrics_alive(
    servers: Sequence[ServerConfig],
    spool_config: SpoolConfig,
    client_id: str,
    qos: int,
    queue_maxsize: int,
    forward_batch_size: int,
    backoff_max_s: float,
    model_check: bool,
) -> None:
    """Run the connector; if there are no servers, idle until cancelled."""
    await run_connector(
        servers=servers,
        spool_config=spool_config,
        client_id=client_id,
        qos=qos,
        queue_maxsize=queue_maxsize,
        forward_batch_size=forward_batch_size,
        backoff_max_s=backoff_max_s,
        model_check=model_check,
    )
    if not servers:
        await _idle_when_no_servers()


def main() -> None:
    """`uns_opcua` entry point."""
    logging.basicConfig(level=logging.INFO)

    if not MQTTConfig.is_config_valid():
        LOGGER.error("mqtt.host is not configured")
        raise SystemExit(1)
    if not OpcUaConfig.client_id:
        LOGGER.error("opcua.client_id is required and must be stable across restarts")
        raise SystemExit(1)

    metrics.start_metrics_server(OpcUaConfig.metrics_port)
    try:
        asyncio.run(_supervise())
    except KeyboardInterrupt:
        LOGGER.info("Shutting down on interrupt")


async def _supervise() -> None:
    """
    Resolve servers (catalog first, YAML fallback), run the connector, and reload
    it when the Connectivity catalog changes.

    The metrics server is already up by the time we get here. The connector runs
    as a cancellable task alongside a 5s catalog poller; when the poller sees
    `catalog_updated_at` move, it cancels the connector and we loop, re-reading
    the catalog. A YAML-only startup (catalog empty or unreachable) still reloads
    the moment the catalog becomes available.
    """
    repository = ConnectivityRepository(Database.shared(CATALOG_MODEL_ENV))
    last_updated_at = await _safe_catalog_updated_at(repository)
    while True:
        catalog_servers = await load_servers_from_catalog(repository)
        servers = resolve_servers(catalog_servers)
        if catalog_servers:
            LOGGER.info("Using %s server(s) from the Connectivity catalog", len(catalog_servers))
        elif OpcUaConfig.servers:
            LOGGER.info("Catalog empty; using %s server(s) from opcua.servers", len(OpcUaConfig.servers))
        else:
            LOGGER.info("No servers configured; idling so /metrics stays available")

        connector_task = asyncio.create_task(
            run_connector_keeping_metrics_alive(
                servers=servers,
                spool_config=OpcUaConfig.spool,
                client_id=OpcUaConfig.client_id,
                qos=MQTTConfig.qos,
                queue_maxsize=OpcUaConfig.queue_maxsize,
                forward_batch_size=OpcUaConfig.forward_batch_size,
                backoff_max_s=OpcUaConfig.reconnect_backoff_max_s,
                model_check=OpcUaConfig.model_check,
            ),
            name="connector",
        )
        poller_task = asyncio.create_task(
            _poll_and_reload(repository, connector_task, last_updated_at),
            name="catalog_poller",
        )
        try:
            await connector_task
        except asyncio.CancelledError:
            # The poller cancels the connector and returns the new timestamp when the
            # catalog moves; that is the only restart we tolerate. A CancelledError that
            # arrives any other way is the process shutting down, and swallowing it
            # would restart the connector forever instead of letting the loop unwind.
            if poller_task.done() and not poller_task.cancelled():
                LOGGER.info("Reloading connectors after a connectivity catalog change")
            else:
                raise
        except Exception:
            # A config conflict or transient error must not spin the loop; back
            # off and let the next catalog change retry.
            LOGGER.exception("Connector exited unexpectedly; backing off before retry")
            await asyncio.sleep(CATALOG_POLL_INTERVAL_S)
        finally:
            poller_task.cancel()
            await asyncio.gather(poller_task, return_exceptions=True)
            if poller_task.done() and not poller_task.cancelled():
                last_updated_at = poller_task.result()


if __name__ == "__main__":
    main()
