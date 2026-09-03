"""Platform-wide settings shared across modules (instance, URLs, application names)."""

from __future__ import annotations

from uns_config.loader import get_settings

_settings = get_settings("default")


class PlatformConfig:
    """Client-specific platform identity and URL settings."""

    instance_name: str = _settings.get("platform.instance_name", "default")
    organization_name: str = _settings.get("platform.organization_name", "")
    display_name: str = _settings.get("platform.display_name", "Unified Namespace")

    graphql_host: str = _settings.get("urls.graphql_host", "localhost")
    graphql_port: int = int(_settings.get("urls.graphql_port", 8000))
    graphql_path: str = _settings.get("urls.graphql_path", "/graphql")
    cors_origins: list[str] = list(_settings.get("urls.cors_origins", []))

    frontend_dev_port: int = int(
        _settings.get("applications.frontend.dev_port", _settings.get("urls.frontend_dev_port", 5173))
    )
    frontend_compose_port: int = int(
        _settings.get("applications.frontend.compose_port", _settings.get("urls.frontend_compose_port", 8088))
    )

    @classmethod
    def graphql_url(cls) -> str:
        return f"http://{cls.graphql_host}:{cls.graphql_port}{cls.graphql_path}"

    @classmethod
    def frontend_dev_origin(cls) -> str:
        return f"http://localhost:{cls.frontend_dev_port}"

    @classmethod
    def frontend_compose_origin(cls) -> str:
        return f"http://localhost:{cls.frontend_compose_port}"


class AuthConfig:
    """Where the realm is, for everything that has to reach it.

    Two base URLs, and the difference matters. `base_url` is what a browser uses: the console
    proxies `/auth`, so the realm has exactly one issuer and Grafana's session cookie is
    same-origin for the embedded dashboards. `internal_base_url` is what a service inside the
    compose network uses, so that validating a token does not depend on the frontend container
    being up to serve a proxy.
    """

    realm: str = _settings.get("auth.realm", "uns")
    base_url: str = _settings.get("auth.base_url", "http://localhost:8088/auth")
    issuer: str = _settings.get("auth.issuer", "http://localhost:8088/auth/realms/uns")
    console_client_id: str = _settings.get("auth.console_client_id", "uns-console")
    grafana_client_id: str = _settings.get("auth.grafana_client_id", "uns-grafana")
    audience: str = _settings.get("auth.audience", "uns-console")
    leeway_seconds: int = int(_settings.get("auth.leeway_seconds", 30))
    internal_base_url: str = _settings.get("auth.internal_base_url", "http://uns_keycloak:8080")

    @classmethod
    def jwks_url(cls) -> str:
        # internal_base_url is the container root; --http-relative-path=/auth prefixes /realms.
        return f"{cls.internal_base_url}/auth/realms/{cls.realm}/protocol/openid-connect/certs"

    @classmethod
    def discovery_url(cls) -> str:
        return f"{cls.base_url}/realms/{cls.realm}/.well-known/openid-configuration"
