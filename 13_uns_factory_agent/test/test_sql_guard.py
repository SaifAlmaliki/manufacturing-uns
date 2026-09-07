import pytest
from uns_factory_agent.sql_guard import SQLGuardError, guard_select


def test_accepts_a_select_on_uns_metrics():
    sql = "SELECT topic, value_double FROM uns_metrics WHERE topic LIKE 'Acme%' LIMIT 10"
    assert guard_select(sql) == sql


def test_accepts_qualified_model_asset():
    sql = "SELECT path, name FROM model.asset WHERE level = 'MACHINE'"
    assert guard_select(sql) == sql


def test_rejects_insert():
    with pytest.raises(SQLGuardError, match="SELECT"):
        guard_select("INSERT INTO uns_metrics (topic) VALUES ('x')")


def test_rejects_update():
    with pytest.raises(SQLGuardError, match="SELECT"):
        guard_select("UPDATE model.asset SET name = 'x'")


def test_rejects_delete():
    with pytest.raises(SQLGuardError, match="SELECT"):
        guard_select("DELETE FROM model.asset")


def test_rejects_second_statement():
    with pytest.raises(SQLGuardError, match="one statement"):
        guard_select("SELECT 1 FROM uns_metrics; DELETE FROM uns_metrics")


def test_rejects_unknown_table():
    with pytest.raises(SQLGuardError, match="allowlist"):
        guard_select("SELECT * FROM pg_stat_activity")


def test_rejects_copilot_schema():
    with pytest.raises(SQLGuardError, match="allowlist"):
        guard_select("SELECT * FROM copilot.conversation")


def test_accepts_downtime_joined_to_asset_via_oee_unit():
    sql = (
        "SELECT a.path AS topic, d.started_at, d.ended_at, d.reason_code\n"
        "FROM oee.downtime_event d\n"
        "JOIN model.oee_unit u ON u.id = d.oee_unit_id\n"
        "JOIN model.asset a ON a.id = u.asset_id"
    )
    assert guard_select(sql) == sql
