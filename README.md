# Unified Name Space (UNS)

[![UNS Project](https://github.com/mkashwin/unifiednamespace/actions/workflows/python-app.yml/badge.svg)](https://github.com/mkashwin/unifiednamespace/actions/workflows/python-app.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

This project aims to create an open sourced option for setting up a Unified Namespace for IIOT transformation.

My objective is to build an open source, free to use UNS solution for the community which can be enhanced and adapted by other enthusiasts.

All components used in this solution are community versions and I do not own any rights on them. Most of them also provide a commercial / enterprise version which may also be considered to have better tool support.
I also used this, as an opportunity to learn Python.

If you are looking for an alternative Unified Namespace implementation with enterprise support, check out the [United Manufacturing Hub](https://learn.umh.app/), which is an Open-Source Helm Chart for Kubernetes.

## What is the Unified Name Space?

A Unified Namespace is an **_architecture_** that establishes a ***centralized repository*** of data, events,  information, and context **_across all IT and OT systems_** where any application or device can consume or publish data needed for a specific action via an **_event-driven_** and **_loosely coupled architecture_** ​along with the **_relevant context and history_**

This is a critical concept to allow scalability by preventing point to point connectivity.
![Credit Walter Reynolds -- IIOT University](./images/UNS.png)

### **References / Further Reading**

1. [Video explaining UNS](https://youtu.be/PB_9HIgSCWc)
1. [UNS Q&A by Walter Reynolds](https://youtu.be/IiUZTSGjCQI)
1. [Event driven architecture on Wikipedia](https://en.wikipedia.org/wiki/Event-driven_architecture)​
1. [Advantages of Event Driven Architecture](https://developer.ibm.com/articles/advantages-of-an-event-driven-architecture/)
1. [Unified Namespace as extended event-driven architecture](https://learn.umh.app/know/industrial-internet-of-things/techniques/unified-namespace/)

---

## **Architecture**

The overall architecture and the deployment setup is as follows

1. Factory1
   - K8s Cluster on the edge
   - MQTT edge installed on K8s
   - Bridge between Factory1 and the Enterprise MQTT clusters
   - Graph DB installed and running on docker
   - UNS graphdb client to persist messages to the Graph DB instance
   - UNS SparkplugB client to translate message from SparkPlug to UNS

1. Factory2
   - K8s Cluster on the edge
   - MQTT edge installed on K8s
   - Bridge between Factory2 and the Enterprise MQTT clusters
   - Graph DB installed and running on docker
   - UNS graphdb client to persist messages to the Graph DB instance
   - UNS SparkplugB client to translate message from SparkPlug to UNS

1. Enterprise on Cloud
   - K8s Cluster of the enterprise
   - MQTT Broker installed on K8s
   - TimescaleDB installed and running on docker / cluster / K8s / hosted service
   - Graph DB installed and running on docker / cluster / K8s / hosted service
   - Kafka cluster/ K8s / hosted service
   - GraphQL service running and connected to the cloud data stores
   - UNS graphdb client to persist messages to the Graph DB instance
   - UNS historian client to persist messages to the Graph DB instance
   - UNS Kafka listener to stream/convert MQTT messages to the Kafka instance
   - Prometheus scraping mapper metrics, and Grafana for dashboards

![Logical Architecture for implementing UNS](./images/UNS-Architecture.png)

The project vocabulary is defined in **[CONTEXT.md](./CONTEXT.md)**, and architectural
decisions that would otherwise be surprising are recorded in **[docs/adr](./docs/adr)**.

---

## **Local Docker Compose stack**

[`docker-compose.yml`](./docker-compose.yml) starts a **local, non-production** UNS: MQTT, databases, mappers, GraphQL, the console UI, and the device simulator. Do not use this compose file for production.

In Docker Desktop the project is `manufacturing-uns`. Container names look like `manufacturing-uns-<service>-1`.

**How to start** (from the repository root). Passwords live in `conf/.secrets.yaml` only — copy `conf/.secrets_template.yaml` if you have not already. Compose cannot read YAML, so use the wrapper that loads that file and then runs `docker compose`:

```bash
uv run uns_compose up -d --build
```

That command is the same on Windows, macOS, and Linux. The simulator publishes into the Compose MQTT broker (`uns_mqtt_broker`) automatically.

Start or stop **only** the simulator (the MQTT broker is started too if needed):

```bash
docker compose up -d uns_simulator
docker compose stop uns_simulator
docker compose start uns_simulator
docker compose logs -f uns_simulator
```

Do not use a Compose profile for this. Profiles hide a service from default `docker compose up`; the simulator is part of the default stack. Use the service name above instead.

To run the simulator on the host instead of in Docker (optional; uses the **repository-root** `.venv` from [Setting up the development environment](#setting-up-the-development-environment)):

```bash
uv run uns_simulator
```

### What each container does

| Docker Desktop name | Role |
| --- | --- |
| `uns_mqtt_broker` | MQTT backbone (EMQX). Devices, the simulator, and all mapper clients publish/subscribe here. Host ports: `1883` (MQTT), `8080` (MQTT over WebSocket). |
| `uns_neo4j_db` | Graph database that stores the current ISA-95 namespace as a tree of nodes. Host ports: `7474` (browser), `7687` (Bolt). |
| `uns_timescale_db` | Time-series historian (TimescaleDB / Postgres) that keeps a history of MQTT events. Host port: `5432`. |
| `tsdb_setup_script` | One-shot job that creates the historian database, user, tables (`unifiednamespace` + `uns_metrics`), continuous aggregates, and the compression / retention policies. It **exits after success** — a gray/stopped icon is normal, not a failure. |
| `asset_model_setup` | One-shot job that creates the `model` and `console` schemas, enrichment views, and imports the configured plant hierarchy. Also **exits after success**. Restart it (`docker compose up asset_model_setup`) after changing the hierarchy in `conf/settings.yaml`; running services pick up binding changes via Postgres `NOTIFY`. |
| `uns_kafka_broker` | Kafka broker for streaming UNS messages to other systems. Host port: `9092`. |
| `graphdb_client` | MQTT subscriber that writes live namespace messages into Neo4j (current state / tree). |
| `historian_client` | MQTT subscriber that writes events into TimescaleDB (history) and binds each distinct topic to the Asset Model after a successful persist. Shares one Postgres engine with `09_uns_model` (ADR-0004). |
| `opcua_client` | Read-only OPC UA edge connector: subscribes to PLC/SCADA nodes and publishes into the UNS with a disk-backed store-and-forward spool. Host port: `9093` (Prometheus metrics). With no `opcua.servers` configured it logs that there is nothing to collect, stays up serving Prometheus metrics on `9093`, and does not connect to a PLC. |
| `spb_mapper_client` | Sparkplug B translator: listens on Sparkplug topics, decodes protobuf, republishes JSON on the ISA-95 UNS topics. |
| `kafka_mapper_client` | MQTT-to-Kafka bridge: copies UNS MQTT messages onto Kafka topics. |
| `uns_simulator` | Synthetic PLC / HMI / SCADA publisher used for local demos. Not for production. |
| `oee_client` | Computes shift OEE from the historised `uns_metrics` rows and publishes each result to `<line>/KPI/ShiftOee`. Reads the historian, writes the `oee` schema, never writes to a control system (ADR-0008). Metrics on `9095`, unpublished. |
| `graphql_server` | GraphQL API over MQTT (live), Neo4j (current tree), TimescaleDB (history), Postgres `model` / `console` (Asset Model and Alert Rules), and Kafka. Host port: **`8000`** (`http://localhost:8000/graphql`). |
| `uns_frontend` | Web console for the namespace tree, payload inspector, live feed, search, and historian. Host port: **`8088`** (`http://localhost:8088`). The browser calls GraphQL on port `8000`. |
| `uns_prometheus` | Scrapes the `/metrics` endpoints exposed by the mapper clients. Host port: `9090`. |
| `uns_grafana` | Dashboards for Process Visualization (plant measurements from `uns_metrics_1m_enriched`), OEE (shift results and downtime from the `oee` schema), and Platform Observability (platform health). Host port: **`3000`** (`http://localhost:3000`). Anonymous access is enabled — see [Known Limitations](#known-limitations--workarounds). |

Typical flow: **simulator or plant devices → MQTT → mapper clients → Neo4j / Timescale / Kafka → GraphQL → UI**,
with **mapper clients → Prometheus → Grafana** alongside it for platform health.

---

## **Technology Choices**

The following section lists the various options and technology choices that I evaluated and the reasoning for choosing them.
This should hopefully also give you possible alternatives to consider if you choose to implement and extend this for your needs.
The opinions below are my personal ones with no influence from the companies that built them

### **Clustering at the Edge with Kubernetes**

To run the MQTT broker on the Edge, a cluster is **_not_** a prerequisite. If you do not have a business need for a high availability MQTT cluster, running just a single instance ( probably within a docker) would be a lot more easier.

Even for a clustered setup most of the MQTT brokers do provide an option for clustering however running this cluster on K8s provides significant benefits for scaling, auto healing etc.

I evaluated the following K8s options because it needs to be a extremely light weight and high performant distribution to be able to run on the edge (constrained environments). Any of these is a perfectly good choice depending on your context.

1. [MicroK8s](https://microk8s.io/)
1. [K3s](https://k3s.io/)

There are quite some comparisons between the the k8s distributions on the net so I am not going to list detailed comparison here.

I finally choose to go ahead with **_MicroK8s_** because

- Most of my environment was on Ubuntu hence enabling a snap for microk8s was very easy
- The inbuilt addons and the ease of enabling them without wading through YAML files
- The default CNI provided for the cluster is Calico which [claimed](https://www.suse.com/c/rancher_blog/comparing-kubernetes-cni-providers-flannel-calico-canal-and-weave/) to be more performant
- Setting up a High Availability cluster is extremely easy by adding multiple master nodes

  > **Note:** Avoid setting up high availability and multiple masters for your edge cluster as this increases the resource consumption & load on the edge devices. A single master node should suffice majority of your availability requirements if you actually even need a k8s cluster on the edge in the first place.

- Having a bit more experience with Ubuntu I found the documentation and guides a lot more easy to find and follow, including the community support, especially troubleshooting.

However microk8s did show up some limitations as well as bugs. Details of these are in **[01_k8scluster](./01_k8scluster/README.md)**. The link will provide details of all the addons, workarounds etc. that I did for bringing up my cluster. If you choose to setup your k8s with a different distribution, each of those addons could be setup / configured albeit in a different manner.

Some key limitations to bear in mind

- I faced some stability issues while trying to run this lower raspberry pi (pi3)
- microk8s is not available for every linux distribution.

---

### **MQTT Broker**

The backbone of the **_Unified Name Space_** is the MQTT broker.

#### **Why MQTT**

The overall structure of the UNS is based on the hierarchical structure as defined in ISA-95 part 2.

> \<enterprise\>/\<facility\>/\<area\>/\<line\>/\<device\>

The level at which the message is published has a direct implication on it's time sensitivity as well as guidance on being processed at the edge or on the cloud.  
![ISA-95 Part 2](./images/ISA-95-part2.png)

I evaluated and read the user guides of the following brokers (open source versions only). All three also provide commercial / enterprise versions which is recommended for more robust setup and professional support

1. [EMQX](https://www.emqx.io/)
2. [VERNEMQ](https://vernemq.com/)
3. [HIVEMQ](https://www.hivemq.com)

While HIVEMQ has the best documentation and community support I decided try out EMQX for the following reasons

- EMQX is written in erlang which has a lower footprint than java (HIVEMQ).
- They also provide 2 versions of the broker, one specifically lightweight for edge deployment and the standard for enterprise or cloud deployment.

The details of setting up the MQTT cluster are provided in **[02_mqtt-cluster](./02_mqtt-cluster/README.md)**. The link provides the guidance to install EMQX on a K8s cluster using helm.

**_Having said that, any of the above three would be perfectly good selections because_**

- All the three have extension capabilities via standard as well as custom plugins. However I liked the rules plugin from EMQX which comes by default allowing for lot of flexibility for pre and post processing messages. Also EMQX seems to be supporting the ability to create plugins in multiple languages

- All three deploy very easily on K8s and all three have community (free) as well as commercial offering
- All three support **MQTT 5** which is critical for manufacturers. e.g. The concept of [Shared Subscriptions](https://www.hivemq.com/blog/mqtt5-essentials-part7-shared-subscriptions/) enables clustering of the subscribers in order to better scale message processing if needed)
- All three support **Sparkplug B**
- All three support MQTT bridging allowing copying data between edge to cloud instances
- Both [HiveMQ](hivemq.com/mqtt-cloud-broker/) and [EMQX](https://www.emqx.com/en/cloud) provide fully managed cloud services which might be interesting offer to explore for your cloud / enterprise MQTT Cluster

#### Broker Plugins

> **Important Note:** The community edition of these brokers do not provide all functionalities. e.g. EMQX community doesn't allow plugins to be triggered on message delivery (this is an enterprise feature). As I wanted this solution to be completely open source and free, I decided to write an MQTT client subscribing to `"#"`. This works but is less efficient than creating a plugin within the broker and natively persisting the messages to a database. You can further optimize this by subscribing to a subset e.g. `"<enterprise>/#"`
> However if you go for the enterprise version, I would recommend creating a plugin instead of the [MQTT Listeners](#plugin--mqtt-client-to-subscribe-and-write-to-the-above-databases) provided here for better performance. But for most scenarios, an MQTT client should suffice and be broker independent.

Hence I decided to write [my own plugin](#plugin--mqtt-client-to-subscribe-and-write-to-the-above-databases) as an MQTT client which listens to the broker and on message persists the message ( either the GraphDB or the Historian)

### **GraphDB**

Normally I configured the MQTT publishers to publish messages with retain flag so that consumers are able to get the latest message even if they weren't connected with broker at the time of publishing.

However I realized that, in order to merge messages, or provide the capability to add relationships across multiple messages, MQTT alone will not be able to support that. Hence after some deliberation decided to use a Graph Database.

This provide the flexibility of defining relationships , simple way representing your object hierarchy as well as support merging of attributes

I choose to go with **[Neo4J](https://neo4j.com/)** simply because it was the only graphDB I was aware of as well as the fact that it runs seamlessly on Kubernetes.
The GraphDB also allows for extremely fine grained access control across the nodes, specific sections of the tree as well as limit access to specific properties. Refer [Neo4j - Access Control](https://neo4j.com/docs/operations-manual/current/authentication-authorization/access-control/)

> **Important Note:** The clustering feature of neo4j on K8s is an enterprise feature and [not available in the community version](https://community.neo4j.com/t/neo4j-community-edition-on-kubernetes/4955)

### **Historian**

The other critical component of the **_Unified Name Space_** is the historian. This allows to keep a full history of all messages, entities and artifacts generated.
Since the graph databases are not suited for historian data (there were a couple of projects enhancing Neo4j but all were archived), it makes sense to delegate that to specialist.

I evaluated and read the user guides of the following historians

1. [InfluxDb](https://www.influxdata.com/) combined with Telegraf
1. [TimescaleDB](https://www.timescale.com/) combined with [MQTT Listeners](#plugin--mqtt-client-to-subscribe-and-write-to-the-above-databases)

Both of these are excellent options and have significant user adoption. InfluxDb combined with Telegraph provide a strong low code approach to the integration. Telegraf however did not have a plugin for Neo4j and InfluxDb does not support K8s. Given the stronger stability of postgres (on which TimescaleDB is built) as well as support for [JSON](https://docs.timescale.com/timescaledb/latest/how-to-guides/schema-management/json/) I decided to go ahead with **[TimescaleDB](https://www.timescale.com/)**

For production systems you might want to consider the cloud versions of the historians ([InfluxDB Cloud](https://www.influxdata.com/products/influxdb-cloud/) or [TimescaleDB](https://www.timescale.com/products#timescale-cloud)) for lower maintenance and higher scalability

#### Historian schema

The historian writes two tables in the same transaction:

| Table | Contents |
| --- | --- |
| `unifiednamespace` | The Historic Event exactly as published — full JSONB payload. The immutable record. |
| `uns_metrics` | A projection of that payload: every scalar leaf as one row, keyed by its dotted path (`Motor.Winding.Temperature`). Rebuildable from `unifiednamespace`. |

Storing the payload whole is right for fidelity but useless for time-series queries — the
measurement is buried in JSONB and there is no index that helps. `uns_metrics` exists so that
`time_bucket()` / `avg()` queries are possible at all. Grafana reads the
`uns_metrics_1m_enriched` view (Asset Model labels joined at read time) rather than raw
hypertables; see [ADR 0003](./docs/adr/0003-postgres-asset-model-and-read-time-enrichment.md).

Retention drops raw data earliest and coarse aggregates last: raw events 90 days,
`uns_metrics` 1 year, 1-minute aggregates 1 year, 1-hour aggregates 5 years, compression after
7 days. These are **engineering defaults, not a compliance judgement** — revisit them if
regulated retention applies to your process data. The reasoning is recorded in
[ADR 0002](./docs/adr/0002-uns-metrics-hypertable.md).

### **Plugin / MQTT Client to subscribe and write to the above databases**

Since I did not have the enterprise version of the MQTT brokers, I decided to develop a broker agnostic solution. Hence the MQTT client seems to be a the best option ( even if it may not be as performant as the Broker plugin/module).

- The MQTT listener to persist UNS messages & SPB messages to the GraphDB can be found at [03_uns_graphdb](./03_uns_graphdb/README.md)
- The MQTT listener to persist UNS messages & SPB messages to the Historian can be found at [04_uns_historian](./04_uns_historian/README.md)
- The MQTT listener to read SPB messages, translate and transform them to the UNS can be found at [05_sparkplugb](./05_sparkplugb/README.md)
- The MQTT listener to publish UNS messages, to a kafka topic [06_uns_kafka](./06_uns_kafka/README.md)
- A module which connects with all the data sources; Neo4j, TimescaleDB, Kafka and MQTT to provide GraphQL apis to query the UNS [07_uns_graphql](./07_uns_graphql/README.md)
- Prometheus and Grafana configuration for Process Visualization and Platform Observability [08_uns_observability](./08_uns_observability/README.md)
- The authored Asset Model in Postgres, which contextualizes and enriches everything the historian stores [09_uns_model](./09_uns_model/README.md)
- The shift OEE engine, which turns that history into Availability x Performance x Quality per line [12_uns_oee](./12_uns_oee/README.md)
- The read-only OPC UA edge connector that publishes PLC/SCADA tags into the UNS [10_uns_opcua](./10_uns_opcua/README.md)
- A simulator for test purposes [99_simulator](./99_simulator/README.md)

I choose to write the client in Python even thought Python is not as performant as Go, C or Rust primarily because

- In the OT space most professionals ( in my experience) were more familiar coding with Python than Go, C or Rust. Hence I hope this increases the adoptions and contributions from the community in further developing this tool
- Should a team want to further optimize the code, given the readability and the inline comments in the code, they are hopefully able to rewrite the application in their choice of language

### **Plugin / MQTT Client to translate SparkplugB messages to UNS Namespace**

Sparkplug B consist of three primary features in its definition.

1. The first is the MQTT topic namespace definition.
1. The second is the definition of the order and flow of MQTT messages to and from various MQTT clients in the system.
1. The final is the payload data format.
   As the messages are published in the Sparkplug Namespace , they are not visible in the UNS hierarchy which is based on ISA-95 part 2. Also given that they are packaged in protocol buffers, these message payloads are not easily understandable and need some parsing / transformation to a JSON structure.
   This plugin listens on the SparkplugB topic hierarchy and translate the protocol buffer messages into appropriate UNS messages
   The detailed description of the plugin can be found at [05_sparkplugb](./05_sparkplugb/README.md)

### **GraphQL Support**

GraphQL is a query language for APIs and a runtime for executing those queries with your existing data. It allows clients to request only the data they need and nothing more, enabling precise and efficient data fetching.
Some key benefits of adding this support to the UNS are:

1. **Simplified Data Access**: A Unified Namespace typically brings together diverse data sources or systems into a single cohesive structure. By integrating GraphQL capabilities, it provides a unified and simplified way to access and query this diverse dataset. GraphQL's flexible querying allows for precise data retrieval, avoiding the need to interact with each individual data source separately.
1. **Consolidated Querying**: With GraphQL, querying data from different sources becomes seamless. It allows for composing complex queries across multiple data sources within the Unified Namespace, retrieving precisely the required data without unnecessary overhead or complexity.
1. **Service/Node Discovery**:Given the contextual and hierarchical nature of the UNS, the ability to search for specific Nodes and/or Properties will significantly simplify data discovery and facilitate easier consumption by providing a coherent interface to access the combined data in the Unified Namespace
1. **Dynamic Data Retrieval**: GraphQL's nature allows for dynamic data retrieval, enabling clients to specify the exact fields, relationships, and data they need. This flexibility aligns well with the diverse nature of data sources within a Unified Namespace, allowing clients to fetch the required information efficiently.

### **Observability & Visualization**

**[Grafana](https://grafana.com/)** and **[Prometheus](https://prometheus.io/)** are part of the
stack, serving two jobs that are deliberately kept separate:

- **Process Visualization** — the plant's own measurements (temperature, flow rate). Reads the
  `uns_metrics_1m_enriched` view over the TimescaleDB data source so panels show line, machine,
  and unit of measure from the authored Asset Model.
- **Platform Observability** — the platform's own behaviour (throughput, persist failures,
  latency). Reads Prometheus.

Confusing the two is how a green health indicator ends up meaning nothing, so they never share a
data source. Details are in **[08_uns_observability](./08_uns_observability/README.md)**, and the
decision — including why this reverses an earlier choice to keep Grafana out of the architecture —
is recorded in [ADR 0001](./docs/adr/0001-grafana-for-visualization-and-observability.md).

Two constraints are worth knowing before you extend this:

- **Neo4j Community Edition has no metrics export at all** — Prometheus, JMX, CSV and Graphite are
  Enterprise-only. Every graph signal therefore has to come from the `03_uns_graphdb` mapper
  instrumenting itself. This is why the mappers expose their own `/metrics` endpoints
  (`historian_client:9091`, `graphdb_client:9092`) instead of relying on exporters alone.
  Exporters also cannot see failures that a mapper swallows internally.
- **There is no Neo4j data source for Grafana** in the plugin catalog. The Unified Namespace tree
  stays in the React console; Grafana is not where you browse the namespace. Of the three plugins
  in the abandoned `99_simulator/notes` sketch, only `grafana-mqtt-datasource` exists — which is
  why that sketch never started.

### **OEE**

**Overall Equipment Effectiveness** — Availability x Performance x Quality — is computed per
closed shift by **[12_uns_oee](./12_uns_oee/README.md)** from data already in the historian,
and published back into the namespace on `<line>/KPI/ShiftOee`.

It is deliberately not a live gauge. Availability is Run Time over *Loading Time*, and
Loading Time is not known until the shift closes — mid-shift, a changeover scheduled for the
last hour has not happened yet. A live number would either divide by elapsed time, which is a
different quantity, or read 40% at 08:00 on every shift ever run.

Two consequences are worth knowing before you rely on it:

- **A shift's number can change.** Late-arriving data and corrected downtime reasons both
  trigger a recomputation within `late_window_hours`. Each restatement bumps `revision` and
  moves the previous numbers to `oee.shift_result_revision`, so the change is visible rather
  than silent.
- **Undefined is null, never zero.** A shift with no Loading Time has `status`
  `NO_LOADING_TIME` and null ratios. A plant holiday therefore leaves a gap on the trend
  instead of a catastrophe.

The reasoning is recorded in
[ADR 0008](./docs/adr/0008-oee-computed-from-history-not-streamed.md).

### OPC UA client: [asyncua](https://github.com/FreeOpcUa/opcua-asyncio)

The only actively maintained pure-Python OPC UA stack with a native asyncio API, which
matters because the connector runs one session per server in one event loop. It also
ships an in-process `Server`, so the connector's subscription and deadband behaviour is
tested for real rather than mocked.

### Edge buffer: SQLite

The store-and-forward spool must survive a container restart and a week-long WAN outage,
which rules out an in-memory queue. SQLite in WAL mode is already on every Python
install, needs no daemon on the edge node, and its `AUTOINCREMENT` rowid gives FIFO —
and therefore per-topic ordering — for free.

## **Setting up the development environment**

The current project contains the following microservices

1. [01_k8scluster](./01_k8scluster/README.md): Scripts and utilities to create a K8s cluster (on the edge and in the cloud)
1. [02_mqtt-cluster](./02_mqtt-cluster/README.md): Scripts and utilities to create a MQTT cluster (on the edge and in the cloud). Common python package for all uns mqtt listeners and sparkplugB generated code and helper code
1. [03_uns_graphdb](./03_uns_graphdb/README.md): Python project for mqtt listener that persists all message of the UNS and SparkplugB namespaces to a GraphDB. Spb messages are translated from protocol buffers to JSON prior to persisting
1. [04_uns_historian](./04_uns_historian/README.md): MQTT listener that persists UNS and SparkplugB messages to TimescaleDB via SQLAlchemy Core on the shared `uns_model` engine, and binds topics to the Asset Model after each persist
1. [05_sparkplugb](./05_sparkplugb/README.md): Python project for mqtt listener that listens to the SparkplugB namespace and for translates relevant messages to publish to the UNS namespace
1. [06_uns_kafka](./06_uns_kafka/README.md): Python project for mqtt listener that subscribes to the MQTT broker and publishes to the KAFKA broker
1. [07_uns_graphql](./07_uns_graphql/README.md): GraphQL server over MQTT (live), Neo4j (current tree), TimescaleDB (history), Postgres `model` / `console` (authored Asset Model and Alert Rules), and Kafka
1. [08_uns_observability](./08_uns_observability/README.md): Prometheus scrape configuration and Grafana provisioning (data sources + dashboards). Configuration only — no Python package, so it is not part of the `uv` workspace and has no tests
1. [09_uns_model](./09_uns_model/README.md): Python project holding the authored Asset Model (the ISA-95 hierarchy, equipment facts and units of measure) in Postgres via SQLAlchemy and Alembic, plus the views that enrich time-series rows with it at read time
1. [10_uns_opcua](./10_uns_opcua/README.md): Read-only OPC UA edge connector that subscribes to PLC/SCADA nodes and publishes them into the Unified Namespace with disk-backed store-and-forward
1. [11_frontend](./11_frontend/README.md): React console that talks only to GraphQL — Asset Model–first tree, payload inspector with read-time enrichment, live feed, search, and historian
1. [12_uns_oee](./12_uns_oee/README.md): Python project that computes OEE for closed shifts from historised UNS data, stores the result and its downtime breakdown in the `oee` schema, and publishes it back to MQTT
1. [99_simulator](./99_simulator/README.md): Python project for simulating data creation to the UNS. _*NOT TO BE USED IN PRODUCTION*_

Python packages are a **uv workspace**. Create **one** virtualenv at this repository root. Do not run `uv venv` inside a module folder (`03_uns_graphdb/.venv`, `99_simulator/.venv`, and so on): those duplicate the workspace env and make the editor pick the wrong interpreter.

This has been tested on **Unix(bash)**, **Windows(powershell)** and **Mac(zsh)**

```bash
python -m pip install --upgrade pip uv
uv venv
uv sync
```

Open the repository root in VS Code / Cursor and select the interpreter at `.venv`. `uv run` from any workspace member then uses that environment.

The stack is meant to run under Docker Compose. Use the root `.venv` when you want to run a Python service or tests on the host instead (for example while iterating on one module). Point `conf/settings.yaml` at brokers and databases you can reach from the host — typically `localhost` and the published Compose ports.

```bash
uv run uns_graphdb
uv run uns_historian
uv run uns_spb_mapper
uv run uns_kafka_mapper
uv run uns_graphql_app
uv run uns_opcua
uv run uns_simulator
uv run uns_model_setup
```

### Running tests

```python
# run all tests
uv run pytest
```

```python
# run all tests excluding integration tests
uv run pytest -m "not integrationtest"
```

```python
# run all tests for a specific module
uv run pytest  ./02_mqtt-cluster
uv run pytest  ./03_uns_graphdb
uv run pytest  ./04_uns_historian
uv run pytest  ./05_sparkplugb
uv run pytest  ./06_uns_kafka
uv run pytest  ./07_uns_graphql
uv run pytest  ./09_uns_model
uv run pytest  ./12_uns_oee
uv run pytest  ./99_simulator
```

```python
# run all tests for a specific module excluding integration test
uv run pytest -m "not integrationtest" ./02_mqtt-cluster
uv run pytest -m "not integrationtest" ./03_uns_graphdb
uv run pytest -m "not integrationtest" ./04_uns_historian
uv run pytest -m "not integrationtest" ./05_sparkplugb
uv run pytest -m "not integrationtest" ./06_uns_kafka
uv run pytest -m "not integrationtest" ./07_uns_graphql
uv run pytest -m "not integrationtest" ./09_uns_model
uv run pytest -m "not integrationtest" ./12_uns_oee
# 99_simulator has no integration tests hence the normal call will suffice
```

## Known Limitations / workarounds

1. **Windows**: Allowing powershell to run scripts
   If you get windows security error for running scripts, please run this first

   ```bash
   powershell Set-ExecutionPolicy RemoteSigned
   ```

1. **pytest-xdist & VSCode**:
   To optimize and speed up the project is using the [pytest-xdist](https://pytest-xdist.readthedocs.io/en/latest/)
   This however has some challenges [Working with VSCode Issue](https://github.com/microsoft/vscode-python/issues/19374)
   As a workaround run all tests which are marked `@pytest.mark.xdist_group` via the command line instead of within VSCode

1. **pytest-asyncio & Integration Testing**:
   Similar to `pytest-xdist` I have also enabled `pytest-asyncio` for the project. While this has significantly decreased the execution time, for some integration tests ( marked by `@pytest.mark.integrationtest`) sometimes fail (_flaky tests_) if there is too much CPU / IO load. Executing them again normally works. Need to investigate how to make those more robust/race proof. The issue is not in the code but in the test case where the validation starts before the test data has completely been setup in the data store.

1. **Grafana / Prometheus is incomplete.** The observability stack is wired into
   `docker-compose.yml` but is **not yet working end to end**. Known issues:

   - `08_uns_observability/grafana/entrypoint.sh` calls `envsubst`, which is **not present in the
     `grafana/grafana` image**, so the container exits on start. Grafana interpolates `$VAR` in
     provisioning files natively, so this indirection can be removed entirely.
   - The dashboards reference data sources by `uid` (`prometheus`, `timescaledb`), but the
     provisioning file does not declare `uid:` fields, so panels will not bind to a data source.
   - Enabling compression on `unifiednamespace` conflicts with the surviving
     `unique_event UNIQUE (time, topic, client_id, mqtt_msg)` constraint: TimescaleDB requires every
     column of a unique constraint to be in `segmentby` or `orderby`. Recent versions warn, older
     versions error — and `ON_ERROR_STOP=1` means an error fails the whole DB setup. The constraint
     should be narrowed to `(time, topic, client_id)`, which also removes a btree index over entire
     payloads.
   - Only `03_uns_graphdb` and `04_uns_historian` are instrumented. `05_sparkplugb`,
     `06_uns_kafka` and `07_uns_graphql` expose no metrics, so Kafka mapper failures and Sparkplug
     alias-cache resets are still invisible.
   - No EMQX, `postgres_exporter` or Kafka JMX scrape targets are configured, so broker, database
     and Kafka metrics are absent and the community dashboards for them cannot be used.
   - Prometheus `remote_write` from edge to enterprise is not configured; the current setup is
     enterprise-only.

1. **The console's System Health panel is not real.** `11_frontend` derives all five component
   indicators from a single boolean — "did a GraphQL query return data" — so Neo4j or Kafka can be
   down while the panel reads `ONLINE`. It is intended to be replaced by an embedded Grafana
   dashboard (`GF_SECURITY_ALLOW_EMBEDDING` is already set) but that is not implemented yet.
   Until then, do not treat that panel as a health signal.

1. **Grafana runs with anonymous access.** `GF_AUTH_ANONYMOUS_ENABLED=true` with the `Admin` role,
   matching the rest of this stack, which has no authentication anywhere. This is a deliberate but
   real security gap: anyone who can reach port `3000` can read plant process data. See
   [ADR 0001](./docs/adr/0001-grafana-for-visualization-and-observability.md). Do not expose these
   ports outside a trusted network.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/mkashwin/unifiednamespace)
