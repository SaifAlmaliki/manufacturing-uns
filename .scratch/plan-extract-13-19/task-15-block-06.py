    async def _run_clock(self) -> None:
        """Advance the plant and evaluate every signal on the same tick."""
        tick_s = self.clock.tick_s
        self.clock.running = True
        try:
            while self.clock.running:
                self.clock.advance()
                self.tick(tick_s)
                await asyncio.sleep(tick_s)
        except asyncio.CancelledError:
            LOGGER.info("Plant clock cancelled")
            raise
        finally:
            self.clock.running = False
