# HiveMQ Edge config

`config.xml` is mounted into `uns_mqtt_broker` at `/opt/hivemq/conf/config.xml`.

Default file: MQTT TCP on `1883`, no protocol adapters. The stack starts with no PLC.

To ingest S7, EtherNet/IP, or OPC UA, copy a `<protocol-adapter>` from
`fixtures/adapters-unroutable.xml`, point `host` / `uri` at the real device, set
`topic` to the ISA-95 path, keep `includeTimestamp` true and `maxQos` 1, and
recreate the broker:

```bash
uv run uns_compose up -d --force-recreate uns_mqtt_broker
```

Do not add `<southboundMapping>` entries. The Edge console on host port `18080`
(default login `admin` / `hivemq`) is for inspection; git remains the source of
truth. Mitsubishi is out of scope.

**OPC UA via the console catalog:** Engineers add OPC UA servers in the web console
(Assets & Connectivity). The `opcua_client` Compose service polls that catalog and
publishes subscribed tags into the UNS. Do not author OPC UA mappings in the Edge
UI — Edge XML remains the path for S7 and EtherNet/IP only.
