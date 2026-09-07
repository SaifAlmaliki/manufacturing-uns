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

#: Verbs that describe an Asset getting worse over time. Paired with a window word below
#: so a bare "degrading" (no timeframe) does not hijack every vague complaint.
_PERFORMANCE_VERBS = ("degrad", "declin", "lost", "losing", "slower", "slowing", "worse")
_PERFORMANCE_WINDOWS = ("week", "month")

#: Narrow, deliberately literal phrasings for "explain the console/platform itself" —
#: broader words like a bare "access group" also show up in ordinary data questions
#: ("what's in alarm in my access group?"), which must still get the data playbook.
_PLATFORM_MAP_PHRASES = (
    "what is an access group",
    "how does historian",
    "what is this console",
    "how does this console",
)


def classify(message: str) -> Kind:
    text = " ".join(message.lower().split())

    if any(p in text for p in ("graphql down", "copilot unavailable", "keycloak down", "why is graphql")):
        return "platform_health"

    # Data intents are checked before the platform_map probe: a question that happens to
    # mention "access group" alongside a data word (alarms, a metric, a path, performance)
    # must still run the data playbook, not the static console map (I5).
    if "in alarm" in text:
        return "alarms_on_focus"
    if "eight hours" in text or "this metric" in text or "selected metric" in text:
        return "metric_vs_window"
    if "published" in text and ("last hour" in text or "this path" in text or "plant path" in text):
        return "publishers_on_path"
    if (
        "lost performance" in text
        or (any(v in text for v in _PERFORMANCE_VERBS) and any(w in text for w in _PERFORMANCE_WINDOWS))
        or ("why is" in text and "down" in text)
    ):
        return "performance_rca"

    if any(p in text for p in _PLATFORM_MAP_PHRASES):
        return "platform_map"

    if text in {"hi", "hello", "hey"} or "what's going on" in text or "whats going on" in text:
        return "plant_overview"

    return "other"
