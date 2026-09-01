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

from uns_opcua import prometheus_metrics as metrics
from uns_opcua.collector import Collector
from uns_opcua.forwarder import Forwarder, SpoolWriter, opened_spool
from uns_opcua.model_check import report_at_startup
from uns_opcua.opcua_config import MQTTConfig, OpcUaConfig, ServerConfig, SpoolConfig
from uns_opcua.spool import Spool, SpoolRow
from uns_opcua.tag_map import TagBinding, build_bindings, find_conflicts

LOGGER = logging.getLogger(__name__)


def build_bindings_for_all(servers: Sequence[ServerConfig]) -> list[TagBinding]:
    """Resolve every tag of every server, and refuse a mapping that cannot be right."""
    bindings = [binding for server in servers for binding in build_bindings(server)]
    conflicts = find_conflicts(bindings)
    if conflicts:
        for conflict in conflicts:
            LOGGER.error("Configuration conflict: %s", conflict)
        raise ValueError(f"{len(conflicts)} conflict(s) in the opcua tag configuration")
    return bindings


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
        asyncio.run(
            run_connector_keeping_metrics_alive(
                servers=OpcUaConfig.servers,
                spool_config=OpcUaConfig.spool,
                client_id=OpcUaConfig.client_id,
                qos=MQTTConfig.qos,
                queue_maxsize=OpcUaConfig.queue_maxsize,
                forward_batch_size=OpcUaConfig.forward_batch_size,
                backoff_max_s=OpcUaConfig.reconnect_backoff_max_s,
                model_check=OpcUaConfig.model_check,
            )
        )
    except KeyboardInterrupt:
        LOGGER.info("Shutting down on interrupt")


if __name__ == "__main__":
    main()
