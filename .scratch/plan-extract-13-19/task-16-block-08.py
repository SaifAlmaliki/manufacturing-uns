        raw_config = load_simulator_config(settings)
        self.mqtt_config = settings.mqtt
        self.simulation_config = settings.simulation
        self.hierarchies = expand_hierarchy_paths(raw_config["hierarchy"])
        self.hierarchy = self.hierarchies[0]
