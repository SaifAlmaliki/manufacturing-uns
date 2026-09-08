# Live HiveMQ Edge Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save on S7, EtherNet/IP, **and OPC UA** writes `config.xml` and live-applies HiveMQ Edge so MQTT starts without recreating the broker. Browse/Test stay on `uns_opcua`. Remap of `mqttTopic` rewrites historian. A datalake object-store port is types/tests only.

**Architecture:** XML `after_flush` still rolls back Save if the file write fails. After the row is stored, GraphQL calls the Edge Management API. Edge down: keep Save, `pending`. Topic remap: catalog + `rewrite_topic_prefix` in one failure domain (restore catalog if rewrite fails), then live apply. Default Compose does not start `opcua_client`.

**Tech Stack:** `httpx` in `00_uns_config`, `EdgeAdapterInput`, Strawberry GraphQL, React + Vitest, pytest + `httpx.MockTransport`.

**Specs:**
- `docs/superpowers/specs/2026-09-07-connectivity-edge-live-apply-design.md`
- `docs/superpowers/specs/2026-09-08-uns-edge-opcua-datalake-design.md`

## Global Constraints

- **Pending copy (verbatim):** `Waiting for HiveMQ Edge to apply`
- **`EDGE_APPLY_ERROR` is that sentence.** Model, GraphQL, and frontend tests must match it.
- **XML write still rolls back the Save.** Live apply never rolls back the Save.
- **Live apply includes S7, EIP, and OPC UA.** Browse/Test never call Edge.
- **Subscribe is not ISA-95-gated.** Browse-path `mqttTopic` is valid.
- **Historian rewrite failure on remap rolls back the catalog topic.** Edge down after a successful rewrite keeps the new topic and sets `pending`.
- **No southbound** on the API payload.
- **Do not create, update, or delete** `simulation` or any non-`catalog-*` adapter.
- **Catalog `adapterId`** remains `catalog-<server.id>`. `ethernet_ip` → `eip`. `opc_ua` → `opcua`.
- **OPC UA Edge auth is anonymous.** Config is `<uri>` from the catalog endpoint.
- **Payload is Edge native** (`includeTimestamp` true). Do not mimic `uns_opcua` `source` / `equipment`.
- **API timeout:** 10 seconds.
- **S7/EIP Test is TCP. OPC UA Test is the existing session probe.** Test does not push to Edge. If still `pending`, a successful Test keeps `EDGE_APPLY_ERROR`.
- **`last_error` is NOT NULL.** Cleared means `""`, not SQL NULL.
- **No live broker in pytest.** Mock HTTP only. No live S3/ADLS.
- **Do not implement on `main`.** Branch `feat/connectivity-edge-live-apply` from current `main`.
- **`uns_config` must not import `uns_model`.**
- **Do not delete `10_uns_opcua`.** Do not change `kafka_mapper` topic shape.

---

## File Structure

```
09_uns_model/src/uns_model/connectivity.py
09_uns_model/src/uns_model/tables.py
09_uns_model/test/test_connectivity.py

00_uns_config/pyproject.toml
00_uns_config/src/uns_config/hivemq_edge_xml.py
00_uns_config/src/uns_config/hivemq_edge_api.py
00_uns_config/src/uns_config/datalake.py
00_uns_config/test/test_hivemq_edge_api.py
00_uns_config/test/test_hivemq_edge_xml.py
00_uns_config/test/test_hivemq_edge_stack.py
00_uns_config/test/test_datalake.py
conf/settings.yaml
docker-compose.yml
docker-compose.dev.yml
08_uns_observability/prometheus/prometheus.yml

07_uns_graphql/src/uns_graphql/mutations/connectivity.py
07_uns_graphql/test/mutations/test_connectivity.py

11_frontend/src/components/connectivity/ConnectivityView.test.tsx
11_frontend/src/components/connectivity/ConnectivityView.tsx   # only if recreate sentence is hardcoded

conf/hivemq/README.md
docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md
```

**Task order:** 1 → 2 → **2b** → 3 → 4 → 5 → 6 → 7. GraphQL live apply (Task 3) is wrong if OPC UA adapters are still skipped. Do not start Task 3 until 2b is green.

---

### Task 1: Pending copy and `record_live_apply`

**Files:**
- Modify: `09_uns_model/src/uns_model/connectivity.py` (`EDGE_APPLY_ERROR`, new `record_live_apply`)
- Modify: `09_uns_model/test/test_connectivity.py`

**Interfaces:**
- Consumes: existing `ConnectivityRepository`, `ConnectivityServer.last_status` / `last_error`
- Produces: `EDGE_APPLY_ERROR = "Waiting for HiveMQ Edge to apply"`; `ConnectivityRepository.record_live_apply(self, server_ids: list[str], *, ok: bool) -> None`

- [ ] **Step 1: Write the failing tests**

In `09_uns_model/test/test_connectivity.py` change the existing copy assertion and add apply tests next to `record_test` tests (search `record_test` in this file and place them immediately after that class/section):

```python
def test_edge_apply_error_copy():
    assert EDGE_APPLY_ERROR == "Waiting for HiveMQ Edge to apply"


@pytest.mark.asyncio
async def test_record_live_apply_success_clears_pending(repository, session):
    server = await _insert_s7_server(session, last_status="pending", last_error=EDGE_APPLY_ERROR)
    await repository.record_live_apply([server.id], ok=True)
    row = await session.get(ConnectivityServer, server.id)
    assert row.last_status == "untested"
    assert row.last_error == ""


@pytest.mark.asyncio
async def test_record_live_apply_failure_sets_pending(repository, session):
    server = await _insert_s7_server(session, last_status="untested", last_error="")
    await repository.record_live_apply([server.id], ok=False)
    row = await session.get(ConnectivityServer, server.id)
    assert row.last_status == "pending"
    assert row.last_error == EDGE_APPLY_ERROR
```

Reuse whatever helper this file already uses to insert a connectivity server (do not invent a parallel insert). If the file uses a fake repository / in-memory session, match that. If helpers need `last_status` kwargs, add only that — do not create a new fixture module.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./09_uns_model/test/test_connectivity.py::test_edge_apply_error_copy ./09_uns_model/test/test_connectivity.py::test_record_live_apply_success_clears_pending ./09_uns_model/test/test_connectivity.py::test_record_live_apply_failure_sets_pending -v`

Expected: FAIL — copy still the recreate sentence; `record_live_apply` missing.

- [ ] **Step 3: Implement**

In `connectivity.py`:

```python
EDGE_APPLY_ERROR = "Waiting for HiveMQ Edge to apply"
```

Add next to `record_test`:

```python
    async def record_live_apply(self, server_ids: list[str], *, ok: bool) -> None:
        """Record whether HiveMQ Edge accepted the catalog adapters.

        Success is `untested` with an empty error: live apply is not a PLC probe.
        Failure is `pending` plus EDGE_APPLY_ERROR. Unknown ids are ignored.
        """
        if not server_ids:
            return
        values = (
            {"last_status": "untested", "last_error": "", "updated_at": func.now()}
            if ok
            else {
                "last_status": "pending",
                "last_error": EDGE_APPLY_ERROR,
                "updated_at": func.now(),
            }
        )
        async with self._database.session() as session:
            await session.execute(
                update(ConnectivityServer)
                .where(ConnectivityServer.id.in_(server_ids))
                .values(**values)
            )
