"""Datalake mapper configuration and backend validation."""



from __future__ import annotations



import logging

from dataclasses import dataclass

from typing import Literal

from uns_config import get_settings
from uns_datalake.replay import VALID_INITIAL_POSITIONS, InitialPosition

from uns_config.kafka import sanitize_kafka_config

from uns_datalake.routing import LegacyRouteEntry, LegacyRouteKey, LegacyRouteMap, build_legacy_route_map



LOGGER = logging.getLogger(__name__)



DEFAULT_MINIO_ENDPOINT = "http://uns-minio:9000"

DEFAULT_HISTORIC_TOPIC = "uns.historic-events"

DEFAULT_GROUP_ID = "uns_datalake"



settings = get_settings("datalake")





@dataclass(frozen=True, slots=True)

class FlushLimits:

    interval_seconds: float = 60.0

    max_bytes: int = 8_388_608

    max_records: int = 10_000

    max_record_bytes: int = 1_048_576

    worker_max_buffered_bytes: int = 32 * 1024 * 1024

    max_active_route_groups: int = 64

    max_encoded_bytes: int = 16 * 1024 * 1024



    def __post_init__(self) -> None:

        validate_flush_limits(self)





def validate_flush_limits(limits: FlushLimits) -> None:

    positive_fields = (

        ("interval_seconds", limits.interval_seconds),

        ("max_bytes", limits.max_bytes),

        ("max_records", limits.max_records),

        ("max_record_bytes", limits.max_record_bytes),

        ("worker_max_buffered_bytes", limits.worker_max_buffered_bytes),

        ("max_active_route_groups", limits.max_active_route_groups),

        ("max_encoded_bytes", limits.max_encoded_bytes),

    )

    for name, value in positive_fields:

        if value <= 0:

            raise ValueError(f"flush.{name} must be positive")

    if limits.max_record_bytes > limits.max_bytes:

        raise ValueError("flush.max_record_bytes cannot exceed flush.max_bytes")

    if limits.max_bytes > limits.worker_max_buffered_bytes:

        raise ValueError("flush.max_bytes cannot exceed flush.worker_max_buffered_bytes")





@dataclass(frozen=True, slots=True)

class S3Settings:

    bucket: str

    region: str

    endpoint_url: str | None

    access_key_id: str | None

    secret_access_key: str | None





@dataclass(frozen=True, slots=True)

class AdlsSettings:

    account: str

    container: str

    account_key: str | None





def validate_s3_credential_pair(access_key_id: str | None, secret_access_key: str | None) -> None:

    if (access_key_id is None) ^ (secret_access_key is None):

        raise ValueError("datalake.s3 access_key_id and secret_access_key must be supplied together")





