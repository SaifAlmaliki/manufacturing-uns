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

Entry point for all GraphQL queries to the UNS
"""

import logging

import strawberry
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from strawberry.schema.config import StrawberryConfig
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL

from uns_graphql.auth.context import AuthenticatedGraphQLRouter, graphql_context
from uns_graphql.graphql_config import PlatformConfig
from uns_graphql.mutations.alert_rule import Mutation as AlertRuleMutation
from uns_graphql.mutations.hierarchy import Mutation as HierarchyMutation, Query as HierarchyQuery
from uns_graphql.mutations.oee import Mutation as OeeMutation
from uns_graphql.queries import alert_rule, asset, graph, historian, oee
from uns_graphql.subscriptions.kafka import KAFKASubscription
from uns_graphql.subscriptions.mqtt import MQTTSubscription
from uns_graphql.type.basetype import Int64

LOGGER = logging.getLogger(__name__)


@strawberry.type(description="Query the UNS for current or historic Nodes/Events ")
class Query(historian.Query, graph.Query, asset.Query, alert_rule.Query, oee.Query, HierarchyQuery):
    @classmethod
    async def on_startup(cls):
        """Start background tasks for query modules."""
        await asset.Query.on_startup()

    @classmethod
    async def on_shutdown(cls):
        """
        Clean up connections, db pools etc.
        """
        try:
            await historian.Query.on_shutdown()
        finally:
            try:
                await graph.Query.on_shutdown()
            finally:
                # Last: this disposes the engine that the Asset Model, the Alert Rules
                # and the OEE results share.
                await alert_rule.Query.on_shutdown()
                await oee.Query.on_shutdown()
                await asset.Query.on_shutdown()


@strawberry.type(description="Write configuration to the UNS platform")
class Mutation(AlertRuleMutation, OeeMutation, HierarchyMutation):
    """
    The mutations this service exposes.

    Deliberately narrow: process data is written by publishing to the broker. What is
    left is the console's own configuration (ADR-0005), one correction to plant data
    that no machine can make — which reason a stop is attributed to — and the admin
    write of plant.yaml, because the console is a static bundle with no backend of
    its own.
    """

    @classmethod
    async def on_shutdown(cls):
        """
        Clean up connections, db pools etc.
        """
        await AlertRuleMutation.on_shutdown()
        await OeeMutation.on_shutdown()


@strawberry.type(description="Subscribe to UNS Events or Streams")
class Subscription(MQTTSubscription, KAFKASubscription):
    @classmethod
    async def on_shutdown(cls):
        """
        Clean up connections, db pools etc.
        """
        await MQTTSubscription.on_shutdown()
        await KAFKASubscription.on_shutdown()


class UNSGraphql:
    """
    Class providing the entry point for all GraphQL queries to the UNS & SPB Namespaces
    """

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):  # noqa: ARG002
        """
        lifespan manager to ensure cleanup
        """
        await Query.on_startup()
        try:
            yield
        finally:
            # Mutations first: they share the engine that Query.on_shutdown disposes.
            await Mutation.on_shutdown()
            await Query.on_shutdown()
            await Subscription.on_shutdown()

    schema = strawberry.Schema(
        query=Query, mutation=Mutation, subscription=Subscription, config=StrawberryConfig(
            scalar_map={int: Int64}))

    graphql_app = AuthenticatedGraphQLRouter(
        schema,
        # Every request to /graphql resolves an identity here or is refused with 401. This is
        # the single point that ADR-0005's "There is no authorization in this service" refers
        # to, and the reason that sentence can now be retired.
        context_getter=graphql_context,
        subscription_protocols=[
            GRAPHQL_TRANSPORT_WS_PROTOCOL,
            GRAPHQL_WS_PROTOCOL,
        ],
    )
    LOGGER.info("GraphQL app created")
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=PlatformConfig.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(graphql_app, prefix="/graphql")
    app.lifespan = lifespan
