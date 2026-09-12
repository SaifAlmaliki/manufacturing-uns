"""Edge agent entrypoint."""

from __future__ import annotations

import logging
import signal
import sys
import uuid

from uns_edge_agent.config import AgentConfig
from uns_edge_agent.credentials import CredentialStore
from uns_edge_agent.cloud_client import CloudClient
from uns_edge_agent.edge_client import HiveMQEdgeClient
from uns_edge_agent.journal import Journal
from uns_edge_agent.polling import PollLoop
from uns_edge_agent.reconcile import Reconciler

LOGGER = logging.getLogger(__name__)


def run_agent(config: AgentConfig) -> None:
    credentials = CredentialStore(config.credentials_dir)
    if not credentials.has_credentials():
        raise SystemExit("credentials missing: run uns_edge_enroll first")

    journal = Journal(config.journal_path)
    journal.open()
    cloud_client = CloudClient(
        config.cloud_base_url,
        credentials,
        request_timeout_seconds=config.request_timeout_seconds,
        connect_timeout_seconds=config.connect_timeout_seconds,
    )

    edge_client = None
    reconciler = None
    boot_id = str(uuid.uuid4())
    if config.edge_api_url:
        edge_client = HiveMQEdgeClient(
            config.edge_api_url,
            username=config.edge_api_username,
            password=config.edge_api_password,
        )
        reconciler = Reconciler(
            edge_client,
            boot_id=boot_id,
            endpoint_allowlist=config.endpoint_allowlist,
        )

    def on_configuration(snapshot) -> None:
        LOGGER.info(
            "configuration revision=%s digest=%s received",
            snapshot.revision,
            snapshot.digest,
        )

    loop = PollLoop(
        cloud_client=cloud_client,
        journal=journal,
        on_configuration=on_configuration,
        edge_id_loader=lambda: credentials.load_manifest()["edge_id"],
        edge_client=edge_client,
        reconciler=reconciler,
    )
    loop.state.boot_id = boot_id
    journal.set_boot_id(boot_id)

    def _stop(*_args) -> None:
        LOGGER.info("shutdown requested")
        loop.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        loop.run_until_stopped()
    finally:
        if edge_client is not None:
            edge_client.close()
        journal.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = AgentConfig.from_env()
    try:
        run_agent(config)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
