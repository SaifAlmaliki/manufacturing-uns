from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

Role = Literal["user", "assistant"]
RETENTION = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class Citation:
    asset: str
    topic: str
    time: str
    source: Literal["model", "historian", "live", "alarms"]


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str
    role: Role
    body: str
    citations: tuple[Citation, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    subject: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationStore(Protocol):
    async def list_for(self, subject: str, *, now: datetime) -> list[Conversation]: ...
    async def get(self, conversation_id: str, subject: str, *, now: datetime) -> Conversation | None: ...
    async def create(self, subject: str, *, now: datetime) -> Conversation: ...
    async def delete(self, conversation_id: str, subject: str) -> bool: ...
    async def append(
        self,
        conversation_id: str,
        subject: str,
        role: Role,
        body: str,
        citations: tuple[Citation, ...],
        *,
        now: datetime,
    ) -> Message: ...
    async def last_messages(self, conversation_id: str, subject: str, *, limit: int = 20) -> list[Message]: ...
    async def purge_expired(self, *, now: datetime) -> int: ...


@dataclass
class _ConversationRecord:
    conversation: Conversation
    messages: list[Message]


class MemoryConversationStore:
    def __init__(self) -> None:
        self._conversations: dict[str, _ConversationRecord] = {}

    async def list_for(self, subject: str, *, now: datetime) -> list[Conversation]:
        rows = [
            record.conversation
            for record in self._conversations.values()
            if record.conversation.subject == subject and not _expired(record.conversation, now)
        ]
        return sorted(rows, key=lambda c: c.updated_at, reverse=True)

    async def get(self, conversation_id: str, subject: str, *, now: datetime) -> Conversation | None:
        record = self._conversations.get(conversation_id)
        if record is None or record.conversation.subject != subject:
            return None
        if _expired(record.conversation, now):
            return None
        return record.conversation

    async def create(self, subject: str, *, now: datetime) -> Conversation:
        conv = Conversation(
            id=uuid.uuid4().hex,
            subject=subject,
            title="New chat",
            created_at=now,
            updated_at=now,
        )
        self._conversations[conv.id] = _ConversationRecord(conversation=conv, messages=[])
        return conv

    async def delete(self, conversation_id: str, subject: str) -> bool:
        record = self._conversations.get(conversation_id)
        if record is None or record.conversation.subject != subject:
            return False
        del self._conversations[conversation_id]
        return True

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
        record = self._conversations.get(conversation_id)
        if record is None or record.conversation.subject != subject:
            raise KeyError(conversation_id)
        if _expired(record.conversation, now):
            raise KeyError(conversation_id)
        message = Message(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            role=role,
            body=body,
            citations=citations,
            created_at=now,
        )
        record.messages.append(message)
        title = record.conversation.title
        if role == "user" and title == "New chat":
            title = body[:60]
        record.conversation = Conversation(
            id=record.conversation.id,
            subject=record.conversation.subject,
            title=title,
            created_at=record.conversation.created_at,
            updated_at=now,
        )
        return message

    async def last_messages(self, conversation_id: str, subject: str, *, limit: int = 20) -> list[Message]:
        record = self._conversations.get(conversation_id)
        if record is None or record.conversation.subject != subject:
            return []
        return record.messages[-limit:]

    async def purge_expired(self, *, now: datetime) -> int:
        expired_ids = [
            cid
            for cid, record in self._conversations.items()
            if _expired(record.conversation, now)
        ]
        for cid in expired_ids:
            del self._conversations[cid]
        return len(expired_ids)


def _expired(conversation: Conversation, now: datetime) -> bool:
    return now - conversation.updated_at > RETENTION


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(tz=UTC)
