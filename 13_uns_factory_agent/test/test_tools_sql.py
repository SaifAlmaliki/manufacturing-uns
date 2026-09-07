import pytest
from uns_factory_agent.scope_sql import Scope
from uns_factory_agent.sql_guard import SQLGuardError
from uns_factory_agent.tools_sql import query_historian


class FakeExec:
    def __init__(self):
        self.sql = None
        self.params = None

    async def fetch(self, sql, params):
        self.sql = sql
        self.params = params
        return [{"topic": "Acme/Plant/Filtration/L1/Dryer"}]


@pytest.mark.asyncio
async def test_historian_wraps_and_runs():
    exe = FakeExec()
    rows = await query_historian(
        "SELECT topic FROM uns_metrics",
        scope=Scope(unrestricted=False, root_paths=frozenset({"Acme/Plant/Filtration"})),
        execute=exe,
    )
    assert rows[0]["topic"].endswith("Dryer")
    assert "p0" in exe.params


@pytest.mark.asyncio
async def test_insert_never_reaches_execute():
    exe = FakeExec()
    with pytest.raises(SQLGuardError):
        await query_historian(
            "INSERT INTO uns_metrics (topic) VALUES ('x')",
            scope=Scope(True, frozenset()),
            execute=exe,
        )
    assert exe.sql is None
