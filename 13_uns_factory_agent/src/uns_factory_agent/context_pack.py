from __future__ import annotations

from dataclasses import dataclass

from uns_factory_agent.chat import PageContext


@dataclass(frozen=True, slots=True)
class Focus:
    asset_path: str
    metric_key: str
    alarm_topic: str


@dataclass(frozen=True, slots=True)
class ContextPack:
    route: str
    focus: Focus
    default_plant: tuple[str, ...]
    page_hint: str
    unrestricted: bool


def page_hint(route: str) -> str:
    lowered = route.lower()
    if "alert" in lowered:
        return "alarms"
    if "condition" in lowered:
        return "condition_monitoring"
    if "hierarch" in lowered:
        return "hierarchy"
    return "plant"


def resolve_paths(pack: ContextPack) -> tuple[str, ...]:
    focus = pack.focus
    if focus.asset_path:
        return (focus.asset_path,)
    if focus.alarm_topic:
        return (focus.alarm_topic,)
    if focus.metric_key:
        return (focus.metric_key,)
    return pack.default_plant


def build_context_pack(
    page: PageContext,
    *,
    is_admin: bool,
    root_paths: frozenset[str],
    admin_roots: tuple[str, ...] = (),
) -> ContextPack:
    if is_admin:
        default = admin_roots
    else:
        default = tuple(sorted(root_paths))
    return ContextPack(
        route=page.route,
        focus=Focus(page.asset_path, page.metric_key, page.alarm_topic),
        default_plant=default,
        page_hint=page_hint(page.route),
        unrestricted=is_admin,
    )
