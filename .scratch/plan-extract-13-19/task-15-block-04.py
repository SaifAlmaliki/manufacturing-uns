    def create_signal_devices(self) -> list[SignalDevice]:
        """One SignalDevice per resolved DeviceSpec, each with its own read-only view."""
        built: list[SignalDevice] = []
        for spec in self.profile.devices:
            # Only production areas have a LineState (spec 6.1: a compressor house has no
            # batch to be IDLE between), so a utility device's view carries `line=None` and
            # reads production through `serves` instead. The line key is `<Area>/<Line>`,
            # matching how `build_plant_context` registered it.
            line = f"{spec.path.area}/{spec.path.line}" if spec.path.kind == PRODUCTION_KIND else None
            view = DeviceView(self.profile.context, spec.path.site, line, spec.serves)
            built.append(SignalDevice(spec, self.mqtt_config, view, self.profile.seed))
        return built

    def tick(self, dt: float) -> None:
        """Advance every enabled device's signals. Called once per plant tick."""
        for device in self.signal_devices:
            if device.enabled:
                device.evaluate(dt)

    def announce_device_count(self) -> None:
        """Tell every SCADA how many devices actually exist, instead of a random guess."""
        count = len(self.signal_devices)
        for device in self.devices:
            if isinstance(device, SCADA):
                device.connected_devices = count

    def status(self) -> dict[str, Any]:
        """Runtime status. Sub-project B's GET /simulator/status extends this body."""
        per_tier: dict[str, int] = {}
        for device in self.signal_devices:
            for spec in device.spec.signals:
                per_tier[spec.tier] = per_tier.get(spec.tier, 0) + 1
        return {
            "profile": self.profile.name,
            "seed": self.profile.seed,
            "device_count": len(self.signal_devices),
            "signal_count": sum(len(d.spec.signals) for d in self.signal_devices),
            "tiers": dict(self.profile.tiers),
            "families": dict(self.profile.families),
            "per_tier": per_tier,
            "broker_connected": any(d.connected for d in self.signal_devices),
            "published_total": sum(d.publish_ok for d in self.signal_devices),
            "failed_total": sum(d.publish_fail for d in self.signal_devices),
            "tick_count": self.clock.tick_count,
        }
