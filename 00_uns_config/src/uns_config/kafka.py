"""Librdkafka client maps from Dynaconf-merged kafka.config."""

from __future__ import annotations


def sanitize_kafka_config(raw: dict | None) -> dict:
    """Drop empty secrets-template keys so a PLAINTEXT broker can start a producer.

    ``conf/.secrets.yaml`` ships ``security.protocol: SASL_SSL`` with blank
    username/password for cloud brokers. Dynaconf merges those into the Compose
    PLAINTEXT override and librdkafka then refuses to create a producer.
    """
    if not raw:
        return {}
    cleaned = {key: value for key, value in raw.items() if value not in (None, "")}
    protocol = str(cleaned.get("security.protocol", "")).upper()
    if protocol.startswith("SASL") and not (
        cleaned.get("sasl.username") and cleaned.get("sasl.password")
    ):
        cleaned.pop("security.protocol", None)
        for key in [key for key in cleaned if key.startswith("sasl.")]:
            cleaned.pop(key)
    return cleaned
