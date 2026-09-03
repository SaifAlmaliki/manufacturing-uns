"""The realm's identity is read from conf/settings.yaml, not retyped per module."""

from uns_config import AuthConfig


def test_issuer_is_the_realm_under_the_console_origin():
    # The console proxies /auth, so the issuer is the console's origin. A token minted with
    # any other issuer is rejected by the GraphQL service, so this string is a contract.
    assert AuthConfig.issuer == "http://localhost:8088/auth/realms/uns"


def test_jwks_url_is_built_from_the_internal_base_url():
    # The service resolves Keycloak by container name: its validation must not depend on the
    # frontend container being up to serve the proxy.
    assert AuthConfig.jwks_url() == (
        "http://uns_keycloak:8080/auth/realms/uns/protocol/openid-connect/certs"
    )


def test_discovery_url_is_browser_facing():
    assert AuthConfig.discovery_url() == (
        "http://localhost:8088/auth/realms/uns/.well-known/openid-configuration"
    )


def test_the_client_ids_match_the_realm_export():
    assert AuthConfig.console_client_id == "uns-console"
    assert AuthConfig.grafana_client_id == "uns-grafana"


def test_audience_matches_the_console_client():
    # The audience mapper in conf/keycloak/realm.json puts this in the access token's `aud`.
    assert AuthConfig.audience == "uns-console"


def test_there_is_leeway_on_expiry():
    # A laptop clock is not the realm's clock, and a plant floor PC's clock is nobody's.
    assert AuthConfig.leeway_seconds > 0
