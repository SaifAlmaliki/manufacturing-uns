class SignalDevice(AsyncMQTTDevice):
    """A device whose behaviour is entirely declared by its DeviceSpec.

    Two responsibilities, deliberately kept apart:
      evaluate(dt)      - advance the signals. Called once per plant tick.
      publish_tier(t)   - send the current values for one cadence tier.

    Splitting them is what makes a 900 s meter reading and a 1 s vibration sample describe
    the same instant of the same world. The old PLC computed a value at publish time, so a
    slow publisher necessarily saw a coarser simulation.
    """

    def __init__(
        self,
        spec: DeviceSpec,
        mqtt_config: dict[str, Any],
        view: DeviceView,
        global_seed: int,
    ) -> None:
        super().__init__(spec.id, spec.path, mqtt_config)
        self.spec = spec
        self.view = view
        self.enabled = spec.enabled
        self.values: dict[str, Any] = {}
        self._last_published: dict[str, Any] = {}

        self._param_types: dict[str, ParameterType] = {}
        for signal_spec in spec.signals:
            try:
                self._param_types[signal_spec.name] = ParameterType(signal_spec.param_type)
            except ValueError:
                allowed = ", ".join(member.value for member in ParameterType)
                raise ValueError(
                    f"device {spec.id!r} signal {signal_spec.name!r}: unknown param_type "
                    f"{signal_spec.param_type!r} (allowed: {allowed})"
                ) from None

        # spec.signals is already in dependency order (profiles.expand_template sorted it),
        # so evaluating in sequence guarantees a derived signal sees this tick's siblings.
        self.signals = [
            build_signal(signal_spec, f"{spec.topic_prefix}/{signal_spec.name}", global_seed)
            for signal_spec in spec.signals
        ]
        self.tiers = frozenset(signal_spec.tier for signal_spec in spec.signals)

    def evaluate(self, dt: float) -> dict[str, Any]:
        """Advance every signal by `dt` seconds. Synchronous, and never publishes."""
        for signal in self.signals:
            self.values[signal.spec.name] = signal.next(dt, self.view, self.values)
        return self.values

    async def publish_tier(self, tier: str) -> int:
        """Publish the current value of every signal in `tier`. Returns the success count."""
        if not self.enabled:
            return 0
        published = 0
        for signal in self.signals:
            if signal.spec.tier != tier:
                continue
            value = self.values.get(signal.spec.name)
            if value is None:
                continue
            # The 'event' tier means "on change" - a door that stays shut says so once.
            if tier == "event" and self._last_published.get(signal.spec.name, object()) == value:
                continue
            payload = {
                "value": value,
                "unit": signal.spec.unit,
                "status": signal.status(),
                "quality": "Good",
            }
            if signal.spec.limits:
                payload["limits"] = signal.spec.limits
            if await self.publish_parameter(
                self.spec.equipment, self._param_types[signal.spec.name], signal.spec.name, payload
            ):
                self._last_published[signal.spec.name] = value
                published += 1
        return published

    async def run_tier(self, tier: str, interval: float) -> None:
        """Publish `tier` every `interval` seconds until stopped or cancelled."""
        self._running = True
        LOGGER.info("Device %s publishing tier %s every %.1fs", self.device_id, tier, interval)
        try:
            while self._running:
                await self.publish_tier(tier)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            LOGGER.info("Device %s tier %s cancelled", self.device_id, tier)
            raise

    def snapshot(self) -> list[dict[str, Any]]:
        """Describe every signal. Rendered by sub-project B's SignalInspector."""
        return [
            {
                "name": signal.spec.name,
                "shape": signal.spec.shape,
                "unit": signal.spec.unit,
                "precision": signal.spec.precision,
                "range": list(signal.spec.value_range) if signal.spec.value_range else None,
                "limits": dict(signal.spec.limits),
                "params": dict(signal.spec.params),
                "tier": signal.spec.tier,
                "param_type": signal.spec.param_type,
                "value": self.values.get(signal.spec.name),
                "status": signal.status(),
            }
            for signal in self.signals
        ]
