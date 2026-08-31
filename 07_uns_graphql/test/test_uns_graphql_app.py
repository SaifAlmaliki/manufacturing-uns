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

from unittest.mock import AsyncMock, patch

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from uns_graphql.backend.graphdb import GraphDB
from uns_graphql.queries import graph, historian
from uns_graphql.subscriptions.kafka import KAFKASubscription
from uns_graphql.subscriptions.mqtt import MQTTSubscription
from uns_graphql.uns_graphql_app import UNSGraphql
from uns_model.engine import Database


def test_uns_graphql_app_attributes():
    """
    Test validity of key attributes of  UNSGraphql needed to start run the GraphQL server
    """
    assert UNSGraphql.schema is not None
    assert UNSGraphql.app is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_uns_graphql_app_test_cleanup_on_shutdown():
    """
    Test to validate that the app calls the cleanup method on the query and subscription classes
    """
    # patch the classes
    with patch.object(historian.Query, "on_shutdown", new_callable=AsyncMock) as mock_historic_cleanup, patch.object(
        graph.Query, "on_shutdown", new_callable=AsyncMock
    ) as mock_uns_cleanup, patch.object(
        MQTTSubscription, "on_shutdown", new_callable=AsyncMock
    ) as mock_mqtt_cleanup, patch.object(KAFKASubscription, "on_shutdown", new_callable=AsyncMock) as mock_kafka_cleanup:
        # Initialize the UNSGraphql app
        uns_graphql_app = UNSGraphql()
        app: FastAPI = uns_graphql_app.app

        # Simulate the lifespan context
        @asynccontextmanager
        async def lifespan_context(app):
            async with uns_graphql_app.lifespan(app):
                yield

        # Simulate the startup and shutdown sequence
        async with lifespan_context(app):
            pass
    # Every query/subscription class gets its on_shutdown called, including the ones
    # whose on_shutdown is now a no-op: the app must not have to know which is which.
    mock_historic_cleanup.assert_called_once()
    mock_uns_cleanup.assert_called_once()
    mock_mqtt_cleanup.assert_called_once()
    mock_kafka_cleanup.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_uns_graphql_app_db_pool_cleanup():
    """
    Every database this service holds open is released on shutdown.

    One Postgres engine for the historian, the Asset Model and the Alert Rules
    (ADR-0004), and one driver for the graph database. Both must be disposed exactly
    once: a lifespan that leaves either open is how a redeployed container is refused
    connections by its own database.
    """
    # patch the classes
    with patch.object(Database, "close_shared", new_callable=AsyncMock) as mock_engine_dispose, patch.object(
        GraphDB,
        "release_graphdb_driver",
        new_callable=AsyncMock,
    ) as mock_graphdb_close_pool:
        # Initialize the UNSGraphql app
        uns_graphql_app = UNSGraphql()
        app: FastAPI = uns_graphql_app.app

        # Simulate the lifespan context
        @asynccontextmanager
        async def lifespan_context(app):
            async with uns_graphql_app.lifespan(app):
                yield

        # Simulate the startup and shutdown sequence
        async with lifespan_context(app):
            pass
    # Once, by the Asset Model query: the historian and Alert Rule queries share that
    # engine and deliberately leave the disposing to it.
    mock_engine_dispose.assert_awaited_once()
    mock_graphdb_close_pool.assert_called_once()


def test_uns_graphql_app_uvicorn_compatibility():
    """
    Test to validate that UNSGraphql.app can be instantiated by uvicorn
    """
    uns_graphql_app = UNSGraphql()
    app = uns_graphql_app.app

    # Create a mock uvicorn config
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info")

    # Attempt to create a Server instance
    try:
        server = uvicorn.Server(config)
        assert server is not None
    except Exception as e:
        pytest.fail(f"Failed to create uvicorn Server instance: {e!s}")

    # Optionally, you can add more assertions here if needed
    assert isinstance(app, FastAPI)
    assert app.router.routes is not None
