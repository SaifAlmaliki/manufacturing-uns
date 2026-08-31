"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

MQTT listener that listens to ISA-95 UNS and SparkplugB and persists all messages to the Historian
"""

import asyncio
import logging
import random
import time

from uns_model.engine import Database
from uns_model.repositories import AssetModelRepository
from uns_model.topic_binder import TopicBinder
from uns_mqtt.mqtt_listener import UnsMQTTClient

from uns_historian.historian_config import HistorianConfig, MQTTConfig
from uns_historian.historian_handler import HistorianHandler
from uns_historian.prometheus_metrics import (
    MESSAGES_RECEIVED,
    PERSIST_DURATION,
    PERSIST_FAILURE,
    PERSIST_SUCCESS,
    start_metrics_server,
)

LOGGER = logging.getLogger(__name__)


class UnsMqttHistorian:
    """
    MQTT listener that listens to ISA-95 UNS and SparkplugB and
    persists all messages to the Historian
    """

    def __init__(self, loop=None):
        self.client_id = f"historian-{time.time()}-{random.randint(0, 1000)}"  # noqa: S311
        self.uns_client: UnsMQTTClient = UnsMQTTClient(
            client_id=self.client_id,
            clean_session=MQTTConfig.clean_session,
            userdata=None,
            protocol=MQTTConfig.version,
            transport=MQTTConfig.transport,
            reconnect_on_failure=MQTTConfig.reconnect_on_failure,
        )
        # Callback messages
        self.uns_client.on_message = self.on_message
        self.uns_client.on_disconnect = self.on_disconnect
        self.loop = loop or asyncio.get_event_loop()
        self.loop.run_until_complete(HistorianHandler.get_shared_pool())
        # Resolves each new topic to its Asset once, so that the enriched views can
        # join on equality instead of matching prefixes per row (ADR-0003).
        self.topic_binder = TopicBinder(AssetModelRepository(Database.shared("historian")))
        self.uns_client.run(
            host=MQTTConfig.host,
            port=MQTTConfig.port,
            username=MQTTConfig.username,
            password=MQTTConfig.password,
            tls=MQTTConfig.tls,
            keepalive=MQTTConfig.keepalive,
            topics=MQTTConfig.topics,
            qos=MQTTConfig.qos,
        )

    def on_message(self, client, userdata, msg):
        """
        Callback function executed every time a message is received by the subscriber
        """
        LOGGER.debug("{Client: %s,Userdata: %s,Message: %s,}", client, userdata, msg)

        try:
            # get the payload as a dict object
            filtered_message = self.uns_client.get_payload_as_dict(
                topic=msg.topic, payload=msg.payload, mqtt_ignored_attributes=MQTTConfig.ignored_attributes
            )

            MESSAGES_RECEIVED.inc()

            # Async Historian persistence method — result is inspected via callback.
            async def run_async_handler():
                with PERSIST_DURATION.time():
                    async with HistorianHandler() as uns_historian_handler:
                        await uns_historian_handler.persist_mqtt_msg(
                            client_id=client._client_id.decode(),
                            topic=msg.topic,
                            timestamp=float(filtered_message.get(MQTTConfig.timestamp_key, time.time() * 1000)),
                            message=filtered_message,
                        )
                PERSIST_SUCCESS.inc()
                # After the measurement is safely stored: binding is for context,
                # and TopicBinder swallows its own failures for that reason.
                await self.topic_binder.observe(msg.topic)

            future = asyncio.run_coroutine_threadsafe(run_async_handler(), self.loop)
            future.add_done_callback(self._on_persist_done)

        except SystemError as system_error:
            LOGGER.error(
                "Fatal Error while parsing Message: %s\nTopic: %s \nMessage:%s\nExiting.........",
                system_error,
                msg.topic,
                msg.payload,
                stack_info=True,
                exc_info=True,
            )
        except Exception as ex:
            LOGGER.error(
                "Error persisting the message to the Historian DB: %s\nTopic: %s \nMessage:%s",
                ex,
                msg.topic,
                msg.payload,
                stack_info=True,
                exc_info=True,
            )

    @staticmethod
    def _on_persist_done(future: asyncio.Future) -> None:
        """Log and count failures from the awaited persist coroutine."""
        try:
            future.result()
        except Exception as ex:
            PERSIST_FAILURE.labels(reason=type(ex).__name__).inc()
            LOGGER.error(
                "Error persisting the message to the Historian DB: %s",
                ex,
                stack_info=True,
                exc_info=True,
            )

    def on_disconnect(
        self,
        client,  # noqa: ARG002
        userdata,  # noqa: ARG002
        flags,  # noqa: ARG002
        reason_codes,
        properties=None,  # noqa: ARG002
    ) -> None:
        """
        Callback function executed every time the client is disconnected from the MQTT broker
        """
        if reason_codes != 0:
            LOGGER.error("Unexpected disconnection.:%s", reason_codes, stack_info=True)
        # dont close the DB Pool as the client may disconnect multiple times and reconnect


def main():
    """
    Main function invoked from command line
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    uns_mqtt_historian = None

    try:
        start_metrics_server(HistorianConfig.metrics_port)
        uns_mqtt_historian = UnsMqttHistorian(loop)
        uns_mqtt_historian.uns_client.loop_start()
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if uns_mqtt_historian is not None:
            uns_mqtt_historian.uns_client.loop_stop()
            uns_mqtt_historian.uns_client.disconnect()
        loop.run_until_complete(HistorianHandler.close_pool())
        loop.run_until_complete(Database.close_shared())
        loop.close()


if __name__ == "__main__":
    main()
