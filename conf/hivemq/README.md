# HiveMQ Edge config

`config.xml` is mounted into `uns_mqtt_broker` at `/opt/hivemq/conf/config.xml`.

Default file: MQTT TCP on `1883`, plus the optional `simulation` adapter. The stack
starts with no plant PLC.

**S7 and EtherNet/IP:** author host, port, controller type, and signals in Assets &
Connectivity (`#/connectivity/servers`). GraphQL upserts catalog-owned
`<protocol-adapter>` blocks (`adapterId` `catalog-<server id>`). Then recreate:

```bash
uv run uns_compose up -d --force-recreate uns_mqtt_broker
```

Do not hand-edit catalog-owned adapters. Do not add `<southboundMapping>` entries.
The generator preserves listeners, admin-api, comments, and the `simulation` adapter,
and writes 4-space indent matching `fixtures/adapters-unroutable.xml`.

**OPC UA:** engineers add servers in the same console. `opcua_client` polls that
catalog and publishes subscribed tags. Do not author OPC UA mappings in the Edge UI.

The Edge console on host port `18080` (default login `admin` / `hivemq`) is for
inspection. Mitsubishi is out of scope.
