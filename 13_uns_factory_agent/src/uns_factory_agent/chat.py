from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from uns_factory_agent.classify import classify
from uns_factory_agent.console_map import CONSOLE_MAP, PLATFORM_HEALTH_REPLY
from uns_factory_agent.context_pack import ContextPack, build_context_pack
from uns_factory_agent.conversations import Citation, ConversationStore
from uns_factory_agent.playbook import PlaybookResult, run_playbook
from uns_factory_agent.schema_cards import SCHEMA_CARDS
from uns_factory_agent.scope_sql import Scope
from uns_factory_agent.tools_graphql import GraphqlPost, query_alarms, query_live
from uns_factory_agent.tools_sql import SqlExecutor, query_asset_model, query_historian

MAX_TOOL_ROUNDS = 3

SYSTEM_PROMPT = """You are Factory Copilot, a plant colleague. Speak in first person, short sentences.
Cite Asset, topic, and time. If tools return nothing, say you cannot see it.
You cannot ack alarms, change Alert Rules, edit the Asset Model, or write values.
Use only these tools: query_asset_model, query_historian, query_live, query_alarms.

When investigating declining equipment performance (e.g. a pump losing head over weeks):
1. Find the Asset in the Asset Model (query_asset_model).
2. Pull historian trends for its Metrics over the last three weeks and last shift (query_historian).
3. Check downtime events on that line (query_historian on oee.downtime_event).
4. See if any Alert Rules are firing on that Asset (query_alarms).
5. Read live Metric values (query_live).
Combine the evidence, state what you found and what you cannot see, then suggest plausible causes.
Never invent numbers — only cite values returned by tools.
When you have your final answer, call submit_answer with text and citations."""


@dataclass(frozen=True, slots=True)
class PageContext:
    route: str
    asset_path: str
    metric_key: str
    alarm_topic: str


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ModelTurn:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    citations: tuple[Citation, ...]


class ModelClient(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn: ...


OPENAI_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_asset_model",
            "description": "Run a read-only SELECT against the Asset Model.",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_historian",
            "description": "Run a read-only SELECT against uns_metrics or oee.downtime_event.",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_live",
            "description": "Read live UNS Node values for topic filters.",
            "parameters": {
                "type": "object",
                "properties": {"topics": {"type": "array", "items": {"type": "string"}}},
                "required": ["topics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_alarms",
            "description": "List Alert Rules.",
            "parameters": {
                "type": "object",
                "properties": {"enabled_only": {"type": "boolean"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": "Submit the final answer with citations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "asset": {"type": "string"},
                                "topic": {"type": "string"},
                                "time": {"type": "string"},
                                "source": {
                                    "type": "string",
                                    "enum": ["model", "historian", "live", "alarms"],
                                },
                            },
                            "required": ["asset", "topic", "time", "source"],
                        },
                    },
                },
                "required": ["text", "citations"],
            },
        },
    },
]


def _build_system(pack: ContextPack, playbook: PlaybookResult) -> str:
    cards = "\n\n".join(f"### {name}\n{body}" for name, body in SCHEMA_CARDS.items())
    focus = pack.focus
    ctx = (
        f"Page route: {pack.route or '(none)'}\n"
        f"Selected Asset path: {focus.asset_path or '(none)'}\n"
        f"Selected Metric key: {focus.metric_key or '(none)'}\n"
        f"Selected alarm topic: {focus.alarm_topic or '(none)'}\n"
        f"Default plant roots: {', '.join(pack.default_plant) or '(none)'}\n"
        f"Page hint: {pack.page_hint}\n"
        f"Unrestricted: {pack.unrestricted}"
    )
    parts = [
        SYSTEM_PROMPT,
        f"## Console map\n{CONSOLE_MAP}",
        f"## Schema cards\n{cards}",
        f"## Page context\n{ctx}",
        "Do not ask for an Asset path, Metric, or topic that is already in this pack. "
        "Use default plant when focus is empty.",
        f"## Playbook observations\n{playbook.observations or '(none)'}",
    ]
    if playbook.kind in ("platform_health", "platform_map"):
        parts.append(
            "Answer this question using only the Playbook observations above. Do not call any tools."
        )
    return "\n\n".join(parts)


