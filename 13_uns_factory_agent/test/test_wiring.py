import pytest
from uns_config import AuthConfig

from uns_factory_agent.playbook import ADMIN_ROOTS_SQL
from uns_factory_agent.wiring import _admin_roots, _jwks


def test_jwks_cache_uses_internal_keycloak_url():
    cache = _jwks()
    assert cache._url == AuthConfig.jwks_url()
    assert "uns_keycloak" in cache._url


class FakeExec:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch(self, sql, params):
        self.calls.append((sql, params))
        return list(self.rows)


@pytest.mark.asyncio
async def test_admin_roots_returns_paths_from_admin_roots_sql():
    execu = FakeExec([{"path": "Acme"}, {"path": "Acme/Site1"}])
    roots = await _admin_roots(execu)
    assert roots == ("Acme", "Acme/Site1")
    assert execu.calls[0][0] == ADMIN_ROOTS_SQL


@pytest.mark.asyncio
async def test_admin_roots_ignores_rows_without_path():
    execu = FakeExec([{"other": 1}, {"path": "Acme"}])
    roots = await _admin_roots(execu)
    assert roots == ("Acme",)


@pytest.mark.asyncio
async def test_admin_roots_empty_when_no_rows():
    roots = await _admin_roots(FakeExec([]))
    assert roots == ()


def test_load_scope_and_chat_handler_both_use_the_admin_roots_helper():
    import inspect

    from uns_factory_agent import wiring

    source = inspect.getsource(wiring.create_production_app)
    # ADMIN_ROOTS_SQL itself is only referenced once, inside `_admin_roots` (module level,
    # outside this function's source) — `create_production_app` calls the helper instead
    # of re-running the query inline at either call site (I7/I9).
    assert "ADMIN_ROOTS_SQL" not in source
    assert source.count("_admin_roots(sql_execute)") == 2
