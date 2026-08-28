"""Resolve and load platform configuration from the root conf/ directory."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dynaconf import Dynaconf

_SETTINGS_ENV_VAR = "UNS_CONF_DIR"
_DOCKER_CONF_DIR = Path("/app/conf")
_REPO_CONF_MARKER = ("conf", "settings.yaml")


def resolve_conf_dir() -> Path:
    """
  Return the directory containing settings.yaml and .secrets.yaml.

  Resolution order:
  1. UNS_CONF_DIR environment variable
  2. /app/conf when mounted in Docker
  3. Walk up from the current working directory
  4. Repository root relative to this package (local development)
  """
    if env_dir := os.environ.get(_SETTINGS_ENV_VAR):
        return Path(env_dir).resolve()

    docker_settings = _DOCKER_CONF_DIR / _REPO_CONF_MARKER[1]
    if docker_settings.is_file():
        return _DOCKER_CONF_DIR

    for parent in (Path.cwd(), *Path.cwd().parents):
        candidate = parent.joinpath(*_REPO_CONF_MARKER)
        if candidate.is_file():
            return candidate.parent

    # 00_uns_config/src/uns_config/loader.py -> repo root
    return Path(__file__).resolve().parents[3] / "conf"


@lru_cache
def get_settings(module_env: str = "default") -> Dynaconf:
    """Load merged settings for the given Dynaconf environment."""
    conf_dir = resolve_conf_dir()
    return Dynaconf(
        envvar_prefix="UNS",
        environments=True,
        env=module_env,
        root_path=conf_dir,
        settings_files=["settings.yaml", ".secrets.yaml"],
        merge_enabled=True,
    )
