"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Connection settings for the database holding the Asset Model.

The Asset Model lives in the same Postgres/Timescale database as the historian
hypertables, so it reads the same `historian.*` keys. Those keys sit under
`default:` in conf/settings.yaml and are therefore visible from every Dynaconf
environment, which is why the environment is a parameter rather than a constant.
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass

from uns_config import get_settings

LOGGER = logging.getLogger(__name__)

MODEL_SCHEMA = "model"
CONSOLE_SCHEMA = "console"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Everything needed to reach the database holding the Asset Model."""

    hostname: str
    database: str
    user: str
    password: str
    port: int = 5432
    sslmode: str | None = None
    sslrootcert: str | None = None
    sslcert: str | None = None
    sslkey: str | None = None

    @classmethod
    def from_settings(cls, module_env: str = "default") -> ModelConfig:
        """Read connection settings from the platform conf/ directory."""
        settings = get_settings(module_env)
        config = cls(
            hostname=settings.get("historian.hostname"),
            database=settings.get("historian.database"),
            user=settings.get("historian.username"),
            password=settings.get("historian.password"),
            port=settings.get("historian.port") or 5432,
            sslmode=settings.get("historian.sslmode", None),
            sslrootcert=settings.get("historian.sslrootcert", None),
            sslcert=settings.get("historian.sslcert", None),
            sslkey=settings.get("historian.sslkey", None),
        )
        if not config.is_valid():
            LOGGER.error(
                "Asset Model database is not configured. Set 'historian.hostname', 'historian.database' in "
                "'conf/settings.yaml' and 'historian.username', 'historian.password' in 'conf/.secrets.yaml'"
            )
        return config

    def is_valid(self) -> bool:
        """Mandatory settings are present. Does not check that they are correct."""
        return all((self.hostname, self.database, self.user, self.password))

    @property
    def url(self) -> str:
        """SQLAlchemy async URL. The password is deliberately not interpolated here."""
        return f"postgresql+asyncpg://{self.user}@{self.hostname}:{self.port}/{self.database}"

    def connect_args(self) -> dict:
        """
        asyncpg connect arguments, including the password and SSL context.

        Kept out of the URL so the password never reaches a log line that echoes
        the engine, and because asyncpg wants an `ssl.SSLContext` rather than the
        libpq `sslmode` string.
        """
        args: dict = {"password": self.password}
        if ssl_context := self._ssl_context():
            args["ssl"] = ssl_context
        return args

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not self.sslmode or self.sslmode.lower() == "disable":
            return None
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        if self.sslmode.lower() in {"allow", "prefer", "require"}:
            # Faithful to libpq: these modes encrypt but do not authenticate the
            # server, so they cannot detect a machine-in-the-middle. Verification
            # stays on for 'verify-ca' and 'verify-full'.
            LOGGER.warning(
                "historian.sslmode is '%s', so the Asset Model connection is encrypted but the server "
                "certificate is NOT verified. Use 'verify-full' with 'historian.sslrootcert' in production.",
                self.sslmode,
            )
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if self.sslrootcert:
            context.load_verify_locations(cafile=self.sslrootcert)
        if self.sslcert:
            context.load_cert_chain(certfile=self.sslcert, keyfile=self.sslkey)
        return context
