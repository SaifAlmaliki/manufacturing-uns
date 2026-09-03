"""Spec test 1: no bearer token, no answer - on every operation.

Enumerated rather than sampled. A gate that covers five of six mutations is not a gate, and
the missing one is always the one nobody listed.
"""

import pytest
from fastapi.testclient import TestClient

from uns_graphql.auth.context import use_signing_keys
from uns_graphql.auth.jwks import JwksCache
from uns_graphql.uns_graphql_app import UNSGraphql

from .keys import jwks_document, make_key

REALM_KEY = make_key("gate-key")

OPERATIONS = [
    # Queries. Every one of them, per success criterion 2.
    ("getUnsNodes", '{ getUnsNodes(topics: ["a/b"]) { topic } }'),
    ("getHistoricEvents",
     '{ getHistoricEventsByPublishers(publishers: ["client-1"]) { topic } }'),
    ("getAssets", "{ getAssets { path } }"),
    ("getAlertRules", "{ getAlertRules { id } }"),
    # The OEE query's datetime arguments are published as `from`/`to` (strawberry.argument
    # renames them), and the field is oeeShiftResults, not getShiftResults.
    ("oeeShiftResults",
     '{ oeeShiftResults(assetPath: "a", from: "2026-01-01T00:00:00Z", '
     'to: "2026-01-01T08:00:00Z") { shiftStart } }'),
    # All six mutations, per finding 3.
    ("saveAlertRule", 'mutation { saveAlertRule(rule: {id: "r", name: "n", severity: '
                      'CRITICAL, category: TEMPERATURE, topic: "a/b", metricField: "value", '
                      'condition: GREATER_THAN, thresholdValue: 1.0}) { id } }'),
    ("saveAlertRules", "mutation { saveAlertRules(rules: []) { id } }"),
    ("deleteAlertRule", 'mutation { deleteAlertRule(id: "r") }'),
    ("setAlertRuleEnabled", 'mutation { setAlertRuleEnabled(id: "r", enabled: false) { id } }'),
    ("recordAlertRuleEvaluation",
     'mutation { recordAlertRuleEvaluation(id: "r", triggered: true) { id } }'),
    ("assignDowntimeReason",
     'mutation { assignDowntimeReason(eventId: "1", reasonCode: "MECH_FAULT") { id } }'),
]


@pytest.fixture(autouse=True)
def realm_keys():
    document = jwks_document(REALM_KEY)

    async def fetch(_url: str) -> dict:
        return document

    use_signing_keys(JwksCache("http://keys.test/certs", fetch=fetch))
    yield
    use_signing_keys(None)


@pytest.mark.parametrize(("label", "document"), OPERATIONS, ids=[name for name, _ in OPERATIONS])
def test_no_token_is_rejected(label: str, document: str):  # noqa: ARG001
    client = TestClient(UNSGraphql.app)

    response = client.post("/graphql", json={"query": document})

    assert response.status_code == 401


@pytest.mark.parametrize(("label", "document"), OPERATIONS, ids=[name for name, _ in OPERATIONS])
def test_a_garbage_token_is_rejected(label: str, document: str):  # noqa: ARG001
    client = TestClient(UNSGraphql.app)

    response = client.post(
        "/graphql",
        json={"query": document},
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert response.status_code == 401


def test_a_valid_token_gets_past_the_gate():
    """
    The gate opens. What happens next is a resolver reaching a database this test has none
    of, so the assertion is only that the answer is no longer 401 - which is precisely what
    this task is responsible for.
    """
    client = TestClient(UNSGraphql.app)
    token = REALM_KEY.mint(roles=["viewer"])

    response = client.post(
        "/graphql",
        json={"query": "{ __typename }"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"__typename": "Query"}


def test_the_preflight_permits_the_authorization_header():
    """
    allow_headers=["*"] at uns_graphql_app.py already covers this. The test exists
    because if it ever stops covering it, every console request fails in the browser and
    passes in every test that does not go through CORS.
    """
    from uns_graphql.graphql_config import PlatformConfig

    client = TestClient(UNSGraphql.app)
    response = client.options(
        "/graphql",
        headers={
            "Origin": PlatformConfig.frontend_compose_origin(),
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    allowed = (response.headers.get("access-control-allow-headers") or "").lower()
    assert "authorization" in allowed or allowed == "*"
