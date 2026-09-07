from uns_factory_agent.scope_sql import Scope, covers_sql, wrap_select


def test_admin_is_unscoped():
    scoped = wrap_select(
        "SELECT topic FROM uns_metrics",
        Scope(unrestricted=True, root_paths=frozenset()),
        path_column="topic",
    )
    assert scoped.sql == "SELECT topic FROM uns_metrics"
    assert scoped.params == {}


def test_operator_gains_a_prefix_filter():
    scoped = wrap_select(
        "SELECT topic FROM uns_metrics",
        Scope(unrestricted=False, root_paths=frozenset({"Acme/Plant/Filtration"})),
        path_column="topic",
    )
    assert "_scoped" in scoped.sql
    assert "left(topic" in scoped.sql
    assert scoped.params["p0"] == "Acme/Plant/Filtration"


def test_empty_roots_match_nothing():
    scoped = wrap_select(
        "SELECT path FROM model.asset",
        Scope(unrestricted=False, root_paths=frozenset()),
        path_column="path",
    )
    assert "where false" in scoped.sql.lower()


def test_covers_sql_does_not_use_like():
    clause = covers_sql("topic", "p0")
    assert "LIKE" not in clause.upper()
    assert "left(topic" in clause
