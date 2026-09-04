---
status: accepted
---

# Site Instances keep HiveMQ Edge and local Timescale; the cloud is an optional hop

Date: 2026-09-04

## Status

Accepted

## Context

Compose now runs `hivemq/hivemq-edge` as `uns_mqtt_broker`, with northbound S7,
EtherNet/IP, and OPC UA adapters authored in `conf/hivemq/`. That cut replaced
EMQX in the running stack. Older README and `02_mqtt-cluster` text still describe
an EMQX edge/enterprise mesh and put Timescale only in the cloud.

The platform has to do two jobs that look like they fight:

- A facility must keep publishing, and operators must still read Historic Events,
  when the WAN is down.
- Manufacturing, process, and laboratory publishers at many sites have to be
  analysed together. That work does not fit on a plant historian.

It is easy to collapse those jobs into “deploy Edge everywhere and dump into
Kafka on AWS.” That drops the local historian and treats Kafka as the Unified
Namespace.

## Decision

1. **HiveMQ Edge is the site broker.** A Site Instance does not run EMQX. Edge
   is both the local MQTT backbone and the OSS plant ingest. Mappers stay MQTT
   clients; the HiveMQ Kafka extension is commercial and is not the bridge.
2. **Timescale stays on the Site Instance.** The local historian is not a cache
   of the cloud. Process Visualization at the plant reads the site store.
3. **Multi-site analysis is an Enterprise Instance, not a Kafka-only hub.**
   Site traffic reaches the centre by MQTT bridge onto enterprise MQTT. Mappers
   there fill the enterprise graph, historian, and Kafka. Kafka is the seam for
   further analysis — including consumers you attach in AWS or Azure — not the
   collection bus.
4. **AWS and Azure are locations for an Enterprise Instance and its consumers.**
   The platform does not ship an AWS or Azure landing zone. The same enterprise
   services can run on-prem. Cloud warehouses, notebooks, and MES subscribe to
   Kafka (or to GraphQL) after the hop.

Local Compose remains one Instance with every service, used for development. It
is the Site Instance shape plus Kafka in the same file, not a multi-site mesh.

## Consequences

- README architecture and `CONTEXT.md` name Site Instance and Enterprise
  Instance. EMQX is historical evaluation, not the running broker.
- `02_mqtt-cluster` helm notes still install EMQX. They are superseded for the
  running platform; do not treat them as the site topology.
- CI mapper jobs may still use `emqx/emqx` as a generic MQTT 5 broker. That is
  a test double, not a deployment.
- The MQTT bridge from Site Instance to Enterprise Instance, and any AWS / Azure
  consumer of Kafka, are the intended hop. They are not a compose profile yet.
- Prometheus `remote_write` from site to enterprise remains the intended
  observability hop (ADR-0001) and is still unconfigured.
