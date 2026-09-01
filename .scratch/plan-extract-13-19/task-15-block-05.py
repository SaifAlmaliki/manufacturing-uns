        self.devices = [
            *self.signal_devices,
            *self.create_plc(),
            *self.create_scada(),
            *self.create_hmi(),
        ]
        self.announce_device_count()

        # The clock is a task of its own: it advances the world, and self.tick evaluates
        # every signal on that same advance. Publishing is scheduled separately, per tier.
        self.clock.on_transition(
            lambda site, line, state: LOGGER.info("Plant %s/%s -> %s", site, line, state)
        )
        self.tasks.append(asyncio.create_task(self._run_clock()))

        for device in self.signal_devices:
            for tier in sorted(device.tiers):
                # Already multiplied by the profile's `tier_scale` by `load_profile`, so a
                # slow profile cannot be defeated by forgetting to scale here.
                interval = self.profile.tiers.get(tier, 0.0)
                if interval <= 0.0:
                    # tier 'event' (and any tier explicitly set to 0) publishes on change
                    # from the tick itself; scheduling it would be a busy loop.
                    continue
                self.tasks.append(asyncio.create_task(device.run_tier(tier, interval)))

        # `.get`, not `.interval`: the legacy devices keep the single flat interval, and tests
        # hand this class a plain dict rather than the Dynaconf settings object.
        interval = float(self.simulation_config.get("interval", 5.0))
        for device in self.devices:
            if isinstance(device, SignalDevice):
                continue
            self.tasks.append(asyncio.create_task(device.start(interval)))
