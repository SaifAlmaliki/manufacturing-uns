    async def stop(self) -> None:
        """Stop device operation and release the broker connection."""
        self._running = False
        await self.disconnect()
        LOGGER.info("Device %s stopped", self.device_id)
