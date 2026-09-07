import pytest
from uns_factory_agent.tools_graphql import query_alarms, query_live


class FakeGql:
    def __init__(self, payload):
        self.payload = payload
        self.token = None
        self.query = None

    async def post(self, query, variables, token):
        self.token = token
        self.query = query
        return self.payload


@pytest.mark.asyncio
async def test_live_forwards_the_caller_token():
    fake = FakeGql({"data": {"getUnsNodes": [{"namespace": "Acme/Plant", "nodeName": "Plant"}]}})
    rows = await query_live(["Acme/#"], token="caller.jwt", client=fake)
    assert fake.token == "caller.jwt"
    assert "getUnsNodes" in fake.query
    assert rows[0]["namespace"] == "Acme/Plant"


@pytest.mark.asyncio
async def test_alarms_forwards_the_caller_token():
    fake = FakeGql({"data": {"getAlertRules": [{"id": "r1", "topic": "Acme/Plant/L1", "severity": "HIGH"}]}})
    rows = await query_alarms(token="caller.jwt", client=fake)
    assert fake.token == "caller.jwt"
    assert rows[0]["id"] == "r1"
