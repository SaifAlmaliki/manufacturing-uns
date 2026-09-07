"""Static replies for the platform_map and platform_health playbook kinds."""

from __future__ import annotations

CONSOLE_MAP = """
Console pages: Hierarchy (Asset tree), Condition Monitoring (live Metrics), Alarms (Alert Rules), historian jumps from citations.
Stores: Postgres schema model = what Assets and Metric Definitions exist. Timescale uns_metrics and oee.downtime_event = history. GraphQL = live UNS Nodes and Alert Rules.
Access Groups hide plant rows. You only see your own Copilot threads.
I am read-only. I do not ack alarms, edit Alert Rules, or change setpoints.
I do not diagnose whether GraphQL, Copilot, or Keycloak is down.
""".strip()

PLATFORM_HEALTH_REPLY = (
    "I don't diagnose service health in this slice. "
    "I can look up plant data and how the console stores it."
)
