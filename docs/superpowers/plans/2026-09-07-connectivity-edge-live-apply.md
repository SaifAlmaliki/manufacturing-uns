# Live HiveMQ Edge Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an engineer Saves an S7 or EtherNet/IP server or signal, GraphQL still writes `config.xml` and also pushes the same catalog adapters to the running HiveMQ Edge so MQTT can start without recreating the broker.

**Architecture:** Keep `after_flush` as the XML write (Save rolls back if the file write fails). After the row is stored, GraphQL calls a new `uns_config` Edge Management API client. If Edge accepts, clear pending (`untested`). If Edge is down, keep the Save and leave `pending`. Next Save retries. No Docker socket. No background worker.

**Tech Stack:** `httpx` in `00_uns_config`, existing `EdgeAdapterInput`, Strawberry GraphQL, React + Vitest, pytest + `httpx.MockTransport`.

**Spec:** `docs/superpowers/specs/2026-09-07-connectivity-edge-live-apply-design.md`

## Global Constraints

- **Pending copy (verbatim):** `Waiting for HiveMQ Edge to apply`
- **`EDGE_APPLY_ERROR` is that sentence.** Model, GraphQL, and frontend tests must match it.
- **XML write still rolls back the Save.** Live apply never rolls back the Save.
- **Live apply is S7/EIP only.** OPC UA mutations do not call the Edge client.
- **No southbound** on the API payload.
- **Do not create, update, or delete** `simulation` or any non-`catalog-*` adapter.
- **Catalog `adapterId`** remains `catalog-<server.id>`. Catalog `ethernet_ip` → Edge type `eip`.
- **API timeout:** 10 seconds.
- **Test stays TCP.** It does not push to Edge. If the server is still `pending`, a successful Test keeps `EDGE_APPLY_ERROR`.
- **`last_error` is NOT NULL.** Cleared means `""`, not SQL NULL.
- **No live broker in pytest.** Mock HTTP only.
- **Do not implement on `main`.** Branch `feat/connectivity-edge-live-apply` from current `main`.
- **`uns_config` must not import `uns_model`.**

---

## File Structure

```
09_uns_model/src/uns_model/connectivity.py
09_uns_model/test/test_connectivity.py

00_uns_config/pyproject.toml
00_uns_config/src/uns_config/hivemq_edge_api.py
00_uns_config/test/test_hivemq_edge_api.py
conf/settings.yaml
docker-compose.yml

07_uns_graphql/src/uns_graphql/mutations/connectivity.py
07_uns_graphql/test/mutations/test_connectivity.py

11_frontend/src/components/connectivity/ConnectivityView.test.tsx
11_frontend/src/components/connectivity/ConnectivityView.tsx   # only if recreate sentence is hardcoded

conf/hivemq/README.md
docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md
```

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
    return "eip" if protocol == "ethernet_ip" else "s7"


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

### Task 3: GraphQL Save calls live apply after the row is stored

**Files:**
- Modify: `07_uns_graphql/src/uns_graphql/mutations/connectivity.py`
- Modify: `07_uns_graphql/test/mutations/test_connectivity.py`

**Interfaces:**
- Consumes: `_sync_edge` (XML, unchanged); `apply_catalog_adapters_live`; `EdgeApplyError`; `edge_adapters_from_rows`; `PLC_PROTOCOLS`; `record_live_apply`
- Produces: `_finish_live_apply(mutated_ids: list[str]) -> None` used only on S7/EIP mutations

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
async def test_save_opc_ua_does_not_call_live_apply(monkeypatch):
    live = Mock()
    monkeypatch.setattr("uns_graphql.mutations.connectivity.apply_catalog_adapters_live", live)
    repository = AsyncMock()
    saved = _server(server_id="srv-opc", protocol="opc_ua", endpoint="opc.tcp://h:4840")
    repository.save_server.return_value = saved
    with patch(REPOSITORY, return_value=repository):
        result = await UNSGraphql.schema.execute(
            """
            mutation {
              saveConnectivityServer(server: {
                id: "srv-opc", name: "opc", protocol: OPC_UA,
                endpoint: "opc.tcp://h:4840"
              }) { id }
            }
            """,
            context_value=ADMIN,
        )
    assert result.errors is None
    live.assert_not_called()
    repository.record_live_apply.assert_not_awaited()
