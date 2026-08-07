"""Fail-closed loopback and same-origin policy for HTTP v1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from starlette.requests import Request

from loopx.application import Profile

from .sessions import (
    ControlSessionManager,
    InvalidControlSession,
    OperatorAuthorityDenied,
)


CONTROL_SESSION_HEADER = "X-LoopX-Control-Session"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SESSION_CREATE_PATH = "/api/v1/control-sessions"
_OPERATOR_PATH_PREFIX = "/api/v1/operator/"
_READ_ONLY_POST_SUFFIX = "/turns/plan"


class ServerProfile(str, Enum):
    READ_ONLY = "read_only"
    LOCAL_OPERATOR = "local_operator"

    @property
    def application_profile(self) -> Profile:
        if self is ServerProfile.READ_ONLY:
            return Profile.HTTP_READ_ONLY
        return Profile.HTTP_LOCAL_OPERATOR

    @classmethod
    def parse(cls, value: object) -> ServerProfile:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError as exc:
            raise ValueError("profile must be read_only or local_operator") from exc


@dataclass(frozen=True, slots=True)
class ServerSettings:
    profile: ServerProfile
    bind_host: str
    allowed_hosts: frozenset[str]
    public_origin: str
    static_dir: Path | None = None

    def __post_init__(self) -> None:
        profile = ServerProfile.parse(self.profile)
        bind_host = _loopback_bind_host(self.bind_host)
        allowed_hosts = frozenset(_normalize_host(value) for value in self.allowed_hosts)
        if not allowed_hosts:
            raise ValueError("at least one exact Host value is required")
        public_origin = _normalize_origin(self.public_origin)
        if urlsplit(public_origin).netloc.lower() not in allowed_hosts:
            raise ValueError("public origin Host must be included in allowed_hosts")
        if any(not _is_exact_loopback_authority(value) for value in allowed_hosts):
            raise ValueError("allowed_hosts may contain only 127.0.0.1 or ::1")
        if not _is_exact_loopback_authority(urlsplit(public_origin).netloc):
            raise ValueError("public_origin must use 127.0.0.1 or ::1")
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "bind_host", bind_host)
        object.__setattr__(self, "allowed_hosts", allowed_hosts)
        object.__setattr__(self, "public_origin", public_origin)
        if self.static_dir is not None:
            object.__setattr__(self, "static_dir", Path(self.static_dir).expanduser())


@dataclass(frozen=True, slots=True)
class SecurityFailure(Exception):
    code: str
    message: str
    status_code: int


def validate_request_transport(
    request: Request,
    *,
    settings: ServerSettings,
    sessions: ControlSessionManager,
) -> None:
    """Validate Host and every non-GET JSON transport before route dispatch."""

    supplied_host = request.headers.get("host")
    try:
        normalized_host = _normalize_host(supplied_host)
    except ValueError as exc:
        raise SecurityFailure(
            "invalid_host",
            "The request Host is not allowed.",
            400,
        ) from exc
    if normalized_host not in settings.allowed_hosts:
        raise SecurityFailure(
            "invalid_host",
            "The request Host is not allowed.",
            400,
        )

    if request.method == "OPTIONS" and request.url.path.startswith("/api/v1"):
        raise SecurityFailure(
            "cors_disabled",
            "Cross-origin preflight is not enabled.",
            403,
        )
    if request.method not in _MUTATING_METHODS:
        return

    _require_json_content_type(request)
    _require_same_origin(request, settings.public_origin)

    path = request.url.path.rstrip("/") or "/"
    if path == _SESSION_CREATE_PATH:
        return
    if path.endswith(_READ_ONLY_POST_SUFFIX):
        return

    session_id = request.headers.get(CONTROL_SESSION_HEADER)
    try:
        sessions.require_valid(session_id)
    except InvalidControlSession as exc:
        raise SecurityFailure(
            "invalid_control_session",
            f"A valid {CONTROL_SESSION_HEADER} header is required.",
            401,
        ) from exc

    if path.startswith(_OPERATOR_PATH_PREFIX):
        if settings.profile is ServerProfile.READ_ONLY:
            raise SecurityFailure(
                "profile_read_only",
                "The read_only server profile does not permit an operator.",
                403,
            )
        return

    if settings.profile is ServerProfile.READ_ONLY:
        raise SecurityFailure(
            "profile_read_only",
            "The read_only server profile does not permit writes.",
            403,
        )
    try:
        sessions.require_operator(session_id)
    except OperatorAuthorityDenied as exc:
        raise SecurityFailure(
            "operator_required",
            "The current control session does not hold the operator slot.",
            403,
        ) from exc


def _require_json_content_type(request: Request) -> None:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise SecurityFailure(
            "json_required",
            "Non-GET API requests require Content-Type application/json.",
            415,
        )


def _require_same_origin(request: Request, public_origin: str) -> None:
    if request.headers.get("origin") != public_origin:
        raise SecurityFailure(
            "origin_denied",
            "The request Origin does not match the configured local origin.",
            403,
        )
    referer = request.headers.get("referer")
    if not referer:
        raise SecurityFailure(
            "referer_required",
            "A same-origin Referer is required for non-GET API requests.",
            403,
        )
    expected = urlsplit(public_origin)
    supplied = urlsplit(referer)
    if (
        supplied.scheme.lower() != expected.scheme.lower()
        or supplied.netloc.lower() != expected.netloc.lower()
        or supplied.username is not None
        or supplied.password is not None
    ):
        raise SecurityFailure(
            "referer_denied",
            "The request Referer does not match the configured local origin.",
            403,
        )
    if request.headers.get("sec-fetch-site") != "same-origin":
        raise SecurityFailure(
            "fetch_site_denied",
            "Sec-Fetch-Site must be same-origin for non-GET API requests.",
            403,
        )


def _normalize_origin(value: object) -> str:
    if not isinstance(value, str) or not value or value.endswith("/"):
        raise ValueError("public_origin must be an exact origin without a trailing slash")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("public_origin must contain only scheme and authority")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _normalize_host(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Host is required")
    normalized = value.strip().lower()
    if (
        not normalized
        or normalized != value.lower()
        or any(character.isspace() for character in normalized)
        or any(character in normalized for character in "/\\,@")
    ):
        raise ValueError("Host is invalid")
    parsed = urlsplit(f"//{normalized}")
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
    ):
        raise ValueError("Host is invalid")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Host port is invalid") from exc
    return normalized


def _loopback_bind_host(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized not in {"127.0.0.1", "::1"}:
        raise ValueError("bind_host must be exactly 127.0.0.1 or ::1")
    return normalized


def _is_exact_loopback_authority(value: str) -> bool:
    parsed = urlsplit(f"//{value}")
    hostname = parsed.hostname
    if hostname is None:
        return False
    try:
        address = ip_address(hostname)
    except ValueError:
        return False
    return str(address) in {"127.0.0.1", "::1"}
