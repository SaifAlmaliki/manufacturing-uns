    def __init__(self, device_id: str, hierarchy: ISA95Hierarchy, mqtt_config: dict[str, Any]):
        self.device_id = device_id
        self.hierarchy = hierarchy
        self.mqtt_config = mqtt_config

        # uuid4, not time.time(): devices are constructed in a tight loop and a timestamp
        # collides. A duplicate client id makes the broker evict the earlier connection.
        self.client_id = f"uns_simulator-{device_id}-{uuid.uuid4().hex[:8]}"

        self.connected = False
        self.publish_ok = 0
        self.publish_fail = 0
        self.reconnects = 0
        self.last_error: str | None = None
        self.last_publish_ts: float | None = None
        self._stack: contextlib.AsyncExitStack | None = None
        self._running = False

        self.client = aiomqtt.Client(
            identifier=self.client_id,
            clean_session=MQTTConfig.clean_session,
            protocol=MQTTConfig.version,
            transport=MQTTConfig.transport,
            hostname=MQTTConfig.host,
            port=MQTTConfig.port,
            username=MQTTConfig.username,
            password=MQTTConfig.password,
            keepalive=MQTTConfig.keep_alive,
            tls_params=MQTTConfig.tls_params,
            tls_insecure=MQTTConfig.tls_insecure,
        )

        LOGGER.info("Initialized device: %s (client id %s)", device_id, self.client_id)
