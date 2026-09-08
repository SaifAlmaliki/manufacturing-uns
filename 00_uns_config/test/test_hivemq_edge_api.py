from __future__ import annotations

import json

import httpx
import pytest

from uns_config.hivemq_edge_api import EdgeApplyError, apply_catalog_adapters_live
from uns_config.hivemq_edge_xml import EdgeAdapterInput, EdgeTagInput


def _s7(*, tags=()):
    return EdgeAdapterInput(
        server_id="srv_1",
        protocol="s7",
        host="10.0.0.6",
        port=103,
        controller_type="S7_300",
        tags=tags,
    )


def _opcua(*, tags=()):
    return EdgeAdapterInput(
        server_id="srv_opc",
        protocol="opc_ua",
        host="",
        port=0,
        uri="opc.tcp://192.0.2.1:4840",
        tags=tags,
    )


def test_apply_opcua_creates_adapter_tags_and_mappings():
    calls: list[tuple[str, str, bytes]] = []

    def handler(request):
        calls.append((request.method, request.url.path, request.read()))
        if request.url.path.endswith("/auth/authenticate"):
            return httpx.Response(200, json={"token": "t0"})
        if request.method == "GET" and request.url.path.endswith("/adapters"):
            return httpx.Response(200, json={"items": [{"id": "sim", "type": "simulation"}]})
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://edge")
    tag = EdgeTagInput(
        node_id="ns=1;i=1004",
        display_name="Temp",
        mqtt_topic="Server/OpcPlc/Temp",
        data_type="Double",
    )
    apply_catalog_adapters_live([_opcua(tags=(tag,))], client=client, username="admin", password="hivemq")

    paths = [(m, p) for m, p, _ in calls]
    assert ("POST", "/api/v1/management/protocol-adapters/adapters/opcua") in paths
    assert not any(p.endswith("/southboundMappings") for _, p in paths)
    assert not any("sim" in p and m == "DELETE" for m, p in paths)

    create_body = json.loads(
        next(body for m, p, body in calls if m == "POST" and p.endswith("/adapters/opcua"))
    )
    assert create_body["config"] == {"uri": "opc.tcp://192.0.2.1:4840"}
    assert "host" not in create_body["config"]

    tags_body = json.loads(
        next(
            body
            for m, p, body in calls
            if m == "PUT" and p.endswith("/catalog-srv_opc/tags")
        )
    )
    definition = tags_body["items"][0]["definition"]
    assert definition["node"] == "ns=1;i=1004"
    assert definition["dataType"] == "REAL"


def test_apply_creates_adapter_tags_and_mappings():
    calls: list[tuple[str, str, bytes]] = []

    def handler(request):
        calls.append((request.method, request.url.path, request.read()))
        if request.url.path.endswith("/auth/authenticate"):
            return httpx.Response(200, json={"token": "t0"})
        if request.method == "GET" and request.url.path.endswith("/adapters"):
            return httpx.Response(200, json={"items": [{"id": "sim", "type": "simulation"}]})
        return httpx.Response(200, json={})

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

    create_body = json.loads(next(body for m, p, body in calls if m == "POST" and p.endswith("/adapters/s7")))
    assert create_body["config"]["controllerType"] == "S7_300"

    tags_body = json.loads(
        next(
            body
            for m, p, body in calls
            if m == "PUT" and p.endswith("/catalog-srv_1/tags")
        )
    )
    definition = tags_body["items"][0]["definition"]
    assert definition["tagAddress"] == "%ID103"
    assert definition["dataType"] == "DINT"


def test_apply_updates_existing_catalog_adapter():
    calls: list[tuple[str, str]] = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/auth/authenticate"):
            return httpx.Response(200, json={"token": "t0"})
        if request.method == "GET" and request.url.path.endswith("/adapters"):
            return httpx.Response(
                200,
                json={"items": [{"id": "catalog-srv_1", "type": "s7"}]},
            )
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://edge")
    apply_catalog_adapters_live([_s7()], client=client, username="admin", password="hivemq")
    assert ("PUT", "/api/v1/management/protocol-adapters/adapters/catalog-srv_1") in calls
    assert ("POST", "/api/v1/management/protocol-adapters/adapters/s7") not in calls


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
    def handler(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://edge")
    with pytest.raises(EdgeApplyError):
        apply_catalog_adapters_live([_s7()], client=client, username="admin", password="hivemq")


def test_apply_http_error_is_edge_apply_error():
    def handler(request):
        if request.url.path.endswith("/auth/authenticate"):
            return httpx.Response(200, json={"token": "t0"})
        return httpx.Response(500, json={"title": "boom"})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://edge")
    with pytest.raises(EdgeApplyError):
        apply_catalog_adapters_live([_s7()], client=client, username="admin", password="hivemq")
