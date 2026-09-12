"""Platform-wide settings shared across modules (instance, URLs, application names)."""

from __future__ import annotations

from uns_config.loader import get_settings

_settings = get_settings("default")


def _strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")


def _resolved_public_origin(settings) -> str | None:
    raw = settings.get("platform.public_origin")
    if raw is None:
        return None
    text = str(raw).strip()
    return _strip_trailing_slash(text) if text else None


def _console_origin(settings, public_origin: str | None) -> str:
    if public_origin:
        return public_origin
    compose_port = int(
        settings.get("applications.frontend.compose_port", settings.get("urls.frontend_compose_port", 8088))
    )
    return f"http://localhost:{compose_port}"


def _auth_base_url(settings, console_origin: str) -> str:
    return f"{console_origin}/auth"


def _auth_issuer(settings, console_origin: str) -> str:
    realm = settings.get("auth.realm", "uns")
    return f"{console_origin}/auth/realms/{realm}"


def _resolved_cors_origins(settings, console_origin: str) -> list[str]:
    configured = list(settings.get("urls.cors_origins", []))
    if console_origin and console_origin not in configured:
        configured.append(console_origin)
    return configured


_public_origin = _resolved_public_origin(_settings)
_console_origin = _console_origin(_settings, _public_origin)


class PlatformConfig:
    """Client-specific platform identity and URL settings."""

    instance_name: str = _settings.get("platform.instance_name", "default")
    organization_name: str = _settings.get("platform.organization_name", "")
    display_name: str = _settings.get("platform.display_name", "Unified Namespace")

    graphql_host: str = _settings.get("urls.graphql_host", "localhost")
    graphql_port: int = int(_settings.get("urls.graphql_port", 8000))
    graphql_path: str = _settings.get("urls.graphql_path", "/graphql")
    cors_origins: list[str] = _resolved_cors_origins(_settings, _console_origin)

    frontend_dev_port: int = int(
        _settings.get("applications.frontend.dev_port", _settings.get("urls.frontend_dev_port", 5173))
    )
    frontend_compose_port: int = int(
        _settings.get("applications.frontend.compose_port", _settings.get("urls.frontend_compose_port", 8088))
    )

    mqtt_public_host: str = str(_settings.get("mqtt.public_host", _settings.get("mqtt.host", "localhost")))
    mqtt_public_port: int = int(_settings.get("mqtt.public_port", _settings.get("mqtt.port", 1883)))

    @classmethod
    def public_origin(cls) -> str | None:
        return _public_origin

    @classmethod
    def console_origin(cls) -> str:
        return _console_origin

    @classmethod
    def graphql_url(cls) -> str:
        if _public_origin:
            return f"{_public_origin}{cls.graphql_path}"
        return f"http://{cls.graphql_host}:{cls.graphql_port}{cls.graphql_path}"

    @classmethod
    def grafana_root_url(cls) -> str:
        return f"{cls.console_origin()}/grafana/"

    @classmethod
    def grafana_oauth_auth_url(cls) -> str:
        realm = AuthConfig.realm
        return f"{cls.console_origin()}/auth/realms/{realm}/protocol/openid-connect/auth"

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
    base_url: str = _auth_base_url(_settings, _console_origin) if _public_origin else _settings.get(
        "auth.base_url", "http://localhost:8088/auth"
    )
    issuer: str = _auth_issuer(_settings, _console_origin) if _public_origin else _settings.get(
        "auth.issuer", "http://localhost:8088/auth/realms/uns"
    )
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
