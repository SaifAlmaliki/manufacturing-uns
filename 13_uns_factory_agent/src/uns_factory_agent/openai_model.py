from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from uns_factory_agent.chat import ModelClient, ModelTurn, ToolCall
from uns_factory_agent.conversations import Citation
from uns_factory_agent.config import FactoryAgentConfig


class OpenAIModelClient:
    def __init__(self, *, api_key: str, model: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model or FactoryAgentConfig.model

    async def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
        )
        choice = response.choices[0].message
        tool_calls: list[ToolCall] = []
        if choice.tool_calls:
            for call in choice.tool_calls:
                args: dict[str, Any] = {}
                if call.function.arguments:
                    args = json.loads(call.function.arguments)
                tool_calls.append(ToolCall(name=call.function.name, arguments=args))
                if call.function.name == "submit_answer":
                    citations = _citations_from_args(args)
                    return ModelTurn(
                        text=str(args.get("text", "")),
                        tool_calls=tuple(tool_calls),
                        citations=citations,
                    )
        return ModelTurn(
            text=choice.content,
            tool_calls=tuple(tool_calls),
            citations=(),
        )


def _citations_from_args(args: dict[str, Any]) -> tuple[Citation, ...]:
    raw = args.get("citations") or []
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
