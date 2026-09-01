    def __init__(self, profile_name: str | None = None, seed: int | None = None):
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(settings.hierarchy)
        self.hierarchy = self.hierarchies[0]
        self.plc_templates = list(settings.get("plc") or [])
        self.equipment_fallback = settings.get("equipment.mixer_tank")
        self.devices: list = []
        self.tasks: list[asyncio.Task] = []

        requested = profile_name or self.simulation_config.get("profile", "full")
        self.profile: LoadedProfile = load_profile(load_simulator_config(settings), requested, seed=seed)
        self.clock = PlantClock(self.profile.context, tick_s=float(self.simulation_config.get("tick_s", 1.0)))
        self.signal_devices: list[SignalDevice] = self.create_signal_devices()
        LOGGER.info(
            "Loaded profile %s: %d devices, %d signals across %s",
            self.profile.name,
            self.profile.report.devices,
            self.profile.report.signals,
            ", ".join(sorted(self.profile.report.per_family)) or "no families",
        )
        for warning in self.profile.report.warnings + self.profile.report.unmatched_templates:
            LOGGER.warning("profile %s: %s", self.profile.name, warning)