```

Adapt field names on `ConnectivityServerInput` to whatever `test_save_connectivity_server_s7_calls_after_flush` already sends (copy that mutation document). If `_server` needs extra kwargs, copy from that test.

If XML `after_flush` is not invoked in the OPC UA test because the mock does not call it, that is fine — the assertion is that live apply is not called.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest ./07_uns_graphql/test/mutations/test_connectivity.py::test_save_s7_live_apply_success_records_untested ./07_uns_graphql/test/mutations/test_connectivity.py::test_save_s7_live_apply_failure_keeps_save ./07_uns_graphql/test/mutations/test_connectivity.py::test_save_opc_ua_does_not_call_live_apply -v`

Expected: FAIL — `_finish_live_apply` / `record_live_apply` not wired.

- [ ] **Step 3: Implement**

In `mutations/connectivity.py`:

```python
from uns_config.hivemq_edge_api import EdgeApplyError, apply_catalog_adapters_live
from uns_model.connectivity import (
    EDGE_APPLY_ERROR,
    PLC_PROTOCOLS,
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
    plc_ids = [adapter.server_id for adapter in adapters] or mutated_ids
    await repo.record_live_apply(plc_ids, ok=True)
```

After each PLC write, call it:

- `save_connectivity_server`: after `save_server`, if `saved.protocol in PLC_PROTOCOLS`: `await _finish_live_apply([saved.id])`. Return `from_server` of a re-fetched server if you need fresh `lastStatus` (call `list_servers` / `_find_server` after apply). The mutation return should reflect `untested` or `pending` after apply — re-fetch `saved = await _find_server(repo, saved.id)` after `_finish_live_apply`.
- `delete_connectivity_server`: look up the server **before** delete. If it is PLC and `deleted`, `await _finish_live_apply([])` (empty mutated ids; leftover catalog adapters are deleted by the client). Do not fail the mutation if apply fails.
- `save_connectivity_tag`, `update_connectivity_tag`, `update_connectivity_tag_topic`, `unsubscribe_connectivity_tag`: after the repository call, if the server protocol is PLC, `await _finish_live_apply([server_id])`. Load protocol with `_find_server` **before** unsubscribe/update if the tag path does not return the server.

Do not call `_finish_live_apply` from `subscribe_opc_ua_variables` or OPC UA `save_connectivity_server`.

Update the `test_connectivity_server` comment: keep `EDGE_APPLY_ERROR` on pending TCP success because live apply has not succeeded, not because of recreate.

- [ ] **Step 4: Run tests**

Run: `uv run pytest ./07_uns_graphql/test/mutations/test_connectivity.py ./07_uns_graphql/test/type/test_connectivity.py ./07_uns_graphql/test/auth/test_require.py -q --tb=line`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 07_uns_graphql/src/uns_graphql/mutations/connectivity.py 07_uns_graphql/test/mutations/test_connectivity.py
git commit -m "feat(graphql): apply S7 and EIP catalog rows to live HiveMQ Edge."
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

`conf/hivemq/README.md` replace the recreate-first S7/EIP paragraph with:

```markdown
**S7 and EtherNet/IP:** author host, port, controller type, and signals in Assets &
Connectivity (`#/connectivity/servers`). GraphQL upserts catalog-owned
`<protocol-adapter>` blocks (`adapterId` `catalog-<server id>`) and pushes the
same adapters to the running broker over the Edge Management API. MQTT can start
on Save. Recreate the broker only for an image upgrade or disaster recovery:

```bash
uv run uns_compose up -d --force-recreate uns_mqtt_broker
```
```

At the top of `docs/superpowers/specs/2026-09-07-connectivity-s7-eip-edge-design.md`, immediately after the Related list, add:

```markdown
Apply path: superseded by
[2026-09-07-connectivity-edge-live-apply-design.md](./2026-09-07-connectivity-edge-live-apply-design.md).
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

**Manual check (not a pytest gate):** with the stack up, add one S7 or EIP signal, do **not** recreate `uns_mqtt_broker`, subscribe to that MQTT topic. If the PLC or sim is reachable from the broker container, a value arrives.

---

## Self-review

| Spec requirement | Task |
| --- | --- |
| Save only; no git/recreate button | 3, 4 |
| Keep writing `config.xml` | 3 (`_sync_edge` unchanged) |
| Live Management API | 2, 3 |
| Edge down keeps Save, pending, next Save retries | 3 |
| XML failure rolls back, no Edge call | 3 (after_flush raises before `_finish_live_apply`) |
| Edge accepts → `untested`, empty error | 1, 3 |
| Test is TCP; pending keeps waiting sentence | 3 |
| No retry worker / Docker socket / Edge status poll | (not added) |
| OPC UA unchanged | 3 |
| No southbound; leave `simulation` | 2 |
| Pending copy verbatim | 1, 3, 4 |
| Settings + compose base_url | 2 |
| README + old spec pointer | 4 |
