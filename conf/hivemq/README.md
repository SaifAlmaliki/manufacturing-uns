# HiveMQ Edge config

HiveMQ Edge is the Site Instance broker: the local Unified Namespace and the
northbound ingest for S7, EtherNet/IP, and OPC UA. Timescale stays on the same
Instance. Connecting that Instance to an Enterprise Instance on AWS or Azure is
an MQTT bridge plus Kafka consumers — not a setting in this file. See
[ADR 0010](../../docs/adr/0010-site-instance-and-enterprise-cloud-hop.md).

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
