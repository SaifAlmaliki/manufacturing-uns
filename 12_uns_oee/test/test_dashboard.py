"""What the OEE dashboard is not allowed to do.

Grafana fails quietly. A panel naming a datasource uid that provisioning never declared
renders "Datasource not found" in one panel and nothing anywhere else; a panel missing
`$__timeFilter` works perfectly until the table has a year in it. Both are found by a
person looking at a screen, which is the worst place to find them.
"""

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAFANA = REPO_ROOT / "08_uns_observability" / "grafana"
DASHBOARD_DIR = GRAFANA / "dashboards"
OEE_DASHBOARD = DASHBOARD_DIR / "oee.json"
DATASOURCES = GRAFANA / "provisioning" / "datasources" / "datasources.yaml.template"


def _panels(dashboard: dict) -> list[dict]:
    """Flattened, because a collapsed row nests its panels inside itself."""
    panels = []
    for panel in dashboard.get("panels", []):
        panels.append(panel)
        panels.extend(panel.get("panels", []))
    return panels


def _queries(panel: dict) -> list[str]:
    return [target["rawSql"] for target in panel.get("targets", []) if "rawSql" in target]


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return json.loads(OEE_DASHBOARD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def declared_uids() -> set[str]:
    template = yaml.safe_load(DATASOURCES.read_text(encoding="utf-8"))
    return {source["uid"] for source in template["datasources"] if "uid" in source}


@pytest.mark.parametrize("path", sorted(DASHBOARD_DIR.glob("*.json")), ids=lambda path: path.name)
def test_every_dashboard_names_a_declared_datasource(path: Path, declared_uids: set[str]):
    """
    Applies to all three dashboards, not only the new one: two of them referenced uids
    that provisioning never declared, which is why the datasource template changed here.
    """
    body = json.loads(path.read_text(encoding="utf-8"))
    named = {
        panel["datasource"]["uid"]
        for panel in _panels(body)
        if isinstance(panel.get("datasource"), dict) and "uid" in panel["datasource"]
    }
    assert named <= declared_uids, f"{path.name} names undeclared datasource uid(s): {named - declared_uids}"


def test_no_panel_recomputes_oee_from_raw_samples(dashboard: dict):
    """
    The engine's numbers or nothing. A panel doing its own arithmetic over `uns_metrics`
    would be a second implementation of the formulas, free to disagree with the value
    already published to `<line>/KPI/ShiftOee`.
    """
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "uns_metrics" not in query, f"panel {panel.get('title')!r} reads uns_metrics"


def test_every_query_is_bounded_by_the_dashboard_time_range(dashboard: dict):
    """Without $__timeFilter a panel scans every shift ever computed."""
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "$__timeFilter" in query, f"panel {panel.get('title')!r} has an unbounded query"


def test_the_trend_is_plotted_against_shift_start(dashboard: dict):
    """
    Not `computed_at`: a restated August shift has to move where the shift was, not where
    the recomputation happened.
    """
    trend = next(panel for panel in _panels(dashboard) if panel["type"] == "timeseries")
    query = _queries(trend)[0]
    assert "$__timeFilter(shift_start)" in query
    assert "computed_at" not in query


def test_every_query_is_filtered_to_the_selected_asset(dashboard: dict):
    """A dashboard showing two lines' OEE on one axis is a dashboard showing neither."""
    for panel in _panels(dashboard):
        for query in _queries(panel):
            assert "$asset" in query, f"panel {panel.get('title')!r} ignores the asset variable"


def test_the_asset_variable_lists_only_assets_oee_is_computed_for(dashboard: dict):
    variable = next(item for item in dashboard["templating"]["list"] if item["name"] == "asset")
    assert variable["type"] == "query"
    assert "model.oee_unit" in variable["query"]
    assert "is_active" in variable["query"]


def test_the_waterfall_walks_loading_time_down_to_valuable_time(dashboard: dict):
    """
    Spec section 15 asks for a waterfall from Loading Time through the three losses. Its
    four stages have to descend in that order, because a waterfall whose bars are not
    successive remainders is just four unrelated bars.
    """
    waterfall = next(panel for panel in _panels(dashboard) if panel["title"] == "Loss waterfall")
    query = _queries(waterfall)[0]
    positions = [
        query.index(stage) for stage in ("'Loading time'", "'Run time'", "'Net run time'", "'Valuable time'")
    ]
    assert positions == sorted(positions)
    # Each stage is the previous one less its loss, taken from the stored columns - not
    # recomputed, and not a fifth factor invented in SQL.
    assert "run_time_s * coalesce(performance, 0) * coalesce(quality, 0)" in query


def test_panel_ids_are_unique(dashboard: dict):
    """Duplicated ids make Grafana silently drop a panel on import."""
    ids = [panel["id"] for panel in _panels(dashboard)]
    assert len(ids) == len(set(ids))


def test_the_dashboard_is_identified_and_tagged(dashboard: dict):
    assert dashboard["uid"] == "uns-oee"
    assert dashboard["title"] == "OEE"
    assert "oee" in dashboard["tags"]


def test_the_unusable_shifts_panel_is_a_worklist(dashboard: dict):
    panel = next(item for item in _panels(dashboard) if item["title"] == "Unusable shifts")
    query = _queries(panel)[0]
    assert "shift_start" in query
    assert "shift_label" in query
    assert "status" in query
    assert "GROUP BY" not in query


COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
NGINX_FILE = REPO_ROOT / "11_frontend" / "nginx.conf"
VITE_FILE = REPO_ROOT / "11_frontend" / "vite.config.ts"
SYSTEM_HEALTH = REPO_ROOT / "11_frontend" / "src" / "components" / "system" / "SystemHealthView.tsx"
GRAFANA_EMBED = REPO_ROOT / "11_frontend" / "src" / "components" / "common" / "GrafanaEmbed.tsx"
EXPLORE_VIEW = REPO_ROOT / "11_frontend" / "src" / "components" / "explore" / "ExploreView.tsx"
PAYLOAD_INSPECTOR = REPO_ROOT / "11_frontend" / "src" / "components" / "home" / "PayloadInspector.tsx"
SIMULATOR_DIAGNOSTICS = (
    REPO_ROOT / "11_frontend" / "src" / "components" / "simulator" / "SimulatorDiagnosticsPanel.tsx"
)
PROCESS_DASHBOARD = DASHBOARD_DIR / "process-visualization.json"
PLATFORM_DASHBOARD = DASHBOARD_DIR / "platform-observability.json"
DASHBOARD_UIDS = (
    "uns-platform-observability",
    "uns-process-visualization",
    "uns-oee",
)


def test_grafana_is_reached_through_the_console_not_host_port_3000():
    """Publishing 3000 fails when anything else on the host already bound it."""
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    grafana = compose["services"]["uns_grafana"]
    assert "ports" not in grafana
    assert grafana["environment"]["GF_SERVER_SERVE_FROM_SUB_PATH"] == "true"
    assert grafana["environment"]["GF_SECURITY_ALLOW_EMBEDDING"] == "true"
    assert "uns_grafana" in compose["services"]["uns_frontend"]["depends_on"]


def test_grafana_does_not_need_envsubst():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    grafana = compose["services"]["uns_grafana"]
    assert grafana.get("entrypoint") in (None, [])
    mounts = " ".join(grafana["volumes"])
    assert "datasources.yaml" in mounts


def test_the_console_proxies_grafana_before_the_spa_fallback():
    nginx = NGINX_FILE.read_text(encoding="utf-8")
    assert "location /grafana" in nginx
    assert nginx.index("location /grafana") < nginx.index("location / {")
    vite = VITE_FILE.read_text(encoding="utf-8")
    assert "'/grafana'" in vite or '"/grafana"' in vite


def test_the_console_embeds_the_three_provisioned_dashboards():
    sources = GRAFANA_EMBED.read_text(encoding="utf-8") + SYSTEM_HEALTH.read_text(encoding="utf-8")
    for uid in DASHBOARD_UIDS:
        assert uid in sources, f"console does not embed dashboard uid {uid}"


def test_every_sql_panel_is_bounded_by_the_dashboard_time_range():
    """Process Visualization can scan uns_metrics_1m the same way OEE can scan every shift."""
    for path in DASHBOARD_DIR.glob("*.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        for panel in _panels(body):
            for query in _queries(panel):
                assert "$__timeFilter" in query, f"{path.name} panel {panel.get('title')!r} is unbounded"


def test_process_visualization_shows_the_plant_the_simulator_publishes():
    """
    One Temperature timeseries is not Process Visualization. The simulator publishes
    production, power, pressure and temperature; the dashboard has to name those series
    or the System and Historian embeds look empty next to a busy broker.
    """
    body = json.loads(PROCESS_DASHBOARD.read_text(encoding="utf-8"))
    sql = "\n".join(q for panel in _panels(body) for q in _queries(panel))
    titles = [panel.get("title") for panel in _panels(body)]
    assert len([t for t in titles if t]) >= 6
    assert "metric_name = 'value'" in sql
    assert "metric_name = 'ProductionRate'" not in sql
    for metric in ("ThroughputTph", "ActivePower"):
        assert f"%/{metric}" in sql, f"process dashboard never filters topics for {metric}"
    assert "uns_metrics_1m_enriched" in sql
    assert "ShiftOee" not in sql
    assert "'Oee'" not in sql
    assert any(panel.get("title") == "All simulator process values" for panel in _panels(body))
    metric_var = next(item for item in body["templating"]["list"] if item["name"] == "metric")
    assert metric_var["current"]["value"] != "Temperature"


def test_platform_observability_covers_the_scraped_jobs():
    """Throughput plus a lump of failures is not a health view of this stack."""
    body = json.loads(PLATFORM_DASHBOARD.read_text(encoding="utf-8"))
    exprs = " ".join(
        target.get("expr", "")
        for panel in _panels(body)
        for target in panel.get("targets", [])
    )
    titles = [panel.get("title") for panel in _panels(body)]
    assert len([t for t in titles if t]) >= 6
    for needle in (
        "uns_historian_messages_received_total",
        "uns_historian_persist_duration_seconds",
        "uns_historian_persist_failure_total",
        "uns_simulator_messages_published",
        "uns_simulator_devices_connected",
        "uns_simulator_signal_value",
        "uns_oee_db_up",
        'up{',
    ):
        assert needle in exprs, f"platform dashboard is missing {needle}"
    assert "reason" in exprs


def test_console_charts_go_through_grafana_not_a_hand_rolled_svg():
    """ADR-0002: GraphQL does not serve bucketed trends. The console must not fake them."""
    embed = GRAFANA_EMBED.read_text(encoding="utf-8")
    assert "vars" in embed
    explore = EXPLORE_VIEW.read_text(encoding="utf-8")
    assert "GrafanaEmbed" in explore
    assert "HistorianTrendChart" not in explore
    inspector = PAYLOAD_INSPECTOR.read_text(encoding="utf-8")
    assert "GrafanaEmbed" in inspector
    diagnostics = SIMULATOR_DIAGNOSTICS.read_text(encoding="utf-8")
    assert "GrafanaEmbed" in diagnostics
