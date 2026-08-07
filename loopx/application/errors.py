from __future__ import annotations

from types import MappingProxyType
from typing import ClassVar, Mapping


class ApplicationError(Exception):
    """Stable typed failure raised by the application facade."""

    code: ClassVar[str] = "application_error"
    default_message: ClassVar[str] = "The LoopX application request failed."
    retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = type(self).code
        self.message = message or type(self).default_message
        self.details = MappingProxyType(dict(details or {}))
        self.retryable = type(self).retryable
        super().__init__(self.message)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "retryable": self.retryable,
        }


class GoalNotFound(ApplicationError):
    code = "goal_not_found"
    default_message = "The requested goal was not found."


class GoalRouteConflict(ApplicationError):
    code = "goal_route_conflict"
    default_message = "The canonical goal route could not be validated."


class ValidationFailed(ApplicationError):
    code = "validation_failed"
    default_message = "The application request is invalid."


class CapabilityUnavailable(ApplicationError):
    code = "capability_unavailable"
    default_message = "The requested capability is unavailable."


class AuthorityDenied(ApplicationError):
    code = "authority_denied"
    default_message = "The requested operation is outside the caller's authority."


class RevisionConflict(ApplicationError):
    code = "revision_conflict"
    default_message = "The expected revision does not match current state."
    retryable = True


class StateUnavailable(ApplicationError):
    code = "state_unavailable"
    default_message = "Required LoopX state is unavailable."
    retryable = True
