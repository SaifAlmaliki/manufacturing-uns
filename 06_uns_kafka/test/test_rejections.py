"""Tests for DLQ rejection encoding."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from uns_kafka.rejections import (
    MAX_REJECTION_BYTES,
    RejectionError,
    RejectionRecord,
    decode_rejection,
    encode_rejection,
    rejection_key,
)


def test_rejection_round_trip_preserves_bounded_fields():
    record = RejectionRecord(
        stage="mqtt_ingress",
        origin="shard-a",
        reason="invalid_json",
        captured_at=datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
        topic="Enterprise/PlantA/Device/Temperature",
        original_bytes=b'{"broken":',
    )
    restored = decode_rejection(encode_rejection(record))
    assert restored == record


def test_rejection_key_is_stable_for_origin_stage_and_topic():
    record = RejectionRecord(
        stage="mqtt_ingress",
        origin="shard-a",
        reason="invalid_json",
        captured_at=datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
        topic="Enterprise/PlantA/Device/Temperature",
        original_bytes=b"{}",
    )
    assert rejection_key(record) == rejection_key(record)


def test_rejection_encode_rejects_unarchivable_original_bytes():
    with pytest.raises(RejectionError, match="oversize"):
        RejectionRecord(
            stage="mqtt_ingress",
            origin="shard-a",
            reason="oversize",
            captured_at=datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC),
            topic="Enterprise/PlantA/Device/Temperature",
            original_bytes=b"x" * (MAX_REJECTION_BYTES + 1),
        )
