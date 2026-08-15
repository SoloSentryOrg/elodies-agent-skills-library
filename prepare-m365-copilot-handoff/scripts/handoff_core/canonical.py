"""Canonical JSON for the integer-only RFC 8785-compatible contract subset."""

from __future__ import annotations

import json
import unicodedata
from typing import Any


class CanonicalisationError(ValueError):
    """Raised when a value is outside the canonical contract subset."""


def normalise(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalisationError("floating-point numbers are not permitted")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if isinstance(value, list):
        return [normalise(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalisationError("JSON object keys must be strings")
        return {normalise(key): normalise(item) for key, item in value.items()}
    raise CanonicalisationError(f"unsupported JSON type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    prepared = normalise(value)
    return json.dumps(
        prepared,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
