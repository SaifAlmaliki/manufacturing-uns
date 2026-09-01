    async def connect(self) -> bool:
        """Open one long-lived broker connection, retrying with exponential backoff.

        Backoff doubles from 1 s and is capped at MQTTConfig.retry_interval, so a broker
        that is down at startup does not turn into a hot loop and does not give up either.
        """
        if self.connected:
            return True
        cap = float(getattr(MQTTConfig, "retry_interval", 10) or 10)
        delay = 1.0
        while True:
            self._stack = contextlib.AsyncExitStack()
            try:
                await self._stack.enter_async_context(self.client)
            except Exception as exc:
                self.reconnects += 1
                self.last_error = str(exc)
                await self._stack.aclose()
                self._stack = None
                LOGGER.warning(
                    "Device %s could not connect (%s); retrying in %.1fs", self.device_id, exc, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, cap)
                continue
            self.connected = True
            LOGGER.info("Device %s connected to the broker", self.device_id)
            return True

    async def disconnect(self) -> None:
        """Close the connection. Safe to call when already disconnected."""
        self.connected = False
        if self._stack is None:
            return
        stack, self._stack = self._stack, None
        try:
            await stack.aclose()
        except Exception as exc:
            LOGGER.debug("Device %s disconnect raised %s", self.device_id, exc)

    def health(self) -> dict[str, Any]:
        """Connection and publish counters. Published as device health by sub-project B."""
        return {
            "device_id": self.device_id,
            "client_id": self.client_id,
            "connected": self.connected,
            "publish_ok": self.publish_ok,
            "publish_fail": self.publish_fail,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "last_publish_ts": self.last_publish_ts,
        }
