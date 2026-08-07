"""In-memory viewer/operator coordination for one HTTP server process."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass


_TOKEN_PREFIX = "lxcs1_"


class ControlSessionError(Exception):
    code = "control_session_error"


class InvalidControlSession(ControlSessionError):
    code = "invalid_control_session"


class OperatorSlotOccupied(ControlSessionError):
    code = "operator_slot_occupied"


class OperatorAuthorityDenied(ControlSessionError):
    code = "operator_authority_denied"


@dataclass(frozen=True, slots=True)
class OperatorSnapshot:
    role: str
    operator_slot_occupied: bool
    changed: bool


class ControlSessionManager:
    """Issue stateless session ids while retaining only the single operator slot.

    A per-process HMAC secret makes session ids self-authenticating.  Restarting
    the server replaces that secret and therefore invalidates every prior page
    session without keeping a viewer registry or durable UI identity.
    """

    __slots__ = ("_secret", "_operator_session_id", "_lock")

    def __init__(self, *, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("control-session secret must contain at least 32 bytes")
        self._operator_session_id: str | None = None
        self._lock = threading.RLock()

    @property
    def operator_session_id(self) -> str | None:
        with self._lock:
            return self._operator_session_id

    def issue(self) -> str:
        nonce = _urlsafe(secrets.token_bytes(32))
        unsigned = f"{_TOKEN_PREFIX}{nonce}"
        signature = _urlsafe(
            hmac.new(self._secret, unsigned.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{unsigned}.{signature}"

    def is_valid(self, session_id: object) -> bool:
        if not isinstance(session_id, str) or len(session_id) > 256:
            return False
        try:
            unsigned, supplied = session_id.rsplit(".", 1)
        except ValueError:
            return False
        if not unsigned.startswith(_TOKEN_PREFIX) or not supplied:
            return False
        expected = _urlsafe(
            hmac.new(self._secret, unsigned.encode("ascii"), hashlib.sha256).digest()
        )
        return hmac.compare_digest(supplied, expected)

    def require_valid(self, session_id: object) -> str:
        if not self.is_valid(session_id):
            raise InvalidControlSession
        return str(session_id)

    def role(self, session_id: object) -> str:
        normalized = self.require_valid(session_id)
        with self._lock:
            return (
                "operator"
                if normalized == self._operator_session_id
                else "viewer"
            )

    def snapshot(self, session_id: object, *, changed: bool = False) -> OperatorSnapshot:
        normalized = self.require_valid(session_id)
        with self._lock:
            return OperatorSnapshot(
                role=(
                    "operator"
                    if normalized == self._operator_session_id
                    else "viewer"
                ),
                operator_slot_occupied=self._operator_session_id is not None,
                changed=changed,
            )

    def acquire(self, session_id: object) -> OperatorSnapshot:
        normalized = self.require_valid(session_id)
        with self._lock:
            if self._operator_session_id is None:
                self._operator_session_id = normalized
                changed = True
            elif self._operator_session_id == normalized:
                changed = False
            else:
                raise OperatorSlotOccupied
            return OperatorSnapshot(
                role="operator",
                operator_slot_occupied=True,
                changed=changed,
            )

    def takeover(self, session_id: object) -> OperatorSnapshot:
        normalized = self.require_valid(session_id)
        with self._lock:
            changed = self._operator_session_id != normalized
            self._operator_session_id = normalized
            return OperatorSnapshot(
                role="operator",
                operator_slot_occupied=True,
                changed=changed,
            )

    def release(self, session_id: object) -> OperatorSnapshot:
        normalized = self.require_valid(session_id)
        with self._lock:
            if normalized != self._operator_session_id:
                raise OperatorAuthorityDenied
            self._operator_session_id = None
            return OperatorSnapshot(
                role="viewer",
                operator_slot_occupied=False,
                changed=True,
            )

    def require_operator(self, session_id: object) -> str:
        normalized = self.require_valid(session_id)
        with self._lock:
            if normalized != self._operator_session_id:
                raise OperatorAuthorityDenied
        return normalized


def _urlsafe(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
