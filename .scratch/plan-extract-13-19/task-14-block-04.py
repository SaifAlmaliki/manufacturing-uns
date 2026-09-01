        status_data = {
            'system_name': self.system_name,
            'system_status': 'Operational',
            'connected_devices': self.connected_devices,
            'data_points_per_second': random.randint(500, 1500),  # noqa: S311
