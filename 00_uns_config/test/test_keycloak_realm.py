"""The realm is a committed file, so its contract is testable without Keycloak running."""

import json
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REALM_FILE = _REPO_ROOT / "conf" / "keycloak" / "realm.json"
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"

# The five names in ConsoleRole (07_uns_graphql/src/uns_graphql/type/alert_rule.py:70) and in
# UserRole (11_frontend/src/types/rbac.ts:5). A drift here silently drops roles in the console.
EXPECTED_ROLES = {"admin", "engineer", "operator", "auditor", "viewer"}

# Duplicate of uns_model.access.DEMO_SUBJECTS — keep in lockstep. Do not import
# uns_model from this package.
PINNED_DEMO_SUBJECTS = {
    "admin.user": "00000000-0000-4000-a000-000000000001",
    "engineer.user": "00000000-0000-4000-a000-000000000002",
    "operator.user": "00000000-0000-4000-a000-000000000003",
    "auditor.user": "00000000-0000-4000-a000-000000000004",
    "viewer.user": "00000000-0000-4000-a000-000000000005",
}


@pytest.fixture(scope="module")
def realm() -> dict:
    return json.loads(_REALM_FILE.read_text(encoding="utf-8"))


def _client(realm: dict, client_id: str) -> dict:
    for client in realm["clients"]:
        if client["clientId"] == client_id:
            return client
    raise AssertionError(f"realm.json has no client {client_id!r}")


def test_realm_declares_exactly_the_five_console_roles(realm: dict):
    names = {role["name"] for role in realm["roles"]["realm"]}
    assert names == EXPECTED_ROLES


def test_console_client_is_public_and_requires_pkce(realm: dict):
    console = _client(realm, "uns-console")
    assert console["publicClient"] is True
    assert "secret" not in console
    # A static bundle cannot keep a secret, so PKCE is the whole security of the flow.
    assert console["attributes"]["pkce.code.challenge.method"] == "S256"
    assert console["standardFlowEnabled"] is True
    # Implicit puts the token in the URL fragment. Not an option (spec finding 5).
    assert console["implicitFlowEnabled"] is False
    assert console["directAccessGrantsEnabled"] is False


def test_console_client_accepts_both_console_origins(realm: dict):
    console = _client(realm, "uns-console")
    redirects = set(console["redirectUris"])
    assert "http://localhost:8088/*" in redirects
    assert "http://localhost:5173/*" in redirects


def test_grafana_client_is_confidential_and_takes_its_secret_from_the_environment(realm: dict):
    grafana = _client(realm, "uns-grafana")
    assert grafana["publicClient"] is False
    assert grafana["secret"] == "${UNS_KEYCLOAK_GRAFANA_CLIENT_SECRET}"


def test_development_users_have_pinned_subjects(realm: dict):
    ids = {user["username"]: user["id"] for user in realm["users"]}
    assert ids == PINNED_DEMO_SUBJECTS


def test_every_development_user_holds_exactly_one_of_the_five_roles(realm: dict):
    granted = {}
    for user in realm["users"]:
        roles = set(user["realmRoles"])
        assert len(roles) == 1, f"{user['username']} holds {roles}"
        granted[user["username"]] = roles.pop()
    assert set(granted.values()) == EXPECTED_ROLES


def test_settings_yaml_points_at_this_realm():
    settings = yaml.safe_load((_REPO_ROOT / "conf" / "settings.yaml").read_text(encoding="utf-8"))
    auth = settings["default"]["auth"]
    assert auth["realm"] == "uns"
    assert auth["console_client_id"] == "uns-console"
    assert auth["issuer"].endswith("/auth/realms/uns")


def test_compose_imports_the_realm_and_does_not_publish_a_second_port():
    compose = yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))
    keycloak = compose["services"]["uns_keycloak"]
    assert "--import-realm" in keycloak["command"]
    mounted = [v for v in keycloak["volumes"] if v.startswith("./conf/keycloak")]
    assert mounted, "the realm export has to be mounted for --import-realm to see it"
    # The console proxies /auth on its own origin, which is what makes Grafana's cookie
    # same-origin (spec section 10). A published 8080 would invite a second issuer URL.
    assert "ports" not in keycloak


def test_grafana_is_no_longer_anonymous():
    compose = yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))
    env = compose["services"]["uns_grafana"]["environment"]
    # Explicit "false", not merely absent: the file states the decision, and an absent key
    # would leave Grafana's own default in charge.
    assert env.get("GF_AUTH_ANONYMOUS_ENABLED") == "false"
    assert "GF_AUTH_ANONYMOUS_ORG_ROLE" not in env
    assert env["GF_AUTH_GENERIC_OAUTH_ENABLED"] == "true"
    # Removing anonymity without keeping embedding on breaks all three console embeds.
    assert env["GF_SECURITY_ALLOW_EMBEDDING"] == "true"


def test_the_admin_role_can_read_the_user_directory(realm: dict):
    """
    The console lists realm members with the signed-in admin's own token. Without this
    composite the directory screen can only ever show its cannot-reach-the-realm state.
    """
    admin = next(role for role in realm["roles"]["realm"] if role["name"] == "admin")
    assert admin["composite"] is True
    granted = admin["composites"]["client"]["realm-management"]
    assert "view-users" in granted


def test_no_role_in_this_realm_can_manage_users(realm: dict):
    """
    Reading the directory is the whole feature. A browser token that could create realm
    users would be a far larger thing to leak, and this console never needs it.
    """
    for role in realm["roles"]["realm"]:
        granted = role.get("composites", {}).get("client", {}).get("realm-management", [])
        assert "manage-users" not in granted, role["name"]
        assert "realm-admin" not in granted, role["name"]