async def _history_messages(store: ConversationStore, conversation_id: str, subject: str) -> list[dict]:
    rows = await store.last_messages(conversation_id, subject, limit=20)
    return [{"role": row.role, "content": row.body} for row in rows]


async def _dispatch_tool(
    call: ToolCall,
    *,
    token: str,
    scope: Scope,
    sql_execute: SqlExecutor,
    graphql: GraphqlPost,
) -> str:
    try:
        if call.name == "query_asset_model":
            rows = await query_asset_model(str(call.arguments.get("sql", "")), scope=scope, execute=sql_execute)
        elif call.name == "query_historian":
            rows = await query_historian(str(call.arguments.get("sql", "")), scope=scope, execute=sql_execute)
        elif call.name == "query_live":
            topics = call.arguments.get("topics") or []
            rows = await query_live([str(t) for t in topics], token=token, client=graphql)
        elif call.name == "query_alarms":
            enabled = call.arguments.get("enabled_only", True)
            rows = await query_alarms(token=token, client=graphql, enabled_only=bool(enabled))
        elif call.name == "submit_answer":
            return json.dumps({"accepted": True})
        else:
            return json.dumps({"error": f"Unknown tool {call.name!r}."})
        return json.dumps(rows, default=str)
    except Exception as ex:  # noqa: BLE001 — tool errors go back to the model as strings
        return json.dumps({"error": str(ex)})


def _citations_from_submit(call: ToolCall) -> tuple[Citation, ...]:
    raw = call.arguments.get("citations") or []
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


async def run_turn(
    *,
    store: ConversationStore,
    conversation_id: str,
    subject: str,
    token: str,
    message: str,
    context: PageContext,
    scope: Scope,
    model: ModelClient,
    sql_execute: SqlExecutor,
    graphql: GraphqlPost,
    now,
    admin_roots: tuple[str, ...] = (),
) -> ChatResult:
    await store.append(conversation_id, subject, "user", message, (), now=now)

    kind = classify(message)
    pack = build_context_pack(
        context,
        is_admin=scope.unrestricted,
        root_paths=scope.root_paths,
        admin_roots=admin_roots,
    )
    playbook = await run_playbook(kind, pack, scope=scope, sql_execute=sql_execute, graphql=graphql, token=token)

    messages: list[dict[str, Any]] = [{"role": "system", "content": _build_system(pack, playbook)}]
    messages.extend(await _history_messages(store, conversation_id, subject))

    citations: tuple[Citation, ...] = ()
    final_text = ""

    for _ in range(MAX_TOOL_ROUNDS + 1):
        turn = await model.complete(messages, OPENAI_TOOLS)

        if turn.tool_calls:
            for call in turn.tool_calls:
                if call.name == "submit_answer":
                    final_text = str(call.arguments.get("text", ""))
                    citations = turn.citations or _citations_from_submit(call)
                    break
                result = await _dispatch_tool(
                    call,
                    token=token,
                    scope=scope,
                    sql_execute=sql_execute,
                    graphql=graphql,
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call.name,
                                "type": "function",
                                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                            }
                        ],
                    }
                )
                messages.append({"role": "tool", "tool_call_id": call.name, "content": result})
            if final_text:
                break
            continue

        if turn.text:
            final_text = turn.text
            citations = turn.citations
            break

    if not final_text:
        if kind == "platform_health":
            final_text = PLATFORM_HEALTH_REPLY
        else:
            final_text = "I could not finish that lookup. Try rephrasing or narrowing the Asset path."

    await store.append(conversation_id, subject, "assistant", final_text, citations, now=now)
    return ChatResult(text=final_text, citations=citations)
