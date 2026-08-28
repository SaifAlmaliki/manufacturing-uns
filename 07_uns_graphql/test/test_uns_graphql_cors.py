"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************
"""

from fastapi.testclient import TestClient

from uns_graphql.uns_graphql_app import UNSGraphql

VITE_ORIGIN = "http://localhost:5173"
COMPOSE_UI_ORIGIN = "http://localhost:8088"


def test_cors_preflight_allows_vite_origin():
    client = TestClient(UNSGraphql.app)
    response = client.options(
        "/graphql",
        headers={
            "Origin": VITE_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") == VITE_ORIGIN


def test_cors_preflight_allows_compose_ui_origin():
    client = TestClient(UNSGraphql.app)
    response = client.options(
        "/graphql",
        headers={
            "Origin": COMPOSE_UI_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") == COMPOSE_UI_ORIGIN


def test_cors_preflight_rejects_unknown_origin():
    client = TestClient(UNSGraphql.app)
    response = client.options(
        "/graphql",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "http://evil.example"
