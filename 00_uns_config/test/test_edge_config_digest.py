"""Deterministic digest tests for edge desired-state documents."""

from __future__ import annotations

import json
import math

import pytest

from uns_config.edge_config_digest import canonical_config_bytes, configuration_digest


def test_digest_is_independent_of_object_key_order():
    assert configuration_digest({"revision": 2, "edge_id": "edge-01"}) == (
        configuration_digest({"edge_id": "edge-01", "revision": 2})
    )


def test_canonical_bytes_use_compact_utf8_json_with_sorted_keys():
    document = {"b": 2, "a": {"d": 4, "c": 3}}
    encoded = canonical_config_bytes(document)
    assert encoded == b'{"a":{"c":3,"d":4},"b":2}'


def test_canonical_bytes_exclude_only_top_level_digest():
    document = {"edge_id": "edge-01", "digest": "abc", "revision": 1}
    encoded = canonical_config_bytes(document)
    assert b"digest" not in encoded
    assert encoded == b'{"edge_id":"edge-01","revision":1}'


def test_configuration_digest_is_sha256_hex():
    digest = configuration_digest({"edge_id": "edge-01", "revision": 1})
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_canonical_bytes_reject_nan_values():
    with pytest.raises(ValueError):
        canonical_config_bytes({"revision": math.nan})


def test_canonical_bytes_reject_infinity_values():
    with pytest.raises(ValueError):
        canonical_config_bytes({"revision": math.inf})
