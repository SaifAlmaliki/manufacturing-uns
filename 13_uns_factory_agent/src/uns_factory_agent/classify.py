from __future__ import annotations

from typing import Literal

Kind = Literal[
    "alarms_on_focus",
    "metric_vs_window",
    "publishers_on_path",
    "performance_rca",
    "plant_overview",
    "platform_map",
    "platform_health",
    "other",
]


def classify(message: str) -> Kind:
    text = " ".join(message.lower().split())
    if any(p in text for p in ("graphql down", "copilot unavailable", "keycloak down", "why is graphql")):
        return "platform_health"
    if any(p in text for p in ("how does historian", "access group", "what is this console", "how does this console")):
        return "platform_map"
    if "in alarm" in text:
        return "alarms_on_focus"
    if "eight hours" in text or "this metric" in text or "selected metric" in text:
        return "metric_vs_window"
    if "published" in text and ("last hour" in text or "this path" in text or "plant path" in text):
        return "publishers_on_path"
    if "lost performance" in text or ("why is" in text and "down" in text):
        return "performance_rca"
    if text in {"hi", "hello", "hey"} or "what's going on" in text or "whats going on" in text:
        return "plant_overview"
    if "p101" in text and ("week" in text or "performance" in text):
        return "performance_rca"
    return "other"