```

Update the `save_server` docstring that still says the row is not live until recreate / Test.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest ./09_uns_model/test/test_connectivity.py -q --tb=line`

Expected: PASS. Any remaining recreate-sentence assertions in this file must be updated to the new copy in this task.

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/connectivity.py 09_uns_model/test/test_connectivity.py
git commit -m "fix(model): pending Edge apply means waiting, not recreate."
```

---

### Task 2: Edge Management API client

**Files:**
- Create: `00_uns_config/src/uns_config/hivemq_edge_api.py`
- Create: `00_uns_config/test/test_hivemq_edge_api.py`
- Modify: `00_uns_config/pyproject.toml` (add `httpx>=0.28.0,<1`)
- Modify: `conf/settings.yaml` (defaults)
- Modify: `docker-compose.yml` (`graphql_server` env `UNS_hivemq_edge__base_url`)

**Interfaces:**
- Consumes: `EdgeAdapterInput`, `EdgeTagInput`, `adapter_id_for`, `edge_data_type`, `_unique_tag_names` from `uns_config.hivemq_edge_xml`
- Produces: `EdgeApplyError`; `apply_catalog_adapters_live(adapters: list[EdgeAdapterInput], *, client: httpx.Client | None = None, base_url: str | None = None, username: str | None = None, password: str | None = None, timeout: float = 10.0) -> None`

Locked HTTP contract (`hivemq/hivemq-edge` OpenAPI):

| Step | Method | Path |
| --- | --- | --- |
| Auth | POST | `/api/v1/auth/authenticate` body `{"userName","password"}` → `{"token"}` |
| List | GET | `/api/v1/management/protocol-adapters/adapters` → `{"items":[{"id","type",...}]}` |
| Create | POST | `/api/v1/management/protocol-adapters/adapters/{adapterType}` body Adapter |
| Update | PUT | `/api/v1/management/protocol-adapters/adapters/{adapterId}` body Adapter |
| Delete | DELETE | `/api/v1/management/protocol-adapters/adapters/{adapterId}` |
| Tags | PUT | `/api/v1/management/protocol-adapters/adapters/{adapterId}/tags` body `{"items":[...]}` |
| Northbound | PUT | `/api/v1/management/protocol-adapters/adapters/{adapterId}/northboundMappings` body `{"items":[...]}` |

Auth header after login: `Authorization: Bearer <token>`.

Adapter body:

```json
{"id": "catalog-srv_1", "type": "s7", "config": {"host": "10.0.0.6", "port": 103, "controllerType": "S7_300"}}
```

EIP omits `controllerType`; `"type": "eip"`.

Tag item: `{"name": "<xml-safe unique name>", "description": "<display or node_id>", "definition": {"tagAddress": "%ID103", "dataType": "DINT"}}` for S7; EIP definition uses `address` not `tagAddress`.

Northbound item: `{"topic": "...", "tagName": "<same name>", "maxQoS": "AT_LEAST_ONCE", "includeTimestamp": true}`.

- [ ] **Step 1: Add httpx and write failing tests**

Add `httpx>=0.28.0,<1` to `00_uns_config/pyproject.toml` dependencies. From repo root run `uv lock` so the workspace picks it up.

Create `00_uns_config/test/test_hivemq_edge_api.py`:

```python
from uns_config.hivemq_edge_xml import EdgeAdapterInput, EdgeTagInput

from uns_config.hivemq_edge_api import EdgeApplyError, apply_catalog_adapters_live


def _s7(*, tags=()):
    return EdgeAdapterInput(
        server_id="srv_1",
        protocol="s7",
        host="10.0.0.6",
        port=103,
        controller_type="S7_300",
        tags=tags,
    )


def test_apply_creates_adapter_tags_and_mappings():
    calls: list[tuple[str, str, object]] = []

    def handler(request):
        calls.append((request.method, request.url.path, request.read()))
        if request.url.path.endswith("/auth/authenticate"):
            return httpx.Response(200, json={"token": "t0"})
        if request.method == "GET" and request.url.path.endswith("/adapters"):
            return httpx.Response(200, json={"items": [{"id": "sim", "type": "simulation"}]})
        return httpx.Response(200, json={})

    import httpx

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://edge")
    tag = EdgeTagInput(
        node_id="%ID103",
        display_name="Speed",
        mqtt_topic="Acme/S7/Speed",
        data_type="Integer",
    )
    apply_catalog_adapters_live([_s7(tags=(tag,))], client=client, username="admin", password="hivemq")

    paths = [(m, p) for m, p, _ in calls]
    assert ("POST", "/api/v1/auth/authenticate") in paths
    assert ("POST", "/api/v1/management/protocol-adapters/adapters/s7") in paths
    assert ("PUT", "/api/v1/management/protocol-adapters/adapters/catalog-srv_1/tags") in paths
    assert (
        "PUT",
        "/api/v1/management/protocol-adapters/adapters/catalog-srv_1/northboundMappings",
    ) in paths
    assert not any(p.endswith("/southboundMappings") for _, p in paths)
    assert not any("sim" in p and m == "DELETE" for m, p in paths)


def test_apply_deletes_removed_catalog_adapter_only():
    def handler(request):
        if request.url.path.endswith("/auth/authenticate"):
            return httpx.Response(200, json={"token": "t0"})
        if request.method == "GET" and request.url.path.endswith("/adapters"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "sim", "type": "simulation"},
                        {"id": "catalog-gone", "type": "s7"},
                    ]
                },
            )
        return httpx.Response(200, json={})

    import httpx

    seen_deletes: list[str] = []

    def tracking(request):
        response = handler(request)
        if request.method == "DELETE":
            seen_deletes.append(request.url.path)
        return response

    client = httpx.Client(transport=httpx.MockTransport(tracking), base_url="http://edge")
    apply_catalog_adapters_live([], client=client, username="admin", password="hivemq")
    assert seen_deletes == [
        "/api/v1/management/protocol-adapters/adapters/catalog-gone"
    ]