class DatalakeConfig:

    backend: Literal["s3", "adls"] = settings.get("backend", "s3")

    historic_topic: str = settings.get("kafka.topic", DEFAULT_HISTORIC_TOPIC)

    group_id: str = settings.get("kafka.group_id", DEFAULT_GROUP_ID)

    initial_position: InitialPosition = settings.get("kafka.initial_position", "require_committed")

    assignment_timeout_seconds: float = float(settings.get("kafka.assignment_timeout_seconds", 5.0))

    metrics_port: int = int(settings.get("metrics_port", 9096))

    consumer_poll_timeout: float = float(settings.get("consumer_poll_timeout", 0.2))

    upload_connect_timeout: float = float(settings.get("upload.connect_timeout_seconds", 5.0))

    upload_read_timeout: float = float(settings.get("upload.read_timeout_seconds", 10.0))

    upload_max_attempts: int = int(settings.get("upload.max_attempts", 3))

    flush = FlushLimits(

        interval_seconds=float(settings.get("flush.interval_seconds", 60.0)),

        max_bytes=int(settings.get("flush.max_bytes", 8_388_608)),

        max_records=int(settings.get("flush.max_records", 10_000)),

        max_record_bytes=int(settings.get("flush.max_record_bytes", 1_048_576)),

        worker_max_buffered_bytes=int(settings.get("flush.worker_max_buffered_bytes", 32 * 1024 * 1024)),

        max_active_route_groups=int(settings.get("flush.max_active_route_groups", 64)),

        max_encoded_bytes=int(settings.get("flush.max_encoded_bytes", 16 * 1024 * 1024)),

    )



    @classmethod

    def kafka_consumer_config(cls) -> dict:

        base = sanitize_kafka_config(settings.get("kafka.config", {}))

        base.update(

            {

                "group.id": cls.group_id,

                "enable.auto.commit": False,

                "enable.auto.offset.store": False,

                "auto.offset.reset": "error",

            }

        )

        return base

    @classmethod

    def validate_initial_position(cls) -> None:

        if cls.initial_position not in VALID_INITIAL_POSITIONS:

            raise ValueError(

                "datalake.kafka.initial_position must be one of "

                f"{sorted(VALID_INITIAL_POSITIONS)}"

            )



    @classmethod

    def s3_settings(cls) -> S3Settings:

        endpoint = settings.get("s3.endpoint_url", DEFAULT_MINIO_ENDPOINT)

        endpoint = None if endpoint in ("", None) else str(endpoint)

        access_key = settings.get("s3.access_key_id")

        secret_key = settings.get("s3.secret_access_key")

        validate_s3_credential_pair(access_key, secret_key)

        return S3Settings(

            bucket=str(settings.get("s3.bucket", "uns-historic-events")),

            region=str(settings.get("s3.region", "us-east-1")),

            endpoint_url=endpoint,

            access_key_id=access_key,

            secret_access_key=secret_key,

        )



    @classmethod

    def adls_settings(cls) -> AdlsSettings:

        account = str(settings.get("adls.account", "") or "")

        container = str(settings.get("adls.container", "") or "")

        if not account or not container:

            raise ValueError("datalake.adls.account and datalake.adls.container are required for backend adls")

        return AdlsSettings(

            account=account,

            container=container,

            account_key=settings.get("adls.account_key"),

        )



    @classmethod

    def resolve_s3_credentials(

        cls,

        s3: S3Settings,

        *,

        minio_user: str | None = None,

        minio_password: str | None = None,

    ) -> tuple[str | None, str | None]:

        if s3.access_key_id and s3.secret_access_key:

            return s3.access_key_id, s3.secret_access_key

        if s3.endpoint_url == DEFAULT_MINIO_ENDPOINT:

            user = minio_user if minio_user is not None else settings.get("minio.root_user")

            password = minio_password if minio_password is not None else settings.get("minio.root_password")

            if user and password:

                return str(user), str(password)

        return None, None



    @classmethod

    def validate_backend(cls) -> None:

        cls.validate_initial_position()

        if cls.backend == "s3":

            cls.s3_settings()

        elif cls.backend == "adls":

            cls.adls_settings()

        else:

            raise ValueError(f"unsupported datalake.backend {cls.backend!r}")



    @classmethod

    def is_config_valid(cls) -> bool:

        try:

            cls.validate_backend()

        except ValueError as exc:

            LOGGER.error("%s", exc)

            return False

        return True



    @classmethod

    def legacy_route_map(cls) -> LegacyRouteMap | None:

        raw = settings.get("legacy_route_map")

        if not raw:

            return None

        revision = str(raw.get("revision", "") or "")

        if not revision:

            raise ValueError("datalake.legacy_route_map.revision is required when legacy_route_map is configured")

        routes: dict[LegacyRouteKey, LegacyRouteEntry] = {}

        for item in raw.get("routes", []) or []:

            key: LegacyRouteKey = (

                str(item["topic"]),

                str(item["source_id"]),

                str(item["site_id"]),

            )

            routes[key] = LegacyRouteEntry(

                application=str(item["application"]),

                schema=str(item["schema"]),

                version=str(item["version"]),

            )

        return build_legacy_route_map(revision, routes)

