"""Verified immutable object publication contract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import BinaryIO, Iterable, Protocol


class IntegrityError(Exception):
    """Raised when stored object content does not match the expected hash or length."""


class AccessDeniedError(Exception):
    """Raised when the object store rejects a publication for auth or permission reasons."""


@dataclass(frozen=True, slots=True)
class FrozenObject:
    key: str
    data: bytes
    sha256: str
    row_count: int

    @classmethod
    def from_bytes(cls, key: str, data: bytes, *, row_count: int) -> FrozenObject:
        return cls(
            key=key,
            data=data,
            sha256=hash_bytes(data),
            row_count=row_count,
        )


class ImmutableObjectStore(Protocol):
    def publish_exact(self, key: str, data: bytes, sha256: str) -> None: ...

    def verify_exact(self, key: str, sha256: str, byte_length: int) -> None: ...


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_bytes(data: bytes, expected_sha256: str, expected_length: int) -> None:
    if len(data) != expected_length:
        raise IntegrityError(
            f"object length {len(data)} does not match expected {expected_length}"
        )
    actual = hash_bytes(data)
    if actual != expected_sha256:
        raise IntegrityError(
            f"object hash {actual} does not match expected {expected_sha256}"
        )


def hash_stream(chunks: Iterable[bytes]) -> tuple[str, int]:
    hasher = hashlib.sha256()
    total = 0
    for chunk in chunks:
        hasher.update(chunk)
        total += len(chunk)
    return hasher.hexdigest(), total


def read_stream(body: BinaryIO, *, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    return hash_stream(iter(lambda: body.read(chunk_size), b""))