def test_apply_connection_error_is_edge_apply_error():
    import httpx

    def handler(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://edge")
    with pytest.raises(EdgeApplyError):
        apply_catalog_adapters_live([_s7()], client=client, username="admin", password="hivemq")


def test_apply_http_error_is_edge_apply_error():
    import httpx

    def handler(request):
        if request.url.path.endswith("/auth/authenticate"):
            return httpx.Response(200, json={"token": "t0"})
        return httpx.Response(500, json={"title": "boom"})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://edge")
    with pytest.raises(EdgeApplyError):
        apply_catalog_adapters_live([_s7()], client=client, username="admin", password="hivemq")
```

Put `import httpx` and `import pytest` at the top of the file (the snippets above inline them only to show the transport). Fix the first test so `httpx` is imported before `handler` uses `httpx.Response`.

Also assert create JSON includes `controllerType` `S7_300` and tag definition `tagAddress` / `DINT`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_api.py -v`

Expected: FAIL — `hivemq_edge_api` not found.

- [ ] **Step 3: Implement the client and settings**

`conf/settings.yaml` under `default:` (next to `mqtt:`):

```yaml
  hivemq_edge:
    base_url: "http://127.0.0.1:18080"
    username: admin
    password: hivemq
```

`docker-compose.yml` `graphql_server.environment` add:

```yaml
      UNS_hivemq_edge__base_url: "http://uns_mqtt_broker:8080"
```

`hivemq_edge_api.py` (complete module):

```python
"""Push catalog-owned adapters to a running HiveMQ Edge via the Management API."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from uns_config.hivemq_edge_xml import (
    EdgeAdapterInput,
    adapter_id_for,
    edge_data_type,
    _unique_tag_names,
)
from uns_config.loader import get_settings

LOGGER = logging.getLogger(__name__)

_TIMEOUT = 10.0
_AUTH = "/api/v1/auth/authenticate"
_ADAPTERS = "/api/v1/management/protocol-adapters/adapters"


class EdgeApplyError(Exception):
    """HiveMQ Edge did not accept the catalog adapters."""


def _protocol_id(protocol: str) -> str:
    # Task 2b adds `opc_ua` → `opcua`. Do not `else: return "s7"` — that would
    # POST an OPC UA adapter as type `s7`.
    if protocol == "ethernet_ip":
        return "eip"
    if protocol == "s7":
        return "s7"
    raise ValueError(f"unsupported Edge protocol: {protocol}")


def _adapter_body(adapter: EdgeAdapterInput) -> dict[str, Any]:
    protocol_id = _protocol_id(adapter.protocol)
    config: dict[str, Any] = {"host": adapter.host, "port": adapter.port}
    if protocol_id == "s7":
        config["controllerType"] = adapter.controller_type
    return {"id": adapter_id_for(adapter.server_id), "type": protocol_id, "config": config}


def _tag_items(adapter: EdgeAdapterInput) -> list[dict[str, Any]]:
    protocol_id = _protocol_id(adapter.protocol)
    addr_key = "tagAddress" if protocol_id == "s7" else "address"
    names = _unique_tag_names(adapter.tags)
    items = []
    for tag, name in zip(adapter.tags, names, strict=True):
        items.append(
            {
                "name": name,
                "description": tag.display_name or tag.node_id,
                "definition": {
                    addr_key: tag.node_id,
                    "dataType": edge_data_type(tag.data_type),
                },
            }
        )
    return items


def _mapping_items(adapter: EdgeAdapterInput) -> list[dict[str, Any]]:
    names = _unique_tag_names(adapter.tags)
    return [
        {
            "topic": tag.mqtt_topic,
            "tagName": name,
            "maxQoS": "AT_LEAST_ONCE",
            "includeTimestamp": True,
        }
        for tag, name in zip(adapter.tags, names, strict=True)
    ]


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> httpx.Response:
    try:
        response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise EdgeApplyError(str(exc)) from exc
    if response.status_code >= 400:
        raise EdgeApplyError(f"{method} {path} -> {response.status_code}")
    return response


def apply_catalog_adapters_live(
    adapters: list[EdgeAdapterInput],
    *,
    client: httpx.Client | None = None,
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout: float = _TIMEOUT,
) -> None:
    settings = get_settings()
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            base_url=(base_url or str(settings.get("hivemq_edge.base_url", "http://127.0.0.1:18080"))),
            timeout=timeout,
        )
    try:
        user = username or str(settings.get("hivemq_edge.username", "admin"))
        secret = password or str(settings.get("hivemq_edge.password", "hivemq"))
        token = _request(
            client, "POST", _AUTH, json={"userName": user, "password": secret}
        ).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        listed = _request(client, "GET", _ADAPTERS).json().get("items") or []
        wanted = {adapter_id_for(adapter.server_id): adapter for adapter in adapters}
        existing_ids = {item.get("id") for item in listed if isinstance(item, dict)}
        for item in listed:
            adapter_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(adapter_id, str) and adapter_id.startswith("catalog-") and adapter_id not in wanted:
                _request(client, "DELETE", f"{_ADAPTERS}/{adapter_id}")
        for adapter_id, adapter in wanted.items():
            body = _adapter_body(adapter)
            if adapter_id in existing_ids:
                _request(client, "PUT", f"{_ADAPTERS}/{adapter_id}", json=body)
            else:
                _request(client, "POST", f"{_ADAPTERS}/{body['type']}", json=body)
            _request(client, "PUT", f"{_ADAPTERS}/{adapter_id}/tags", json={"items": _tag_items(adapter)})
            _request(
                client,
                "PUT",
                f"{_ADAPTERS}/{adapter_id}/northboundMappings",
                json={"items": _mapping_items(adapter)},
            )
    finally:
        if owns_client:
            client.close()
```

If a test needs `get_settings` and has no conf, tests that pass `client` / `username` / `password` must not require settings for URL. When `client` is provided, skip `get_settings` for `base_url` (still may call it for user/pass if omitted). Adjust so MockTransport tests never open a real socket: if `client` is passed, do not construct another client and do not call `get_settings` unless username/password are omitted. **Tests pass username and password**, so when `client` is not None, do not call `get_settings` at all.

Rewrite the top of `apply_catalog_adapters_live` accordingly:

```python
    owns_client = client is None
    if owns_client:
        settings = get_settings()
        client = httpx.Client(
            base_url=base_url or str(settings.get("hivemq_edge.base_url", "http://127.0.0.1:18080")),
            timeout=timeout,
        )
        user = username or str(settings.get("hivemq_edge.username", "admin"))
        secret = password or str(settings.get("hivemq_edge.password", "hivemq"))
    else:
        user = username or "admin"
        secret = password or "hivemq"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_api.py ./00_uns_config/test/test_hivemq_edge_xml.py ./00_uns_config/test/test_compose_env.py -q --tb=line`

Expected: PASS. PUT of an already-listed `catalog-*` id must update, not create a second adapter — add that case in Step 1 if the create-only test is the only happy path (PUT when GET already returned `catalog-srv_1`).

- [ ] **Step 5: Commit**

```bash
git add 00_uns_config/pyproject.toml 00_uns_config/src/uns_config/hivemq_edge_api.py 00_uns_config/test/test_hivemq_edge_api.py conf/settings.yaml docker-compose.yml uv.lock
git commit -m "feat(config): push catalog adapters to HiveMQ Edge over HTTP."
```

---

### Task 2b: Catalog OPC UA adapters in XML, rows, and the Edge HTTP client

**Files:**
- Modify: `09_uns_model/src/uns_model/tables.py` (`EDGE_PROTOCOLS`)
- Modify: `09_uns_model/src/uns_model/connectivity.py` (`edge_adapters_from_rows`, pending/XML gates, `replace_subscribed_tags`)
- Modify: `09_uns_model/test/test_connectivity.py`
- Modify: `00_uns_config/src/uns_config/hivemq_edge_xml.py` (`EdgeAdapterInput.uri`, `render_catalog_adapter`)
- Modify: `00_uns_config/src/uns_config/hivemq_edge_api.py` (`_protocol_id`, `_adapter_body`, `_tag_items`)
- Modify: `00_uns_config/test/test_hivemq_edge_xml.py`
- Modify: `00_uns_config/test/test_hivemq_edge_api.py`

**Interfaces:**
- Consumes: catalog `protocol="opc_ua"`, `endpoint` as `opc.tcp://…`, subscribed `node_id` as OPC UA NodeId
- Produces: `EDGE_PROTOCOLS = frozenset({"s7", "ethernet_ip", "opc_ua"})`; `EdgeAdapterInput.uri: str = ""`; XML `<protocolId>opcua</protocolId>` + `<uri>`; HTTP type `opcua` + `config.uri`; tag definition `node` (not `tagAddress`)
- Keep `PLC_PROTOCOLS` as S7/EIP only. TCP `parse_host_port` and S7/EIP Test stay on `PLC_PROTOCOLS`. XML pending, `after_flush` pending, and `edge_adapters_from_rows` use `EDGE_PROTOCOLS`.

Match `conf/hivemq/fixtures/adapters-unroutable.xml` (the `fixture-opcua` block): config is `<uri>` only; tag definition is `<node>`; northbound is the same `topic` / `tagName` / `maxQos` / `includeTimestamp` as S7. Do not emit `<southboundMappings>` from the catalog renderer (the fixture’s southbound is a non-catalog adapter; catalog splice still must not add southbound).

- [ ] **Step 1: Write the failing tests**

In `09_uns_model/test/test_connectivity.py` next to the existing PLC_PROTOCOLS assertion:

```python
def test_edge_protocols_include_opc_ua():
    assert EDGE_PROTOCOLS == frozenset({"s7", "ethernet_ip", "opc_ua"})
    assert PLC_PROTOCOLS == frozenset({"s7", "ethernet_ip"})
```

Rename `test_edge_adapters_from_rows_maps_s7_and_skips_opc_ua` to `test_edge_adapters_from_rows_maps_s7_and_opc_ua`. Keep the S7 assertion. Change the OPC UA row to include one subscribed tag and assert a second adapter:

```python
opc = SimpleNamespace(
    id="srv_opc",
    protocol="opc_ua",
    endpoint="opc.tcp://h:4840",
    protocol_config=None,
    tags=[
        SimpleNamespace(
            node_id="ns=1;i=1004",
            display_name="Temp",
            mqtt_topic="Server/OpcPlc/Temp",
            data_type="Double",
            subscribed=True,
        )
    ],
)
adapters = edge_adapters_from_rows([s7, opc])
assert len(adapters) == 2
assert adapters[1] == EdgeAdapterInput(
    server_id="srv_opc",
    protocol="opc_ua",
    host="",
    port=0,
    uri="opc.tcp://h:4840",
    tags=(EdgeTagInput("ns=1;i=1004", "Temp", "Server/OpcPlc/Temp", "Double"),),
)
```

If `EdgeAdapterInput` equality fails until `uri` exists, that is the intended red.

Add a test that `replace_subscribed_tags` calls `after_flush` when passed (mirror `save_tag` / `_sync_edge`). Reuse the file’s existing session/repository fixtures. If the current `replace_subscribed_tags` tests have no `after_flush`, add:

```python
@pytest.mark.asyncio
async def test_replace_subscribed_tags_calls_after_flush(repository, session):
    server = await _insert_opc_ua_server(session)  # reuse whatever OPC UA insert helper exists
    flushed = []

    def _flush(adapters):
        flushed.append(adapters)

    await repository.replace_subscribed_tags(
        server.id,
        [ConnectivityTagSpec(node_id="ns=1;i=1", browse_path="Server/A", display_name="A", mqtt_topic="Server/A")],
        after_flush=_flush,
    )
    assert flushed
```

Use the same insert helper the file already uses for OPC UA servers. If none exists, copy the S7 insert and set `protocol="opc_ua"`, `endpoint="opc.tcp://h:4840"`.

In `00_uns_config/test/test_hivemq_edge_xml.py` add next to `test_render_s7_structural_indent`:

```python
def _opcua(**overrides) -> EdgeAdapterInput:
    tags = overrides.pop("tags", (
        EdgeTagInput("ns=1;i=1004", "Temp", "Server/OpcPlc/Temp", "Double"),
    ))
    return EdgeAdapterInput(
        server_id=overrides.pop("server_id", "fixture-opc"),
        protocol="opc_ua",
        host="",
        port=0,
        uri=overrides.pop("uri", "opc.tcp://192.0.2.1:4840"),
        tags=tags,
    )


def test_render_opcua_uri_and_node():
    rendered = render_catalog_adapter(_opcua())
    assert "<protocolId>opcua</protocolId>" in rendered
    assert "<uri>opc.tcp://192.0.2.1:4840</uri>" in rendered
    assert "<host>" not in rendered
    assert "<tagAddress>" not in rendered
    assert "<node>ns=1;i=1004</node>" in rendered
    assert "<topic>Server/OpcPlc/Temp</topic>" in rendered
    assert "southbound" not in rendered.lower()
```

Also assert `apply_catalog_adapters(_CONFIG, [_opcua()])` still keeps the `sim` adapter bytes (reuse `_simulation_adapter_block`).

In `00_uns_config/test/test_hivemq_edge_api.py` copy `test_apply_creates_adapter_tags_and_mappings` for OPC UA: POST path must end with `/adapters/opcua`; body `config` is `{"uri": "opc.tcp://192.0.2.1:4840"}` with no `host`; tag `definition` is `{"node": "ns=1;i=1004"}` (include `dataType` only if S7 tests include it — match S7’s shape but the address key is `node`). Simulation id `sim` must not be DELETE’d.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./09_uns_model/test/test_connectivity.py::test_edge_protocols_include_opc_ua ./09_uns_model/test/test_connectivity.py::test_edge_adapters_from_rows_maps_s7_and_opc_ua ./00_uns_config/test/test_hivemq_edge_xml.py::test_render_opcua_uri_and_node ./00_uns_config/test/test_hivemq_edge_api.py -k opcua -v`

Expected: FAIL — `EDGE_PROTOCOLS` / `uri` / opcua render missing; `_protocol_id("opc_ua")` raises.

- [ ] **Step 3: Implement**

`tables.py` next to `PLC_PROTOCOLS`:

```python
EDGE_PROTOCOLS: frozenset[str] = frozenset({"s7", "ethernet_ip", "opc_ua"})
```

Re-export `EDGE_PROTOCOLS` from `connectivity.py` the same way as `PLC_PROTOCOLS`.

`EdgeAdapterInput`: add `uri: str = ""` after `port` (default keeps every existing S7/EIP constructor valid).

`render_catalog_adapter`: map `opc_ua` → `opcua`. When `protocol == "opc_ua"`, config children are only `<uri>{adapter.uri}</uri>`. Tag definition element is `node` (value `tag.node_id`). S7/EIP branches stay as they are. Still no southbound.

`edge_adapters_from_rows`: iterate `EDGE_PROTOCOLS`. For `opc_ua`, do **not** call `parse_host_port`; set `host=""`, `port=0`, `uri=server.endpoint`. Unsubscribed tags still omitted. Rewrite the function docstring: it currently says OPC UA is not a HiveMQ Edge protocol adapter — that is no longer true.

Pending / XML: every `spec.protocol in PLC_PROTOCOLS` / `protocol in PLC_PROTOCOLS` that gates **Edge apply pending** or **catalog XML** becomes `EDGE_PROTOCOLS`. That includes `save_server` pending values and `_mark_pending_if_plc` (rename to `_mark_pending_if_edge` if the name would otherwise lie). Leave `ConnectivityServerSpec.validate` TCP `parse_host_port` on `PLC_PROTOCOLS` only.

`replace_subscribed_tags`: add `after_flush` with the same type as `save_tag`. After the upserts, if `after_flush is not None`, call `_mark_pending_if_edge` and `_sync_edge` before returning. GraphQL Subscribe has no XML today; this is the seam Task 3 will pass `_sync_edge` into.

`hivemq_edge_api.py`:

```python
def _protocol_id(protocol: str) -> str:
    if protocol == "ethernet_ip":
        return "eip"
    if protocol == "opc_ua":
        return "opcua"
    if protocol == "s7":
        return "s7"
    raise ValueError(f"unsupported Edge protocol: {protocol}")


def _adapter_body(adapter: EdgeAdapterInput) -> dict[str, Any]:
    protocol_id = _protocol_id(adapter.protocol)
    if protocol_id == "opcua":
        config: dict[str, Any] = {"uri": adapter.uri}
    else:
        config = {"host": adapter.host, "port": adapter.port}
        if protocol_id == "s7":
            config["controllerType"] = adapter.controller_type
    return {"id": adapter_id_for(adapter.server_id), "type": protocol_id, "config": config}
```

`_tag_items`: `addr_key` is `tagAddress` for s7, `address` for eip, `node` for opcua.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./09_uns_model/test/test_connectivity.py ./00_uns_config/test/test_hivemq_edge_xml.py ./00_uns_config/test/test_hivemq_edge_api.py -q --tb=line`

Expected: PASS. Delete or update any remaining `skips_opc_ua` test name.

- [ ] **Step 5: Commit**

```bash
git add 09_uns_model/src/uns_model/tables.py 09_uns_model/src/uns_model/connectivity.py 09_uns_model/test/test_connectivity.py 00_uns_config/src/uns_config/hivemq_edge_xml.py 00_uns_config/src/uns_config/hivemq_edge_api.py 00_uns_config/test/test_hivemq_edge_xml.py 00_uns_config/test/test_hivemq_edge_api.py
git commit -m "feat(edge): catalog OPC UA adapters for HiveMQ Edge XML and HTTP."
```

---

### Task 3: GraphQL Save calls live apply after the row is stored

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/mutations/connectivity.py`
- Modify: `07_uns_graphql/test/mutations/test_connectivity.py`

**Interfaces:**
- Consumes: `_sync_edge` (XML, unchanged); `apply_catalog_adapters_live`; `EdgeApplyError`; `edge_adapters_from_rows`; `EDGE_PROTOCOLS`; `record_live_apply`
- Produces: `_finish_live_apply(mutated_ids: list[str]) -> None` on S7, EIP, **and OPC UA** mutations (Save server, save/update/unsubscribe tag, update topic, delete server, `subscribeOpcUaVariables`)

- [ ] **Step 1: Write the failing tests**

In `07_uns_graphql/test/mutations/test_connectivity.py`:

1. Change every expected `Recreate uns_mqtt_broker to apply Edge config` / comment about recreate to `Waiting for HiveMQ Edge to apply`. `test_test_connectivity_server_tcp_success_keeps_pending_error` still asserts `record_test(..., error=EDGE_APPLY_ERROR)` — that keeps working once Task 1 changed the constant.

2. Add (next to `test_save_connectivity_server_s7_calls_after_flush`):

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_save_s7_live_apply_success_records_untested(monkeypatch, tmp_path):
    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
    repository = AsyncMock()
    saved = _server(server_id="srv-s7", protocol="s7", endpoint="10.0.0.5:102")
    saved.last_status = "pending"

    async def _save_server(spec, *, after_flush=None):
        after_flush(
            [
                EdgeAdapterInput(
                    server_id=spec.id,
                    protocol="s7",
                    host="10.0.0.5",
                    port=102,
                    controller_type="S7_1500",
                    tags=(),
                )
            ]
        )
        return saved

    repository.save_server.side_effect = _save_server
    repository.list_servers.return_value = [saved]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation {
              saveConnectivityServer(server: {
                id: "srv-s7", name: "s7", protocol: S7,
                endpoint: "10.0.0.5:102"
              }) { id lastStatus }
            }
            """,
            context_value=ADMIN,
        )

    assert result.errors is None
    live.assert_called_once()
    repository.record_live_apply.assert_awaited()
    kwargs = repository.record_live_apply.await_args
    assert kwargs.kwargs["ok"] is True


@pytest.mark.asyncio(loop_scope="function")
async def test_save_s7_live_apply_failure_keeps_save(monkeypatch, tmp_path):
    from uns_config.hivemq_edge_api import EdgeApplyError

    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "uns_graphql.mutations.connectivity.apply_catalog_adapters_live",
        Mock(side_effect=EdgeApplyError("down")),
    )
    repository = AsyncMock()
    saved = _server(server_id="srv-s7", protocol="s7", endpoint="10.0.0.5:102")

    async def _save_server(spec, *, after_flush=None):
        after_flush([])
        return saved

    repository.save_server.side_effect = _save_server
    repository.list_servers.return_value = [saved]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation {
              saveConnectivityServer(server: {
                id: "srv-s7", name: "s7", protocol: S7,
                endpoint: "10.0.0.5:102"
              }) { id }
            }
            """,
            context_value=ADMIN,
        )

    assert result.errors is None
    assert result.data["saveConnectivityServer"]["id"] == "srv-s7"
    repository.record_live_apply.assert_awaited()
    assert repository.record_live_apply.await_args.kwargs["ok"] is False


@pytest.mark.asyncio(loop_scope="function")
async def test_save_opc_ua_live_apply_success_records_untested(monkeypatch, tmp_path):
    config_path = tmp_path / "hivemq" / "config.xml"
    config_path.parent.mkdir()
    config_path.write_text(_HIVEMQ_XML, encoding="utf-8")
    monkeypatch.setattr("uns_graphql.mutations.connectivity.resolve_conf_dir", lambda: tmp_path)
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
    repository = AsyncMock()
    saved = _server(server_id="srv-opc", protocol="opc_ua", endpoint="opc.tcp://h:4840")
    saved.last_status = "pending"

    async def _save_server(spec, *, after_flush=None):
        after_flush(
            [
                EdgeAdapterInput(
                    server_id=spec.id,
                    protocol="opc_ua",
                    host="",
                    port=0,
                    uri=spec.endpoint,
                    tags=(),
                )
            ]
        )
        return saved

    repository.save_server.side_effect = _save_server
    repository.list_servers.return_value = [saved]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation {
              saveConnectivityServer(server: {
                id: "srv-opc", name: "opc", protocol: OPC_UA,
                endpoint: "opc.tcp://h:4840"
              }) { id lastStatus }
            }
            """,
            context_value=ADMIN,
        )

    assert result.errors is None
    live.assert_called_once()
    repository.record_live_apply.assert_awaited()
    assert repository.record_live_apply.await_args.kwargs["ok"] is True
```

Adapt field names on `ConnectivityServerInput` to whatever `test_save_connectivity_server_s7_calls_after_flush` already sends (copy that mutation document). If `_server` needs extra kwargs, copy from that test.

Add a second OPC UA test next to `test_subscribe_opc_ua_variables_discovers_and_folds_into_catalog`: after subscribe, `apply_catalog_adapters_live` is called and `replace_subscribed_tags` was invoked with `after_flush`. Keep the existing discover/fold assertions.

**Delete** `test_save_opc_ua_does_not_call_live_apply` if it exists in the file from an older draft — do not leave a skip-OPC-UA assertion.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./07_uns_graphql/test/mutations/test_connectivity.py::test_save_s7_live_apply_success_records_untested ./07_uns_graphql/test/mutations/test_connectivity.py::test_save_s7_live_apply_failure_keeps_save ./07_uns_graphql/test/mutations/test_connectivity.py::test_save_opc_ua_live_apply_success_records_untested -v`

Expected: FAIL — `_finish_live_apply` / `record_live_apply` not wired.

- [ ] **Step 3: Implement**

In `mutations/connectivity.py`:

```python
from uns_config.hivemq_edge_api import EdgeApplyError, apply_catalog_adapters_live
from uns_model.connectivity import (
    EDGE_APPLY_ERROR,
    EDGE_PROTOCOLS,
    ConnectivityRepository,
    ConnectivityServerSpec,
    ConnectivityTagSpec,
    edge_adapters_from_rows,
    parse_host_port,
)
```

Keep `_sync_edge` as XML only.

```python
async def _finish_live_apply(mutated_ids: list[str]) -> None:
    """Push catalog adapters to the running broker. Never raises into the mutation."""
    repo = _repository()
    adapters = edge_adapters_from_rows(await repo.list_servers())
    try:
        apply_catalog_adapters_live(adapters)
    except EdgeApplyError:
        LOGGER.warning("HiveMQ Edge live apply failed", exc_info=True)
        await repo.record_live_apply(mutated_ids, ok=False)
        return
    edge_ids = [adapter.server_id for adapter in adapters] or mutated_ids
    await repo.record_live_apply(edge_ids, ok=True)
```

After each Edge-protocol write, call it:

- `save_connectivity_server`: after `save_server`, if `saved.protocol in EDGE_PROTOCOLS`: `await _finish_live_apply([saved.id])`. Return `from_server` of a re-fetched server if you need fresh `lastStatus` (call `list_servers` / `_find_server` after apply). The mutation return should reflect `untested` or `pending` after apply — re-fetch `saved = await _find_server(repo, saved.id)` after `_finish_live_apply`.
- `delete_connectivity_server`: look up the server **before** delete. If it is in `EDGE_PROTOCOLS` and `deleted`, `await _finish_live_apply([])` (empty mutated ids; leftover catalog adapters are deleted by the client). Do not fail the mutation if apply fails.
- `save_connectivity_tag`, `update_connectivity_tag`, `update_connectivity_tag_topic`, `unsubscribe_connectivity_tag`: after the repository call, if the server protocol is in `EDGE_PROTOCOLS`, `await _finish_live_apply([server_id])`. Load protocol with `_find_server` **before** unsubscribe/update if the tag path does not return the server.
- `subscribe_opc_ua_variables`: pass `after_flush=_sync_edge` into `replace_subscribed_tags` (Task 2b added the argument). Then `await _finish_live_apply([server_id])`. Browse (`open_client` / `discover_variables`) stays as it is — do not call Edge for browse.

Do **not** gate Subscribe on ISA-95. Browse-path `mqttTopic` is valid. TopicBinder may mark Unmodelled elsewhere; this mutation must not reject it.

Update the `test_connectivity_server` comment: keep `EDGE_APPLY_ERROR` on pending TCP/session success because live apply has not succeeded, not because of recreate. OPC UA Test remains the existing session probe; it does not call `_finish_live_apply`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./07_uns_graphql/test/mutations/test_connectivity.py ./07_uns_graphql/test/type/test_connectivity.py ./07_uns_graphql/test/auth/test_require.py -q --tb=line`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/mutations/connectivity.py 07_uns_graphql/test/mutations/test_connectivity.py
git commit -m "feat(graphql): apply S7, EIP, and OPC UA catalog rows to live HiveMQ Edge."
```

---

### Task 4: Console copy and docs

**Files:**
- Modify: `11_frontend/src/components/connectivity/ConnectivityView.test.tsx`
- Modify: `11_frontend/src/components/connectivity/ConnectivityView.tsx` only if it hardcodes the recreate sentence (today it renders `lastError` from GraphQL — then tests-only)
- Modify: `conf/hivemq/README.md`
- Modify: `docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md` (one line under Related)

**Interfaces:**
- Consumes: `EDGE_APPLY_ERROR` sentence from the API as `lastError`
- Produces: UI and README that no longer tell the engineer to recreate on Save

- [ ] **Step 1: Write the failing frontend test**

Replace every `'Recreate uns_mqtt_broker to apply Edge config'` in `ConnectivityView.test.tsx` with `'Waiting for HiveMQ Edge to apply'`.

The existing test `does not auto-test a newly added S7 server, leaving it pending` must still assert the pending sentence is visible.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/connectivity/ConnectivityView.test.tsx` from `11_frontend`

Expected: FAIL if the mock still uses the old sentence in `S7_SERVER` — you change mocks and assertions together in Step 1, so this step fails only if production UI still special-cases the old string. If the UI only renders `lastError`, Step 1+3 are the same copy swap and Step 2 may already pass after Step 1. That is acceptable.

- [ ] **Step 3: Docs**

`conf/hivemq/README.md` replace the recreate-first S7/EIP paragraph with the following (indent the shell lines; do not nest fenced blocks in the README):

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

At the top of `docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md`, immediately after the Related list, add (skip this edit if that pointer is already present):

```markdown
Apply path: superseded by
[2026-09-07-connectivity-edge-live-apply-design.md](./2026-09-07-connectivity-edge-live-apply-design.md)
and OPC UA on Edge by
[2026-09-08-uns-edge-opcua-datalake-design.md](./2026-09-08-uns-edge-opcua-datalake-design.md).
Catalog, XML generator, and TCP Test in this document still apply.
```

- [ ] **Step 4: Run frontend connectivity tests**

Run: `npx vitest run src/components/connectivity src/lib/connectivity` from `11_frontend`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 11_frontend/src/components/connectivity/ConnectivityView.test.tsx 11_frontend/src/components/connectivity/ConnectivityView.tsx conf/hivemq/README.md docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md
git commit -m "docs(hivemq): Save applies Edge adapters; recreate is ops-only."
```

**Manual check (not a pytest gate):** with the stack up, add one S7 or EIP signal **and** one subscribed OPC UA node, do **not** recreate `uns_mqtt_broker`, subscribe to those MQTT topics. If the PLC/sim/OPC server is reachable from the broker container, a value arrives. Confirm `opcua_client` is not running unless you passed `--profile legacy-opcua`.

---

### Task 5: Remap `mqttTopic` rewrites historian in the same failure domain

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/backend/historian.py` (`rewrite_topic_prefix` optional connection)
- Modify: `07_uns_graphql/test/backend/test_historian_rewrite.py`
- Modify: `09_uns_model/src/uns_model/connectivity.py` (`update_tag` / `update_tag_topic` rewrite hook)
- Modify: `09_uns_model/test/test_connectivity.py`
- Modify: `07_uns_graphql/src/uns_graphql/mutations/connectivity.py`
- Modify: `07_uns_graphql/test/mutations/test_connectivity.py`

**Interfaces:**
- Consumes: existing `HistorianRepository.rewrite_topic_prefix(old_prefix, new_prefix) -> int`; `update_tag_topic`
- Produces: `rewrite_topic_prefix(..., connection: AsyncConnection | None = None)`; `update_tag(..., on_topic_rewrite: Callable[[AsyncSession, str, str], Awaitable[None]] | None = None)` invoked **inside** the catalog session **before** `after_flush`. If the callback raises, the catalog topic change rolls back (same spirit as XML `after_flush`). Live apply still runs **after** commit and never rolls back the topic.

`09_uns_model` must **not** import `uns_graphql`. GraphQL supplies the callback.

- [ ] **Step 1: Write the failing tests**

Historian: extend an existing rewrite test (or add one next to it) that passes an already-open connection from `database.begin()` and still rewrites. A second test: `connection` omitted still opens its own transaction (current behaviour).

Model: in `test_connectivity.py`, `update_tag_topic` with `on_topic_rewrite` that raises must leave `mqtt_topic` unchanged. A success callback must see `(old_topic, new_topic)` and then `after_flush` still runs. Reuse the file’s repository/session fixtures.

GraphQL: next to the live-apply tests:

```python
@pytest.mark.asyncio(loop_scope="function")
async def test_update_tag_topic_rewrites_historian_then_live_applies(monkeypatch, tmp_path):
    # XML fixture same as Task 3 S7 tests
    rewrite = AsyncMock()
    monkeypatch.setattr(
        "uns_graphql.mutations.connectivity.HistorianRepository.rewrite_topic_prefix",
        rewrite,
    )
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
    repository = AsyncMock()
    tag = _tag(mqtt_topic="Server/OpcPlc/Temp")  # copy the helper this file already uses
    # update_tag_topic must be invoked with on_topic_rewrite; the mock should call it
    # if the mutation passes it through. Prefer asserting the mutation wired the hook:
    captured = {}

    async def _update(server_id, node_id, mqtt_topic, **kwargs):
        captured["rewrite"] = kwargs.get("on_topic_rewrite")
        after = kwargs.get("after_flush")
        if after:
            after([])
        if captured["rewrite"]:
            await captured["rewrite"](None, "Server/OpcPlc/Temp", mqtt_topic)
        tag.mqtt_topic = mqtt_topic
        return tag

    repository.update_tag_topic.side_effect = _update
    repository.list_servers.return_value = [_server(server_id="srv-opc", protocol="opc_ua", endpoint="opc.tcp://h:4840")]

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation {
              updateConnectivityTagTopic(serverId: "srv-opc", nodeId: "ns=1;i=1", mqttTopic: "Acme/Line/Temp") {
                mqttTopic
              }
            }
            """,
            context_value=ADMIN,
        )

    assert result.errors is None
    assert captured["rewrite"] is not None
    live.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_update_tag_topic_rewrite_failure_skips_live_apply(monkeypatch):
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
    repository = AsyncMock()

    async def _update(server_id, node_id, mqtt_topic, **kwargs):
        hook = kwargs.get("on_topic_rewrite")
        if hook:
            await hook(None, "old/topic", mqtt_topic)
        return _tag(mqtt_topic=mqtt_topic)

    repository.update_tag_topic.side_effect = _update
    monkeypatch.setattr(
        "uns_graphql.mutations.connectivity.HistorianRepository.rewrite_topic_prefix",
        AsyncMock(side_effect=RuntimeError("timescale down")),
    )

    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation {
              updateConnectivityTagTopic(serverId: "srv-opc", nodeId: "ns=1;i=1", mqttTopic: "Acme/Line/Temp") {
                mqttTopic
              }
            }
            """,
            context_value=ADMIN,
        )

    assert result.errors
    live.assert_not_called()
```

Adapt GraphQL field names and `_tag` / `_server` helpers to this file. Duplicate-topic rejection stays unchanged and must run **before** rewrite.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./07_uns_graphql/test/mutations/test_connectivity.py -k update_tag_topic ./09_uns_model/test/test_connectivity.py -k topic_rewrite ./07_uns_graphql/test/backend/test_historian_rewrite.py -q --tb=line`

Expected: FAIL — `on_topic_rewrite` / optional `connection` missing.

- [ ] **Step 3: Implement**

`rewrite_topic_prefix`: if `connection` is not None, run the existing UPDATE SQL on that connection and return. If None, keep `async with self._database.begin()`. Do not open a nested transaction when a connection is passed.

`update_tag`: before applying `mqtt_topic`, load the current topic. After the UPDATE, if `mqtt_topic` is in `fields` and differs from the old value and `on_topic_rewrite` is not None, `await on_topic_rewrite(session, old_topic, new_topic)`. Then `after_flush` as today. If the hook raises, do not catch it — the session rolls back.

`update_tag_topic`: pass `on_topic_rewrite` through.

GraphQL `update_connectivity_tag_topic`:

```python
async def _rewrite_topics(session, old_topic: str, new_topic: str) -> None:
    # Prefer passing the same DB connection as the catalog session when the
    # engine is shared (Database.shared("graphql")). If session.connection()
    # is awkward on this SQLAlchemy version, call rewrite_topic_prefix without
    # connection *only if* tests prove the catalog row is still uncommitted
    # and a failure still rolls back. The required product behaviour: rewrite
    # failure ⇒ catalog mqtt_topic unchanged.
    await HistorianRepository(Database.shared("graphql")).rewrite_topic_prefix(
        old_topic, new_topic
    )
```

Wire `_rewrite_topics` as `on_topic_rewrite`. After a successful `update_tag_topic`, `await _finish_live_apply([server_id])` (Task 3). If `update_tag_topic` raises, do not call live apply.

If a same-connection API is needed: `rewrite_topic_prefix(..., connection=await session.connection())` inside the hook. Match how `hierarchy.py` already calls `rewrite_topic_prefix` so hierarchy remap and tag remap share one method.

Same topic (`old == new`): repository must not call rewrite (`rewrite_topic_prefix` already raises `ValueError` on equal prefixes). Skip the hook when unchanged.

Edge down after a successful rewrite: Task 3 already sets `pending`. Catalog and historian stay on the new topic.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./07_uns_graphql/test/mutations/test_connectivity.py ./07_uns_graphql/test/backend/test_historian_rewrite.py ./09_uns_model/test/test_connectivity.py ./07_uns_graphql/test/mutations/test_hierarchy.py -q --tb=line`

Expected: PASS. Hierarchy rewrite tests must still pass.

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/backend/historian.py 07_uns_graphql/test/backend/test_historian_rewrite.py 09_uns_model/src/uns_model/connectivity.py 09_uns_model/test/test_connectivity.py 07_uns_graphql/src/uns_graphql/mutations/connectivity.py 07_uns_graphql/test/mutations/test_connectivity.py
git commit -m "feat(connectivity): rewrite historian when remapping a catalog mqttTopic."
```

---

### Task 6: Park `opcua_client` behind Compose profile `legacy-opcua`

**Files:**
- Modify: `docker-compose.yml` (`opcua_client` `profiles`, prometheus `depends_on`)
- Modify: `docker-compose.dev.yml` (prometheus `depends_on`; keep `opcua_client.extra_hosts` for when the profile is on)
- Modify: `00_uns_config/test/test_hivemq_edge_stack.py`
- Optional: `08_uns_observability/prometheus/prometheus.yml` — leave the `opcua_client:9093` scrape job; a missing target is a down scrape, not a Compose dependency. Do not add `depends_on` back.

**Interfaces:**
- Produces: `opcua_client.profiles: [legacy-opcua]`. Default `uns_compose up` does not start it. Default `uns_prometheus` must **not** `depends_on` `opcua_client`.

- [ ] **Step 1: Write the failing tests**

In `00_uns_config/test/test_hivemq_edge_stack.py`:

Keep `test_opcua_client_is_a_compose_service` (the service still exists).

Replace `test_prometheus_compose_depends_on_opcua_client` with:

```python
def test_opcua_client_is_legacy_opcua_profile_only():
    service = _compose()["services"]["opcua_client"]
    assert service.get("profiles") == ["legacy-opcua"]


def test_prometheus_does_not_depend_on_opcua_client():
    assert "opcua_client" not in _compose()["services"]["uns_prometheus"]["depends_on"]
    dev_deps = _dev_compose()["services"]["uns_prometheus"]["depends_on"]
    if isinstance(dev_deps, dict):
        assert "opcua_client" not in dev_deps
    else:
        assert "opcua_client" not in dev_deps
```

Keep `test_prometheus_scrapes_opcua_client` unless removing the scrape job — default is keep scrape.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py::test_opcua_client_is_legacy_opcua_profile_only ./00_uns_config/test/test_hivemq_edge_stack.py::test_prometheus_does_not_depend_on_opcua_client -v`

Expected: FAIL — no `profiles`, prometheus still depends on `opcua_client`.

- [ ] **Step 3: Implement**

On `opcua_client` in `docker-compose.yml` add:

```yaml
    profiles: ["legacy-opcua"]
```

Remove `opcua_client` from `uns_prometheus.depends_on` in `docker-compose.yml` and from the `!reset` list in `docker-compose.dev.yml`.

Do not delete the `opcua_client` service, its Dockerfile, or `10_uns_opcua`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./00_uns_config/test/test_hivemq_edge_stack.py ./00_uns_config/test/test_compose_env.py -q --tb=line`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.dev.yml 00_uns_config/test/test_hivemq_edge_stack.py
git commit -m "chore(compose): park opcua_client behind the legacy-opcua profile."
```

---

### Task 7: Datalake object-store port (types and fake-store tests only)

**Files:**
- Create: `00_uns_config/src/uns_config/datalake.py`
- Create: `00_uns_config/test/test_datalake.py`

**Interfaces:**
- Produces: Historic Event record type; `historic_event_object_path`; `ObjectStore.put`; `S3ObjectStore` and `AdlsObjectStore` **signatures** (constructible, `put` not implemented against a cloud); fake filesystem tests lock layout and column names
- Does **not** produce a Compose sink, Kafka change, or pyarrow/s3/azure dependency. `kafka_mapper` topic shape stays one Kafka topic per MQTT topic. Module docstring must say a real sink later consumes envelope topic `uns.historic-events` (MQTT topic inside the value).

- [ ] **Step 1: Write the failing tests**

Create `00_uns_config/test/test_datalake.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

from uns_config.datalake import (
    HISTORIC_EVENT_COLUMNS,
    AdlsObjectStore,
    FakeObjectStore,
    HistoricEventRecord,
    S3ObjectStore,
    historic_event_object_path,
)


def test_object_path_is_date_partitioned_and_topic_safe():
    when = datetime(2026, 9, 8, 15, 4, tzinfo=UTC)
    path = historic_event_object_path(event_time=when, topic="Server/OpcPlc/Temp")
    assert path.startswith("dt=2026-09-08/")
    assert "Server/OpcPlc/Temp" not in path  # `/` must not create extra directories beyond dt=
    assert "Server" in path and "Temp" in path


def test_columns_are_historic_event_time_topic_payload():
    assert HISTORIC_EVENT_COLUMNS == ("time", "topic", "payload")


def test_fake_store_writes_under_dt_prefix(tmp_path: Path):
    store = FakeObjectStore(tmp_path)
    record = HistoricEventRecord(
        time=datetime(2026, 9, 8, tzinfo=UTC),
        topic="Acme/Line/Temp",
        payload={"value": 1.2},
    )
    path = historic_event_object_path(event_time=record.time, topic=record.topic)
    store.put(path, b"PARQUET")
    written = tmp_path / path
    assert written.is_file()
    assert written.read_bytes() == b"PARQUET"


def test_s3_and_adls_signatures_do_not_call_the_network():
    s3 = S3ObjectStore(bucket="lake", region="eu-central-1")
    adls = AdlsObjectStore(account="acct", container="lake")
    for store in (s3, adls):
        try:
            store.put("dt=2026-09-08/x.parquet", b"x")
        except NotImplementedError:
            pass
        else:
            raise AssertionError("cloud adapters must not put in this slice")
```

Topic-safe remainder: replace `/` with `=` or `_` (pick one, lock it in the test). File suffix `.parquet`. No real Parquet bytes required — `b"PARQUET"` is enough. Enrichment is read-time and must **not** appear in `HISTORIC_EVENT_COLUMNS`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./00_uns_config/test/test_datalake.py -v`

Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`datalake.py` module docstring (verbatim idea): Historic Events land in object storage later via a Mapper that reads Kafka envelope topic `uns.historic-events`. This module is the port only. Do not subscribe to MQTT here. Do not change `kafka_mapper`.

Types:

```python
HISTORIC_EVENT_COLUMNS = ("time", "topic", "payload")

@dataclass(frozen=True, slots=True)
class HistoricEventRecord:
    time: datetime
    topic: str
    payload: dict[str, Any]


class ObjectStore(Protocol):
    def put(self, path: str, parquet_bytes: bytes) -> None: ...


class FakeObjectStore:
    def __init__(self, root: Path) -> None: ...
    def put(self, path: str, parquet_bytes: bytes) -> None: ...


class S3ObjectStore:
    def __init__(self, *, bucket: str, region: str, prefix: str = "") -> None: ...
    def put(self, path: str, parquet_bytes: bytes) -> None:
        raise NotImplementedError("S3 sink is not in this slice")


class AdlsObjectStore:
    def __init__(self, *, account: str, container: str, prefix: str = "") -> None: ...
    def put(self, path: str, parquet_bytes: bytes) -> None:
        raise NotImplementedError("ADLS sink is not in this slice")
```

Do not add these names to `uns_config/__init__.py` unless a caller outside tests needs them (none does).

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./00_uns_config/test/test_datalake.py ./00_uns_config/test -q --tb=line`

Expected: PASS. No new third-party dependencies.

- [ ] **Step 5: Commit**

```bash
git add 00_uns_config/src/uns_config/datalake.py 00_uns_config/test/test_datalake.py
git commit -m "feat(config): datalake object-store port types without a running sink."
```

---

## Self-review

| Spec requirement | Task |
| --- | --- |
| Save only; no git/recreate button | 3, 4 |
| Keep writing `config.xml` | 3 (`_sync_edge` unchanged) |
| Live Management API | 2, 3 |
| OPC UA on Edge (XML + HTTP + GraphQL) | 2b, 3 |
| Browse/Test stay on `uns_opcua` | 3 (browse unchanged; Test does not call Edge) |
| Subscribe not ISA-95-gated; Subscribe live-applies | 2b (`replace_subscribed_tags`), 3 |
| Edge down keeps Save, pending, next Save retries | 3 |
| XML failure rolls back, no Edge call | 3 (after_flush raises before `_finish_live_apply`) |
| Historian rewrite failure rolls back catalog topic | 5 |
| Remap then live apply; Edge down keeps new topic | 3, 5 |
| Edge accepts → `untested`, empty error | 1, 3 |
| Test is TCP (S7/EIP) or session (OPC UA); pending keeps waiting sentence | 3 |
| No retry worker / Docker socket / Edge status poll | (not added) |
| `opcua_client` profile `legacy-opcua`; prometheus does not depend on it | 6 |
| Lake types/tests only; no Compose sink; Kafka unchanged | 7 |
| No southbound; leave `simulation` | 2, 2b |
| Pending copy verbatim | 1, 3, 4 |
| Settings + compose base_url | 2 |
| README + old spec pointer + `legacy-opcua` | 4 |
