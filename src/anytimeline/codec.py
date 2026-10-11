"""Binary encodings for arrays sent to the browser.

Arrays travel as raw little-endian typed buffers described by a small JSON descriptor, so
the browser can view them without parsing or copying. The descriptor's ``id`` is a hash of
the bytes and the dtype: identical data always has the same id and is sent once.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

DTYPES = {
    "float64": "<f8",
    "float32": "<f4",
    "int32": "<i4",
    "uint32": "<u4",
    "uint16": "<u2",
    "uint8": "u1",
}
"""The dtypes the browser reads, and their NumPy spelling."""


@dataclass(frozen=True)
class Encoded:
    """An encoded array: a JSON-able descriptor plus the raw bytes."""

    descriptor: dict[str, Any]
    data: bytes

    @property
    def id(self) -> str:
        return self.descriptor["id"]


def _descriptor(data: bytes, dtype: str, count: int, components: int) -> dict[str, Any]:
    return {
        "id": hashlib.blake2b(data, digest_size=12).hexdigest() + f"-{dtype}",
        "dtype": dtype,
        "count": count,
        "components": components,
        "byteLength": len(data),
    }


def encode(values: Any, dtype: str, *, components: int = 1) -> Encoded:
    """Encode an array as ``dtype`` (a key of ``DTYPES``).

    Args:
        values: Array of shape ``(n,)`` or ``(n, components)``.
        dtype: The type the browser views the bytes as.
        components: Interleaved components per element (e.g. 4 for RGBA).
    """
    if dtype not in DTYPES:
        raise ValueError(f"unknown dtype {dtype!r}; known: {list(DTYPES)}")
    arr = np.asarray(values)
    if arr.ndim == 2 and arr.shape[1] != components:
        raise ValueError(f"expected {components} components, got shape {arr.shape}")
    if arr.ndim == 1 and components > 1:
        raise ValueError("pass a (n, components) array for interleaved data")
    if arr.dtype.kind == "f" and DTYPES[dtype][1] != "f" and not np.all(np.isfinite(arr)):
        raise ValueError("values must be finite for an integer dtype")
    data = np.ascontiguousarray(arr.astype(DTYPES[dtype], copy=False)).tobytes()
    count = int(arr.shape[0]) if arr.ndim else 1
    return Encoded(_descriptor(data, dtype, count, components), data)


def encode_strings(strings: Sequence[str]) -> Encoded:
    """Encode text as ``count + 1`` little-endian uint32 byte offsets, then the UTF-8 bytes.

    String ``i`` is ``utf8[offsets[i]:offsets[i + 1]]``; the browser decodes it with a
    ``TextDecoder``, without parsing JSON.
    """
    parts = [s.encode("utf-8") for s in strings]
    offsets = np.zeros(len(parts) + 1, dtype="<u4")
    offsets[1:] = np.cumsum([len(p) for p in parts])
    data = offsets.tobytes() + b"".join(parts)
    return Encoded(_descriptor(data, "utf8", len(parts), 1), data)


def decode(descriptor: dict[str, Any], data: bytes) -> np.ndarray:
    """Inverse of ``encode`` (for tests and round trips)."""
    arr = np.frombuffer(data, dtype=DTYPES[descriptor["dtype"]])
    if descriptor["components"] > 1:
        arr = arr.reshape(-1, descriptor["components"])
    return arr


def decode_strings(descriptor: dict[str, Any], data: bytes) -> list[str]:
    """Inverse of ``encode_strings``."""
    n = descriptor["count"]
    offsets = np.frombuffer(data, dtype="<u4", count=n + 1)
    text = data[4 * (n + 1) :]
    return [text[offsets[i] : offsets[i + 1]].decode("utf-8") for i in range(n)]
