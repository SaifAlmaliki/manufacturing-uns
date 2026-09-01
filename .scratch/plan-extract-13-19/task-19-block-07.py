        requested = profile_name or self.simulation_config.get("profile", "full")
        configured_seed = seed if seed is not None else self.simulation_config.get("seed")
        raw_config = load_simulator_config(settings)
        self.profile: LoadedProfile = load_profile(raw_config, requested, seed=configured_seed)
