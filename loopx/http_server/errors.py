"""HTTP-adapter-local expected failures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class HttpAdapterError(Exception):
    code: str
    message: str
    status_code: int
    details: Mapping[str, object] = field(default_factory=dict)
    retryable: bool = False

