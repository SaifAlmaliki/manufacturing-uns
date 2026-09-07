from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from uns_factory_agent.auth import AuthError, Identity, bearer_from_header
from uns_factory_agent.chat import ChatResult, PageContext, run_turn
from uns_factory_agent.conversations import ConversationStore, MemoryConversationStore, utc_now

IdentityGetter = Callable[[str | None], Identity | Awaitable[Identity]]


class PageContextBody(BaseModel):
    route: str = ""
    assetPath: str = ""
    metricKey: str = ""
    alarmTopic: str = ""


class ChatBody(BaseModel):
    message: str
    conversationId: str
    context: PageContextBody = Field(default_factory=PageContextBody)


def _iso(dt) -> str:
    return dt.isoformat()


def _conversation_json(conv) -> dict:
    return {"id": conv.id, "title": conv.title, "updatedAt": _iso(conv.updated_at)}


def _message_json(msg) -> dict:
    return {
        "role": msg.role,
        "body": msg.body,
        "citations": [
            {
                "asset": c.asset,
                "topic": c.topic,
                "time": c.time,
                "source": c.source,
            }
            for c in msg.citations
        ],
    }


async def _resolve_identity(get_identity: IdentityGetter, authorization: str | None) -> Identity:
    try:
        result = get_identity(authorization)
        if hasattr(result, "__await__"):
            return await result  # type: ignore[misc]
        return result  # type: ignore[return-value]
    except AuthError as ex:
        raise HTTPException(status_code=401, detail=str(ex)) from ex


def create_app(
    store: ConversationStore,
    *,
    get_identity: IdentityGetter,
    health_check: Callable[[], dict | Awaitable[dict]] | None = None,
    chat_handler: Callable[..., Any] | None = None,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    app = FastAPI(title="Factory Copilot", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        if health_check is None:
            return {"status": "ok"}
        result = health_check()
        if hasattr(result, "__await__"):
            return await result  # type: ignore[misc]
        return result  # type: ignore[return-value]

    @app.get("/conversations")
    async def list_conversations(authorization: str | None = Header(default=None)) -> list[dict]:
        identity = await _resolve_identity(get_identity, authorization)
        rows = await store.list_for(identity.subject, now=utc_now())
        return [_conversation_json(c) for c in rows]

    @app.post("/conversations")
    async def create_conversation(authorization: str | None = Header(default=None)) -> dict:
        identity = await _resolve_identity(get_identity, authorization)
        conv = await store.create(identity.subject, now=utc_now())
        return _conversation_json(conv)

    @app.get("/conversations/{conversation_id}")
    async def get_conversation(
        conversation_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        identity = await _resolve_identity(get_identity, authorization)
        conv = await store.get(conversation_id, identity.subject, now=utc_now())
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        messages = await store.last_messages(conversation_id, identity.subject)
        return {
            **_conversation_json(conv),
            "messages": [_message_json(m) for m in messages],
        }

    @app.delete("/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(
        conversation_id: str,
        authorization: str | None = Header(default=None),
    ) -> None:
        identity = await _resolve_identity(get_identity, authorization)
        if not await store.delete(conversation_id, identity.subject):
            raise HTTPException(status_code=404, detail="Conversation not found.")

    @app.post("/chat")
    async def chat(body: ChatBody, authorization: str | None = Header(default=None)) -> dict:
        identity = await _resolve_identity(get_identity, authorization)
        now = utc_now()
        conv = await store.get(body.conversationId, identity.subject, now=now)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        token = bearer_from_header(authorization) or ""
        context = PageContext(
            route=body.context.route,
            asset_path=body.context.assetPath,
            metric_key=body.context.metricKey,
            alarm_topic=body.context.alarmTopic,
        )

        if chat_handler is None:
            raise HTTPException(status_code=503, detail="Chat is not configured.")

        result: ChatResult = await chat_handler(
            store=store,
            conversation_id=body.conversationId,
            subject=identity.subject,
            token=token,
            message=body.message,
            context=context,
            identity=identity,
            now=now,
        )
        return {
            "text": result.text,
            "citations": [
                {
                    "asset": c.asset,
                    "topic": c.topic,
                    "time": c.time,
                    "source": c.source,
                }
                for c in result.citations
            ],
        }

    @app.exception_handler(AuthError)
    async def auth_error_handler(_request, exc: AuthError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    return app


def build_default_app() -> FastAPI:
    from uns_factory_agent.wiring import create_production_app

    return create_production_app()


try:
    app = build_default_app()
except Exception:  # noqa: BLE001 — allow importing create_app in tests without full wiring
    app = create_app(MemoryConversationStore(), get_identity=lambda _h: (_ for _ in ()).throw(AuthError("unconfigured")))
