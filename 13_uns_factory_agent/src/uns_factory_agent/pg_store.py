from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from uns_factory_agent.conversations import (
    RETENTION,
    Citation,
    Conversation,
    Message,
    Role,
)

_ENSURE_SCHEMA = """
CREATE SCHEMA IF NOT EXISTS copilot;
CREATE TABLE IF NOT EXISTS copilot.conversation (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  title TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS copilot.message (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES copilot.conversation(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  body TEXT NOT NULL,
  citations JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS conversation_subject_updated ON copilot.conversation (subject, updated_at DESC);
"""


async def ensure_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for statement in _ENSURE_SCHEMA.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                await conn.execute(text(stmt))


def _parse_citations(raw: object) -> tuple[Citation, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[Citation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = item.get("source", "historian")
        if source not in ("model", "historian", "live", "alarms"):
            source = "historian"
        out.append(
            Citation(
                asset=str(item.get("asset", "")),
                topic=str(item.get("topic", "")),
                time=str(item.get("time", "")),
                source=source,  # type: ignore[arg-type]
            )
        )
    return tuple(out)


class PostgresConversationStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_for(self, subject: str, *, now: datetime) -> list[Conversation]:
        cutoff = now - RETENTION
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, subject, title, created_at, updated_at
                        FROM copilot.conversation
                        WHERE subject = :subject AND updated_at >= :cutoff
                        ORDER BY updated_at DESC
                        """
                    ),
                    {"subject": subject, "cutoff": cutoff},
                )
            ).mappings()
            return [_row_to_conversation(row) for row in rows]

    async def get(self, conversation_id: str, subject: str, *, now: datetime) -> Conversation | None:
        cutoff = now - RETENTION
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, subject, title, created_at, updated_at
                        FROM copilot.conversation
                        WHERE id = :id AND subject = :subject AND updated_at >= :cutoff
                        """
                    ),
                    {"id": conversation_id, "subject": subject, "cutoff": cutoff},
                )
            ).mappings().first()
            return _row_to_conversation(row) if row else None

    async def create(self, subject: str, *, now: datetime) -> Conversation:
        conv = Conversation(
            id=uuid.uuid4().hex,
            subject=subject,
            title="New chat",
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO copilot.conversation (id, subject, title, created_at, updated_at)
                    VALUES (:id, :subject, :title, :created_at, :updated_at)
                    """
                ),
                {
                    "id": conv.id,
                    "subject": conv.subject,
                    "title": conv.title,
                    "created_at": conv.created_at,
                    "updated_at": conv.updated_at,
                },
            )
            await session.commit()
        return conv

    async def delete(self, conversation_id: str, subject: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "DELETE FROM copilot.conversation WHERE id = :id AND subject = :subject RETURNING id"
                ),
                {"id": conversation_id, "subject": subject},
            )
            await session.commit()
            return result.first() is not None

    async def append(
        self,
        conversation_id: str,
        subject: str,
        role: Role,
        body: str,
        citations: tuple[Citation, ...],
        *,
        now: datetime,
    ) -> Message:
        conv = await self.get(conversation_id, subject, now=now)
        if conv is None:
            raise KeyError(conversation_id)
        title = conv.title
        if role == "user" and title == "New chat":
            title = body[:60]
        message = Message(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            role=role,
            body=body,
            citations=citations,
            created_at=now,
        )
        payload = [
            {
                "asset": c.asset,
                "topic": c.topic,
                "time": c.time,
                "source": c.source,
            }
            for c in citations
        ]
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE copilot.conversation
                    SET title = :title, updated_at = :updated_at
                    WHERE id = :id AND subject = :subject
                    """
                ),
                {
                    "title": title,
                    "updated_at": now,
                    "id": conversation_id,
                    "subject": subject,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO copilot.message (id, conversation_id, role, body, citations, created_at)
                    VALUES (:id, :conversation_id, :role, :body, CAST(:citations AS jsonb), :created_at)
                    """
                ),
                {
                    "id": message.id,
                    "conversation_id": conversation_id,
                    "role": role,
                    "body": body,
                    "citations": json.dumps(payload),
                    "created_at": now,
                },
            )
            await session.commit()
        return message

    async def last_messages(self, conversation_id: str, subject: str, *, limit: int = 20) -> list[Message]:
        from uns_factory_agent.conversations import utc_now

        conv = await self.get(conversation_id, subject, now=utc_now())
        if conv is None:
            return []
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, conversation_id, role, body, citations, created_at
                        FROM copilot.message
                        WHERE conversation_id = :conversation_id
                        ORDER BY created_at ASC
                        LIMIT :limit
                        """
                    ),
                    {"conversation_id": conversation_id, "limit": limit},
                )
            ).mappings()
            return [_row_to_message(row) for row in rows]

    async def purge_expired(self, *, now: datetime) -> int:
        cutoff = now - RETENTION
        async with self._session_factory() as session:
            result = await session.execute(
                text("DELETE FROM copilot.conversation WHERE updated_at < :cutoff RETURNING id"),
                {"cutoff": cutoff},
            )
            await session.commit()
            return len(result.fetchall())


def _row_to_conversation(row) -> Conversation:
    return Conversation(
        id=row["id"],
        subject=row["subject"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row) -> Message:
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        body=row["body"],
        citations=_parse_citations(row["citations"]),
        created_at=row["created_at"],
    )
