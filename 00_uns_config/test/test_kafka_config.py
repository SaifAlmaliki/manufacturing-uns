"""Empty SASL placeholders in conf/.secrets.yaml must not reach librdkafka."""

from uns_config.kafka import sanitize_kafka_config


def test_empty_sasl_credentials_are_dropped_so_plaintext_brokers_work():
    cleaned = sanitize_kafka_config(
        {
            "client.id": "uns_kafka_client",
            "bootstrap.servers": "uns_kafka_broker:29092",
            "security.protocol": "SASL_SSL",
            "sasl.mechanisms": "SCRAM-SHA-256",
            "sasl.username": "",
            "sasl.password": "",
            "ssl.cipher.suites": "",
        }
    )

    assert cleaned == {
        "client.id": "uns_kafka_client",
        "bootstrap.servers": "uns_kafka_broker:29092",
    }


def test_sasl_credentials_are_kept_when_both_are_set():
    cleaned = sanitize_kafka_config(
        {
            "bootstrap.servers": "pkc.example:9092",
            "security.protocol": "SASL_SSL",
            "sasl.mechanisms": "SCRAM-SHA-256",
            "sasl.username": "user",
            "sasl.password": "secret",
        }
    )

    assert cleaned["security.protocol"] == "SASL_SSL"
    assert cleaned["sasl.username"] == "user"
    assert cleaned["sasl.password"] == "secret"
