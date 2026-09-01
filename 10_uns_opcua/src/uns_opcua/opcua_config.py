"""Configuration reader for the read-only OPC UA edge connector."""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from aiomqtt import ProtocolVersion, TLSParameters
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from uns_config import get_settings

LOGGER = logging.getLogger(__name__)

settings = get_settings("opcua")

DEADBAND_TYPES: frozenset[str] = frozenset({"none", "absolute", "percent"})
SYNCHRONOUS_MODES: frozenset[str] = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})


@dataclass(frozen=True, slots=True)
class Deadband:
    """A server-side report-by-exception threshold. `none` is modelled as no Deadband."""

    type: Literal["absolute", "percent"]
    value: float


@dataclass(frozen=True, slots=True)
class TagConfig:
    """One OPC UA node mapped to an Asset and the topic segments below it."""

    node_id: str
    asset: str
    metric_path: str
    unit: str | None = None
    deadband: Deadband | None = None


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    """OPC UA session security. Pass phrases belong in .secrets.yaml, not here."""

    policy: str
    mode: str
    certificate: str
    private_key: str
    server_certificate: str | None = None

    def to_security_string(self) -> str:
        """asyncua's `set_security_string` format: Policy,Mode,cert,key[,server_cert]."""
        parts = [self.policy, self.mode, self.certificate, self.private_key]
        if self.server_certificate:
            parts.append(self.server_certificate)
        return ",".join(parts)


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """One OPC UA server and the tags collected from it."""

    name: str
    url: str
    publishing_interval_ms: int
    tags: tuple[TagConfig, ...]
    security: SecurityConfig | None = None


@dataclass(frozen=True, slots=True)
class SpoolConfig:
    """Bounds for the disk-backed store-and-forward spool."""

    path: str
    max_rows: int
    max_bytes: int
    max_age_hours: int
    synchronous: str


def parse_deadband(raw: Any) -> Deadband | None:
    """Return None for an absent or explicitly `none` Deadband."""
    if not raw:
        return None
    db_type = str(raw.get("type", "none")).lower()
    if db_type not in DEADBAND_TYPES:
        raise ValueError(f"Unsupported deadband type {db_type!r}; expected one of {sorted(DEADBAND_TYPES)}")
    if db_type == "none":
        return None
    return Deadband(type=db_type, value=float(raw["value"]))


def parse_tag(raw: Any) -> TagConfig:
    node_id = raw.get("node_id")
    if not node_id:
        raise ValueError("An opcua tag is missing 'node_id'")
    asset = str(raw.get("asset") or "").strip("/")
    if not asset:
        raise ValueError(f"opcua tag {node_id!r} is missing 'asset'")
    return TagConfig(
        node_id=str(node_id),
        asset=asset,
        metric_path=str(raw.get("metric_path") or "").strip("/"),
        unit=raw.get("unit"),
        deadband=parse_deadband(raw.get("deadband")),
    )


def parse_security(raw: Any) -> SecurityConfig | None:
    if not raw:
        return None
    missing = [key for key in ("policy", "mode", "certificate", "private_key") if not raw.get(key)]
    if missing:
        raise ValueError(f"opcua server security is missing {', '.join(missing)}")
    return SecurityConfig(
        policy=str(raw["policy"]),
        mode=str(raw["mode"]),
        certificate=str(raw["certificate"]),
        private_key=str(raw["private_key"]),
        server_certificate=raw.get("server_certificate"),
    )


def parse_server(raw: Any) -> ServerConfig:
    name = raw.get("name")
    if not name:
        raise ValueError("An opcua server is missing 'name'")
    url = raw.get("url")
    if not url:
        raise ValueError(f"opcua server {name!r} is missing 'url'")
    tags = tuple(parse_tag(tag) for tag in raw.get("tags") or ())
    if not tags:
        raise ValueError(f"opcua server {name!r} has no tags")
    return ServerConfig(
        name=str(name),
        url=str(url),
        publishing_interval_ms=int(raw.get("publishing_interval_ms", 200)),
        tags=tags,
        security=parse_security(raw.get("security")),
    )


def parse_servers(raw: Any) -> tuple[ServerConfig, ...]:
    return tuple(parse_server(server) for server in raw or ())


def parse_spool(raw: Any) -> SpoolConfig:
    raw = raw or {}
    synchronous = str(raw.get("synchronous", "NORMAL")).upper()
    if synchronous not in SYNCHRONOUS_MODES:
        raise ValueError(f"Unsupported spool synchronous mode {synchronous!r}; expected one of {sorted(SYNCHRONOUS_MODES)}")
    return SpoolConfig(
        path=str(raw.get("path", "/var/lib/uns_opcua/spool.db")),
        max_rows=int(raw.get("max_rows", 5_000_000)),
        max_bytes=int(raw.get("max_bytes", 2_000_000_000)),
        max_age_hours=int(raw.get("max_age_hours", 168)),
        synchronous=synchronous,
    )


class OpcUaConfig:
    """The `opcua` block of settings.yaml."""

    client_id: str = settings.get("opcua.client_id")
    """Rule 2: stable across restarts, never generated."""

    model_check: bool = bool(settings.get("opcua.model_check", True))
    metrics_port: int = int(settings.get("opcua.metrics_port", 9093))
    reconnect_backoff_max_s: float = float(settings.get("opcua.reconnect_backoff_max_s", 60.0))
    queue_maxsize: int = int(settings.get("opcua.queue_maxsize", 50_000))
    forward_batch_size: int = int(settings.get("opcua.forward_batch_size", 200))
    spool: SpoolConfig = parse_spool(settings.get("opcua.spool", {}))
    servers: tuple[ServerConfig, ...] = parse_servers(settings.get("opcua.servers", []))

    @classmethod
    def is_config_valid(cls) -> bool:
        """Mandatory configuration is present. Does not validate the values themselves."""
        return bool(cls.client_id) and bool(cls.servers)


class MQTTConfig:
    """The shared `mqtt` block, read exactly as the simulator reads it."""

    transport: Literal["tcp", "websockets"] = settings.get("mqtt.transport", "tcp")
    version: ProtocolVersion = ProtocolVersion(settings.get("mqtt.version", ProtocolVersion.V5))
    properties: Properties | None = Properties(PacketTypes.CONNECT) if version == ProtocolVersion.V5 else None
    qos: Literal[0, 1, 2] = settings.get("mqtt.qos", 1)

    host: str = settings.get("mqtt.host")
    port: int = settings.get("mqtt.port", 1883)
    username: str | None = settings.get("mqtt.username")
    password: str | None = settings.get("mqtt.password")
    tls: dict | None = settings.get("mqtt.tls", None)

    tls_params: TLSParameters | None = (
        TLSParameters(
            ca_certs=tls.get("ca_certs"),
            certfile=tls.get("certfile"),
            keyfile=tls.get("keyfile"),
            cert_reqs=tls.get("cert_reqs"),
            ciphers=tls.get("ciphers"),
            keyfile_password=tls.get("keyfile_password"),
        )
        if tls is not None
        else None
    )
    tls_insecure: bool | None = tls.get("insecure_cert") if tls is not None else None
    keep_alive: int = settings.get("mqtt.keep_alive", 60)
    retry_interval: int = settings.get("mqtt.retry_interval", 10)

    @classmethod
    def is_config_valid(cls) -> bool:
        return cls.host is not None
