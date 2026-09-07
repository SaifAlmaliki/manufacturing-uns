from __future__ import annotations

from typing import Any, Protocol

LIVE_QUERY = """
query CopilotLive($topics: [MQTTTopicInput!]!) {
  getUnsNodes(topics: $topics) { namespace nodeName nodeType }
}
""".strip()

ALARMS_QUERY = """
query CopilotAlarms($enabledOnly: Boolean!) {
  getAlertRules(enabledOnly: $enabledOnly) { id name topic severity enabled }
}
""".strip()


class GraphqlToolError(Exception):
    """GraphQL returned errors."""


class GraphqlPost(Protocol):
    async def post(self, query: str, variables: dict, token: str) -> dict: ...


def _extract_rows(payload: dict, field: str) -> list[dict]:
    errors = payload.get("errors")
    if errors:
        first = errors[0] if isinstance(errors, list) else errors
        message = first.get("message", str(first)) if isinstance(first, dict) else str(first)
        raise GraphqlToolError(message)
    data = payload.get("data") or {}
    rows = data.get(field)
    if rows is None:
        return []
    return list(rows)


async def query_live(topics: list[str], *, token: str, client: GraphqlPost) -> list[dict]:
    variables: dict[str, Any] = {"topics": [{"topic": topic} for topic in topics]}
    payload = await client.post(LIVE_QUERY, variables, token)
    return _extract_rows(payload, "getUnsNodes")


async def query_alarms(
    *,
    token: str,
    client: GraphqlPost,
    enabled_only: bool = True,
) -> list[dict]:
    payload = await client.post(ALARMS_QUERY, {"enabledOnly": enabled_only}, token)
    return _extract_rows(payload, "getAlertRules")
