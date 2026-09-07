from uns_factory_agent.health import health_payload


def test_missing_key_is_degraded():
    body = health_payload(openai_key="#<enter the OpenAI API key>", db_ok=True)
    assert body["status"] == "degraded"
    assert body["reason"] == "openai_key_missing"


def test_ok_when_key_and_db_present():
    assert health_payload(openai_key="sk-test", db_ok=True)["status"] == "ok"


def test_graphql_unreachable_is_degraded():
    body = health_payload(openai_key="sk-test", db_ok=True, graphql_ok=False)
    assert body["status"] == "degraded"
    assert body["reason"] == "graphql_unreachable"
