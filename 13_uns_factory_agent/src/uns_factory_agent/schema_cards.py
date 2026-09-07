"""Curated schema cards for the four data tools."""

from __future__ import annotations

SCHEMA_CARDS: dict[str, str] = {
    "query_asset_model": """
Asset Model (PostgreSQL schema `model`):
- model.asset(path, segment, display_name, level) — ISA-95 hierarchy. path is the Asset path (e.g. Acme/Plant/Filtration/P101). There is no `name` column: use COALESCE(display_name, segment) AS name for a human-readable name.
- model.metric_definition(asset_id, metric_key, display_name, unit_of_measure) — Metric definitions bound to Assets. Column is `metric_key`, not `key`; `unit_of_measure`, not `unit`.
- model.access_group, model.access_group_member, model.access_group_root — Access Groups (read-only).

Use path LIKE patterns to find Assets by name or tag (e.g. P101, Pump).
""".strip(),
    "query_historian": """
Historian (Timescale hypertable `uns_metrics`):
- uns_metrics(time, topic, metric_name, value_double, value_text) — value_double holds numbers, value_text holds strings/booleans as text; exactly one of the two is set per row. There is no value_bool, value_string, or value_json column.
- topic follows the UNS path (e.g. Acme/Plant/Filtration/P101/Flow).

Last shift: the previous OEE shift window when `oee` shift rows exist; otherwise the last 8 hours.
Use time ranges and aggregates (avg, min, max) to spot declining performance.
Also: oee.downtime_event for Historic Events / downtime on a line or Asset — it has no asset_path column, join via model.oee_unit to model.asset.
""".strip(),
    "query_live": """
Live UNS Nodes via GraphQL getUnsNodes(topics).
Pass MQTT topic filters (e.g. Acme/Plant/Filtration/P101/#) to read current published values.
""".strip(),
    "query_alarms": """
Alert Rules via GraphQL getAlertRules(enabledOnly).
Returns id, name, topic, severity, enabled for active plant alarms.
""".strip(),
}
