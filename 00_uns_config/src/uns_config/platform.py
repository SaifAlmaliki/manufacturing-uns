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
