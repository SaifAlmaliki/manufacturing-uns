"""Entry point for the datalake Mapper."""

from __future__ import annotations

import logging
import signal
import threading

from confluent_kafka import Consumer

from uns_datalake.config import DatalakeConfig
from uns_datalake.mapper import KafkaLakeMapper, run_forever
from uns_datalake.metrics import DatalakeMetrics
from uns_datalake.stores import object_store_from_config

LOGGER = logging.getLogger(__name__)


def build_consumer(config: DatalakeConfig) -> Consumer:
    consumer_config = {
        "bootstrap.servers": config.bootstrap_servers,
        "group.id": config.group_id,
        "enable.auto.commit": False,
        "enable.auto.offset.store": False,
        "auto.offset.reset": "earliest",
        "max.poll.interval.ms": 300000,
        "socket.timeout.ms": 10000,
        "queued.max.messages.kbytes": 16384,
    }
    return Consumer(consumer_config)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = DatalakeConfig.from_settings()
    metrics = DatalakeMetrics(config.metrics_port)
    metrics.start()
    store = object_store_from_config(config)
    consumer = build_consumer(config)
    mapper = KafkaLakeMapper(consumer, store, config, metrics)

    stop_event = threading.Event()

    def _stop(*_args: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    consumer.subscribe([config.kafka_topic], on_assign=mapper.on_assign, on_revoke=mapper.on_revoke, on_lost=mapper.on_lost)
    try:
        run_forever(mapper, stop_event.is_set)
    except Exception:
        metrics.set_up(False)
        metrics.set_ready(False)
        LOGGER.exception("datalake mapper failed")
        raise


if __name__ == "__main__":
    main()
