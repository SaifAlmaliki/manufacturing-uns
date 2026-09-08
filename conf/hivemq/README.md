# HiveMQ Edge config

`config.xml` is mounted into `uns_mqtt_broker` at `/opt/hivemq/conf/config.xml`.

Default file: MQTT TCP on `1883`, plus the optional `simulation` adapter. The stack
starts with no plant PLC.

**S7, EtherNet/IP, and OPC UA:** author the server and subscribed signals in
Assets & Connectivity (`#/connectivity/servers`). GraphQL upserts catalog-owned
`<protocol-adapter>` blocks (`adapterId` `catalog-<server id>`) and pushes the
same adapters to the running broker over the Edge Management API. MQTT can start
on Save. Browse and Test for OPC UA still use GraphQL → `uns_opcua`; they do
not talk to Edge. Recreate the broker only for an image upgrade or disaster
recovery:

    uv run uns_compose up -d --force-recreate uns_mqtt_broker

The Compose service `opcua_client` is not a default publisher. Start it only
with profile `legacy-opcua` if you must roll back to the old forwarder:

    uv run uns_compose --profile legacy-opcua up -d opcua_client

Do not hand-edit catalog-owned adapters. Do not add `<southboundMapping>` entries.
The generator preserves listeners, admin-api, comments, and the `simulation` adapter,
and writes 4-space indent matching `fixtures/adapters-unroutable.xml`.

The Edge console on host port `18080` (default login `admin` / `hivemq`) is for
inspection. Mitsubishi is out of scope.
