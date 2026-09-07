from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from uns_config import AuthConfig, get_settings

from uns_factory_agent.app import create_app
from uns_factory_agent.auth import AuthError, Identity, bearer_from_header, identity_from_token
from uns_factory_agent.chat import run_turn
from uns_factory_agent.config import FactoryAgentConfig
from uns_factory_agent.conversations import MemoryConversationStore, utc_now
from uns_factory_agent.health import health_payload
from uns_factory_agent.jwks import JwksCache
from uns_factory_agent.openai_model import OpenAIModelClient
from uns_factory_agent.pg_store import PostgresConversationStore, ensure_schema
from uns_factory_agent.playbook import ADMIN_ROOTS_SQL
from uns_factory_agent.scope_sql import Scope, scope_for
from uns_factory_agent.tools_sql import SqlExecutor, query_asset_model
from uns_model.access_repository import AccessGroupRepository
from uns_model.engine import Database


class SqlAlchemyExecutor:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def fetch(self, sql: str, params: dict) -> list[dict]:
        import asyncio

        async with self._engine.connect() as conn:
            result = await asyncio.wait_for(conn.execute(text(sql), params), timeout=5.0)
            return [dict(row) for row in result.mappings()]


class HttpxGraphqlClient:
    def __init__(self, url: str) -> None:
        self._url = url

    async def post(self, query: str, variables: dict, token: str) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._url,
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    self._url,
                    json={"query": "{ __typename }"},
                )
                return response.status_code < 500
        except Exception:
            return False


@lru_cache(maxsize=1)
def _engine() -> AsyncEngine:
    settings = get_settings("historian")
    host = settings.get("historian.hostname", "localhost")
    port = settings.get("historian.port", 5432)
    user = settings.get("historian.username", "uns_dbuser")
    password = settings.get("historian.password", "")
    database = settings.get("historian.database", "uns_historian")
    url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def _jwks() -> JwksCache:
    return JwksCache(AuthConfig.jwks_url())


@lru_cache(maxsize=1)
def _access_repo() -> AccessGroupRepository:
    return AccessGroupRepository(Database.shared("factory_agent"))


async def _root_paths_for(subject: str) -> frozenset[str]:
    return await _access_repo().root_paths_for_subject(subject)


async def _admin_roots(sql_execute: SqlExecutor) -> tuple[str, ...]:
    """The ENTERPRISE/SITE roots an admin sees, shared by `load_scope` and `chat_handler`
    so the two never drift into different admin-roots SQL or row-shape assumptions (I7)."""
    rows = await query_asset_model(ADMIN_ROOTS_SQL, scope=Scope(True, frozenset()), execute=sql_execute)
    return tuple(str(row["path"]) for row in rows if "path" in row)


async def check_health() -> dict:
    db_ok = False
    try:
        async with _engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    graphql_ok = await HttpxGraphqlClient(FactoryAgentConfig.graphql_url).ping()
    return health_payload(
        openai_key=FactoryAgentConfig.openai_api_key,
        db_ok=db_ok,
        graphql_ok=graphql_ok,
    )


def create_production_app():
    engine = _engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    holder: dict[str, MemoryConversationStore | PostgresConversationStore] = {
        "store": MemoryConversationStore()
    }
    jwks = _jwks()
    sql_execute = SqlAlchemyExecutor(engine)
    graphql = HttpxGraphqlClient(FactoryAgentConfig.graphql_url)
    model = OpenAIModelClient(api_key=FactoryAgentConfig.openai_api_key)

    class StoreProxy:
        async def list_for(self, subject: str, *, now):
            return await holder["store"].list_for(subject, now=now)

        async def get(self, conversation_id: str, subject: str, *, now):
            return await holder["store"].get(conversation_id, subject, now=now)

        async def create(self, subject: str, *, now):
            return await holder["store"].create(subject, now=now)

        async def delete(self, conversation_id: str, subject: str) -> bool:
            return await holder["store"].delete(conversation_id, subject)

        async def append(self, conversation_id, subject, role, body, citations, *, now):
            return await holder["store"].append(
                conversation_id, subject, role, body, citations, now=now
            )

        async def last_messages(self, conversation_id: str, subject: str, *, limit: int = 20):
            return await holder["store"].last_messages(conversation_id, subject, limit=limit)

        async def purge_expired(self, *, now):
            return await holder["store"].purge_expired(now=now)

    async def on_startup() -> None:
        try:
            await ensure_schema(engine)
            holder["store"] = PostgresConversationStore(session_factory)
        except Exception:
            holder["store"] = MemoryConversationStore()
        await holder["store"].purge_expired(now=utc_now())

    @asynccontextmanager
    async def lifespan(_app):
        await on_startup()
        yield

    async def get_identity(authorization: str | None) -> Identity:
        token = bearer_from_header(authorization)
        if not token:
            raise AuthError("The request has no Authorization bearer token.")
        return await identity_from_token(token, jwks)

    async def load_scope(identity: Identity) -> dict:
        if identity.is_admin:
            roots = await _admin_roots(sql_execute)
            return {"roots": list(roots), "unrestricted": True}
        roots = await _root_paths_for(identity.subject)
        return {"roots": sorted(roots), "unrestricted": False}

    async def chat_handler(**kwargs):
        identity: Identity = kwargs.pop("identity")
        roots = await _root_paths_for(identity.subject)
        scope = scope_for(is_admin=identity.is_admin, root_paths=roots)
        admin_roots = await _admin_roots(sql_execute) if identity.is_admin else ()
        return await run_turn(
            scope=scope,
            model=model,
            sql_execute=sql_execute,
            graphql=graphql,
            admin_roots=admin_roots,
            **kwargs,
        )

    return create_app(
        StoreProxy(),
        get_identity=get_identity,
        health_check=check_health,
        chat_handler=chat_handler,
        scope_loader=load_scope,
        lifespan=lifespan,
    )
