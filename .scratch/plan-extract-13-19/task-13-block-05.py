            if not self.connected:
                await self.connect()

            await self.client.publish(topic, json.dumps(enriched_data))
            self.publish_ok += 1
            self.last_publish_ts = datetime.now().timestamp()
            LOGGER.debug(
                "Device %s published to %s: %s", self.device_id, topic, enriched_data.get("value", "N/A")
            )
            return True
