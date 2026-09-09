"""Configuration for the datalake Mapper."""

from __future__ import annotations

from dataclasses import dataclass

from uns_config import get_settings

DATALAKE_ENV = "default"
DEFAULT_MINIO_ENDPOINT = "http://uns-minio:9000"


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True, slots=True)
class DatalakeConfig:
    backend: str = "s3"
    kafka_topic: str = "uns.historic-events"
    group_id: str = "uns_datalake"
    bootstrap_servers: str = "localhost:9092"
    interval_seconds: float = 60.0
    max_bytes: int = 8388608
    max_records: int = 10000
    max_record_bytes: int = 1048576
    s3_bucket: str = "uns-historic-events"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = DEFAULT_MINIO_ENDPOINT
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    adls_account: str = ""
    adls_container: str = ""
    adls_endpoint_url: str | None = None
    adls_account_key: str | None = None
    metrics_port: int = 9096

    @classmethod
    def from_settings(cls, module_env: str = DATALAKE_ENV) -> DatalakeConfig:
        settings = get_settings(module_env)
        datalake = settings.get("datalake") or {}

        backend = str(datalake.get("backend", "s3")).strip().lower()
        if backend not in ("s3", "adls"):
            raise ValueError(f"unsupported datalake.backend: {backend}")

        interval_seconds = float(datalake.get("flush", {}).get("interval_seconds", 60))
        max_bytes = int(datalake.get("flush", {}).get("max_bytes", 8388608))
        max_records = int(datalake.get("max_records", 10000))
        max_record_bytes = int(datalake.get("max_record_bytes", 1048576))
        metrics_port = int(datalake.get("metrics_port", 9096))

        if interval_seconds < 0:
            raise ValueError("datalake.flush.interval_seconds must be non-negative")
        if max_bytes <= 0 or max_record_bytes <= 0:
            raise ValueError("datalake byte limits must be positive")
        if max_records <= 0:
            raise ValueError("datalake.max_records must be positive")
        if not (0 < metrics_port < 65536):
            raise ValueError("datalake.metrics_port out of range")

        kafka_cfg = datalake.get("kafka") or {}
        kafka_topic = kafka_cfg.get("topic", "uns.historic-events")
        group_id = kafka_cfg.get("group_id", "uns_datalake")

        kafka_config = settings.get("kafka.config", {}) or {}
        bootstrap_servers = kafka_config.get("bootstrap.servers", settings.get("kafka.bootstrap_servers", "localhost:9092"))

        s3_cfg = datalake.get("s3") or {}
        s3_bucket = str(s3_cfg.get("bucket", "uns-historic-events")).strip()
        s3_region = str(s3_cfg.get("region", "us-east-1")).strip()
        s3_endpoint_url = _normalize_optional(s3_cfg.get("endpoint_url"))
        s3_access_key = _normalize_optional(s3_cfg.get("access_key"))
        s3_secret_key = _normalize_optional(s3_cfg.get("secret_key"))

        if backend == "s3" and not s3_bucket:
            raise ValueError("datalake.s3.bucket is required for backend s3")

        if (s3_access_key is None) ^ (s3_secret_key is None):
            raise ValueError("datalake.s3 access_key and secret_key must both be set or both omitted")

        if s3_access_key is None and s3_secret_key is None:
            if s3_endpoint_url == DEFAULT_MINIO_ENDPOINT:
                s3_access_key = _normalize_optional(settings.get("minio.root_user"))
                s3_secret_key = _normalize_optional(settings.get("minio.root_password"))
                if not s3_access_key or not s3_secret_key:
                    raise ValueError("minio.root_user and minio.root_password required for default MinIO endpoint")

        adls_cfg = datalake.get("adls") or {}
        adls_account = str(adls_cfg.get("account", "")).strip()
        adls_container = str(adls_cfg.get("container", "")).strip()
        adls_endpoint_url = _normalize_optional(adls_cfg.get("endpoint_url"))
        adls_account_key = _normalize_optional(adls_cfg.get("account_key"))

        if backend == "adls":
            if not adls_account or not adls_container:
                raise ValueError("datalake.adls.account and container are required for backend adls")

        return cls(
            backend=backend,
            kafka_topic=kafka_topic,
            group_id=group_id,
            bootstrap_servers=bootstrap_servers,
            interval_seconds=interval_seconds,
            max_bytes=max_bytes,
            max_records=max_records,
            max_record_bytes=max_record_bytes,
            s3_bucket=s3_bucket,
            s3_region=s3_region,
            s3_endpoint_url=s3_endpoint_url,
            s3_access_key=s3_access_key,
            s3_secret_key=s3_secret_key,
            adls_account=adls_account,
            adls_container=adls_container,
            adls_endpoint_url=adls_endpoint_url,
            adls_account_key=adls_account_key,
            metrics_port=metrics_port,
        )
