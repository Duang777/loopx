"""Public-safe HTTP mapping and conditional response helpers."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping, TypeVar

from fastapi import Request, Response
from pydantic import BaseModel

from loopx.application.contracts import application_public_safe_text


_ModelT = TypeVar("_ModelT", bound=BaseModel)
_REDACTED = "[redacted]"
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "credential",
    "api_key",
    "access_key",
    "private_key",
    "client_secret",
    "connector_payload",
    "raw_log",
    "log_tail",
)
_SENSITIVE_KEY_SUFFIXES = ("_path", "_repo")
_SENSITIVE_KEYS = frozenset(
    {
        "path",
        "repo",
        "registry",
        "registry_path",
        "runtime_root",
        "source_registry",
        "source_registry_path",
        "absolute_path",
    }
)


def public_safe_payload(value: object, *, key: str | None = None) -> Any:
    """Convert one Application projection into bounded JSON-safe values.

    Explicit Pydantic response models still define the shape.  This final mapper
    prevents nested error details and configuration effects from reintroducing
    paths, credentials, raw logs, or connector payloads.
    """

    if key is not None and _sensitive_key(key):
        return _REDACTED
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return public_safe_payload(value.value, key=key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _REDACTED
    if isinstance(value, str):
        safe = application_public_safe_text(value, limit=10_000)
        return safe if safe is not None else _REDACTED
    if isinstance(value, BaseModel):
        return public_safe_payload(value.model_dump(mode="python"), key=key)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            descriptor.name: public_safe_payload(
                getattr(value, descriptor.name),
                key=descriptor.name,
            )
            for descriptor in fields(value)
        }
    if isinstance(value, Mapping):
        payload: dict[str, Any] = {}
        for raw_key, item in value.items():
            safe_key = application_public_safe_text(raw_key, limit=200)
            if safe_key is None:
                continue
            payload[safe_key] = public_safe_payload(item, key=safe_key)
        return payload
    if isinstance(value, (list, tuple, set, frozenset)):
        return [public_safe_payload(item) for item in value]
    return _REDACTED


def wire_model(model: type[_ModelT], value: object) -> _ModelT:
    return model.model_validate(public_safe_payload(value))


def stable_etag(material: object) -> str:
    canonical = json.dumps(
        public_safe_payload(material),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return f'"sha256:{digest}"'


def conditional_response(
    request: Request,
    response: Response,
    *,
    payload: _ModelT,
    etag_material: object,
) -> _ModelT | Response:
    etag = stable_etag(etag_material)
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return payload


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    for candidate in header.split(","):
        normalized = candidate.strip()
        if normalized == "*":
            return True
        if normalized.startswith("W/"):
            normalized = normalized[2:].strip()
        if normalized == etag:
            return True
    return False


def _sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized in _SENSITIVE_KEYS
        or any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)
        or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)
    )
