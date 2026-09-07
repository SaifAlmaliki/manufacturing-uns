from uns_config import AuthConfig

from uns_factory_agent.wiring import _jwks


def test_jwks_cache_uses_internal_keycloak_url():
    cache = _jwks()
    assert cache._url == AuthConfig.jwks_url()
    assert "uns_keycloak" in cache._url
