from __future__ import annotations


def _placeholder(key: str) -> bool:
    stripped = key.strip()
    return not stripped or stripped.startswith("#<enter")


def health_payload(*, openai_key: str, db_ok: bool, graphql_ok: bool = True) -> dict:
    if _placeholder(openai_key):
        return {"status": "degraded", "reason": "openai_key_missing"}
    if not db_ok:
        return {"status": "degraded", "reason": "database_unreachable"}
    if not graphql_ok:
        return {"status": "degraded", "reason": "graphql_unreachable"}
    return {"status": "ok"}


def main() -> None:
    import asyncio
    import sys

    from uns_factory_agent.wiring import check_health

    result = asyncio.run(check_health())
    if result.get("status") != "ok":
        sys.exit(1)
