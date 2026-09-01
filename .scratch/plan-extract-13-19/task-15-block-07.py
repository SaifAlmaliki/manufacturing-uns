    async def _stop_simulation(self):
        """Cleanly stop all devices"""
        self.clock.stop()
        for device in self.devices:
            await device.stop()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
