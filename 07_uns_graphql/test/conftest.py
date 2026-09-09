"""Shared pytest hooks for the GraphQL module."""

import pytest
import pytest_asyncio
from uns_model.engine import Database


@pytest_asyncio.fixture(autouse=True)
async def _reset_asset_model_singletons():
    """Drop cached DB engines and topic resolvers so retries and xdist workers stay isolated."""
    import uns_graphql.queries.asset as asset_module

    asset_module._resolver = None
    yield
    asset_module._resolver = None
    await Database.close_shared()
