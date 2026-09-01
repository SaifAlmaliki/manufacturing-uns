    def messages_per_second(self) -> dict[str, float]:
        """Periodic publish rate per cadence tier, for the volume guard and the control API.

        Counts periodic publishing only. A `tier` whose interval is 0.0 - `event`, by
        default - publishes on change and contributes nothing here, which is honest rather
        than convenient: the two `bernoulli_event` detector faults in safety.yaml average
        about one message a fortnight each, and rounding that to zero is the right rounding.

        A signal on an unrecognised tier is skipped rather than crashing a status endpoint;
        `test_volume.py` is what makes such a signal fail loudly at the right time.
        """
        rates = dict.fromkeys(self.tiers, 0.0)
        for device in self.devices:
            if not device.enabled:
                continue
            for signal in device.signals:
                interval = self.tiers.get(signal.tier, 0.0)
                if interval > 0.0:
                    rates[signal.tier] += 1.0 / interval
        return rates
