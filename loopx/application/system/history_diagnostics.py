"""Typed public-safe projections for local compact-history diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loopx.control_plane.runtime.trajectory_hygiene import (
    build_trajectory_hygiene_summary,
)
from loopx.history import collect_history, inspect_index_duplicates, load_registry
from loopx.paths import resolve_runtime_root
from loopx.runtime import validate_goal_id_path_segment

from ..contracts import Profile
from ..errors import StateUnavailable, ValidationFailed


INDEX_DUPLICATE_INSPECTION_OPERATION = (
    "application.system.history.inspect_index_duplicates"
)
TRAJECTORY_HYGIENE_OPERATION = "application.system.history.trajectory_hygiene"
_INDEX_DUPLICATE_KINDS = {
    "artifact_identity_collision",
    "plain_duplicate",
    "reward_overlay",
    "structured_artifact_bundle",
}
_INDEX_DUPLICATE_SEVERITIES = {"info", "warning"}
_TRAJECTORY_CHANNELS = {
    "controller",
    "human_decision",
    "outcome",
    "task_event",
}


@dataclass(frozen=True, slots=True)
class IndexDuplicateInspectionRequest:
    goal_id: str | None = None
    limit: int = 10

    def __post_init__(self) -> None:
        if self.goal_id is not None:
            if not isinstance(self.goal_id, str):
                raise ValidationFailed(details={"field": "goal_id"})
            try:
                goal_id = validate_goal_id_path_segment(self.goal_id)
            except (TypeError, ValueError) as exc:
                raise ValidationFailed(details={"field": "goal_id"}) from exc
            object.__setattr__(self, "goal_id", goal_id)
        _validate_limit(self.limit)


@dataclass(frozen=True, slots=True)
class IndexDuplicateGroup:
    goal_id: str
    duplicate_kind: str
    severity: str
    raw_row_count: int
    duplicate_row_count: int
    line_count: int
    reward_overlay_row_count: int
    classification_count: int
    json_artifact_available: bool
    markdown_artifact_available: bool


@dataclass(frozen=True, slots=True)
class IndexDuplicateInspectionResult:
    operation_id: str
    goal_filter: str | None
    checked_goal_count: int
    raw_index_record_count: int
    duplicate_group_count: int
    duplicate_row_count: int
    groups: tuple[IndexDuplicateGroup, ...]
    truncated: bool
    limit: int


@dataclass(frozen=True, slots=True)
class TrajectoryHygieneRequest:
    goal_id: str
    limit: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.goal_id, str):
            raise ValidationFailed(details={"field": "goal_id"})
        try:
            goal_id = validate_goal_id_path_segment(self.goal_id)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(details={"field": "goal_id"}) from exc
        _validate_limit(self.limit)
        object.__setattr__(self, "goal_id", goal_id)


@dataclass(frozen=True, slots=True)
class TrajectoryChannelCount:
    channel: str
    count: int


@dataclass(frozen=True, slots=True)
class TrajectoryHygieneMetrics:
    controller_event_ratio: float
    compact_controller_char_ratio: float
    non_material_event_ratio: float
    learning_candidate_count: int
    learning_action_coverage: float
    learning_outcome_coverage: float
    decision_anchor_coverage: float
    duplicate_learning_action_ratio: float


@dataclass(frozen=True, slots=True)
class TrajectoryTrainingBoundary:
    raw_session_read: bool
    raw_trajectory_read: bool
    run_artifact_read: bool
    compact_index_only: bool
    seed_model_training_eligible: bool


@dataclass(frozen=True, slots=True)
class TrajectoryHygieneResult:
    operation_id: str
    goal_filter: str
    compact_history_row_count: int
    goal_count: int
    source: str
    channel_counts: tuple[TrajectoryChannelCount, ...]
    metrics: TrajectoryHygieneMetrics
    training_boundary: TrajectoryTrainingBoundary


class HistoryDiagnosticsProvider(Protocol):
    def inspect_index_duplicates(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: IndexDuplicateInspectionRequest,
    ) -> Mapping[str, object]: ...

    def trajectory_hygiene(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: TrajectoryHygieneRequest,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class CoreHistoryDiagnosticsProvider:
    def inspect_index_duplicates(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: IndexDuplicateInspectionRequest,
    ) -> Mapping[str, object]:
        return inspect_index_duplicates(
            registry_path=registry_path,
            runtime_root_override=runtime_root_override,
            goal_id=request.goal_id,
            limit=request.limit,
        )

    def trajectory_hygiene(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: TrajectoryHygieneRequest,
    ) -> Mapping[str, object]:
        registry = load_registry(registry_path)
        runtime_root = resolve_runtime_root(
            registry,
            runtime_root_override,
            registry_path=registry_path,
        )
        history = collect_history(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=request.goal_id,
            limit=request.limit,
        )
        return build_trajectory_hygiene_summary(history)


@dataclass(frozen=True, slots=True)
class HistoryDiagnosticsService:
    registry_path: Path
    runtime_root_override: str | None
    profile: Profile
    provider: HistoryDiagnosticsProvider = CoreHistoryDiagnosticsProvider()

    def inspect_index_duplicates(
        self,
        request: IndexDuplicateInspectionRequest,
    ) -> IndexDuplicateInspectionResult:
        if not isinstance(request, IndexDuplicateInspectionRequest):
            raise ValidationFailed(details={"field": "request"})
        payload = self._call(
            lambda: self.provider.inspect_index_duplicates(
                registry_path=self.registry_path,
                runtime_root_override=self.runtime_root_override,
                request=request,
            ),
            operation_id=INDEX_DUPLICATE_INSPECTION_OPERATION,
        )
        return _project_duplicate_result(request, payload)

    def trajectory_hygiene(
        self,
        request: TrajectoryHygieneRequest,
    ) -> TrajectoryHygieneResult:
        if not isinstance(request, TrajectoryHygieneRequest):
            raise ValidationFailed(details={"field": "request"})
        payload = self._call(
            lambda: self.provider.trajectory_hygiene(
                registry_path=self.registry_path,
                runtime_root_override=self.runtime_root_override,
                request=request,
            ),
            operation_id=TRAJECTORY_HYGIENE_OPERATION,
        )
        return _project_trajectory_result(request, payload)

    def _call(
        self,
        call: Callable[[], Mapping[str, object]],
        *,
        operation_id: str,
    ) -> Mapping[str, object]:
        try:
            payload = call()
        except ValueError as exc:
            raise ValidationFailed(str(exc), details={"operation_id": operation_id}) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "history_diagnostics", "cause": type(exc).__name__}
            ) from exc
        if not isinstance(payload, Mapping) or payload.get("ok") is not True:
            raise StateUnavailable(details={"resource": "history_diagnostics"})
        return payload


def _project_duplicate_result(
    request: IndexDuplicateInspectionRequest,
    payload: Mapping[str, object],
) -> IndexDuplicateInspectionResult:
    groups = tuple(
        _project_duplicate_group(value, goal_filter=request.goal_id)
        for value in _mapping_rows(payload.get("groups"), field="groups")
    )
    goal_filter = _optional_text(payload.get("goal_filter"), field="goal_filter")
    if goal_filter != request.goal_id:
        raise _invalid_payload("goal_filter")
    limit = _required_int(payload.get("limit"), field="limit")
    if limit != request.limit:
        raise _invalid_payload("limit")
    return IndexDuplicateInspectionResult(
        operation_id=INDEX_DUPLICATE_INSPECTION_OPERATION,
        goal_filter=goal_filter,
        checked_goal_count=_required_int(
            payload.get("checked_goal_count"), field="checked_goal_count"
        ),
        raw_index_record_count=_required_int(
            payload.get("raw_index_records"), field="raw_index_records"
        ),
        duplicate_group_count=_required_int(
            payload.get("duplicate_group_count"), field="duplicate_group_count"
        ),
        duplicate_row_count=_required_int(
            payload.get("duplicate_row_count"), field="duplicate_row_count"
        ),
        groups=groups,
        truncated=_required_bool(payload.get("truncated"), field="truncated"),
        limit=limit,
    )


def _project_duplicate_group(
    value: Mapping[str, object],
    *,
    goal_filter: str | None,
) -> IndexDuplicateGroup:
    line_numbers = value.get("line_numbers")
    classifications = value.get("classifications")
    if not isinstance(line_numbers, (list, tuple)) or any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0
        for item in line_numbers
    ):
        raise _invalid_payload("groups.line_numbers")
    if not isinstance(classifications, (list, tuple)) or any(
        not isinstance(item, str) for item in classifications
    ):
        raise _invalid_payload("groups.classifications")
    goal_id = _required_goal_id(value.get("goal_id"), field="groups.goal_id")
    if goal_filter is not None and goal_id != goal_filter:
        raise _invalid_payload("groups.goal_id")
    return IndexDuplicateGroup(
        goal_id=goal_id,
        duplicate_kind=_required_choice(
            value.get("duplicate_kind"),
            field="groups.duplicate_kind",
            choices=_INDEX_DUPLICATE_KINDS,
        ),
        severity=_required_choice(
            value.get("severity"),
            field="groups.severity",
            choices=_INDEX_DUPLICATE_SEVERITIES,
        ),
        raw_row_count=_required_int(value.get("raw_rows"), field="groups.raw_rows"),
        duplicate_row_count=_required_int(
            value.get("duplicate_rows"), field="groups.duplicate_rows"
        ),
        line_count=len(line_numbers),
        reward_overlay_row_count=_required_int(
            value.get("reward_overlay_rows"), field="groups.reward_overlay_rows"
        ),
        classification_count=len(classifications),
        json_artifact_available=_required_bool(
            value.get("json_exists"), field="groups.json_exists"
        ),
        markdown_artifact_available=_required_bool(
            value.get("markdown_exists"), field="groups.markdown_exists"
        ),
    )


def _project_trajectory_result(
    request: TrajectoryHygieneRequest,
    payload: Mapping[str, object],
) -> TrajectoryHygieneResult:
    sample = _required_mapping(payload.get("sample"), field="sample")
    metrics = _required_mapping(payload.get("metrics"), field="metrics")
    boundary = _required_mapping(
        payload.get("training_boundary"), field="training_boundary"
    )
    channel_counts = _required_mapping(
        payload.get("channel_counts"), field="channel_counts"
    )
    goal_filter = _required_text(payload.get("goal_filter"), field="goal_filter")
    if goal_filter != request.goal_id:
        raise _invalid_payload("goal_filter")
    return TrajectoryHygieneResult(
        operation_id=TRAJECTORY_HYGIENE_OPERATION,
        goal_filter=goal_filter,
        compact_history_row_count=_required_int(
            sample.get("compact_history_row_count"),
            field="sample.compact_history_row_count",
        ),
        goal_count=_required_int(sample.get("goal_count"), field="sample.goal_count"),
        source=_required_source(sample.get("source")),
        channel_counts=tuple(
            TrajectoryChannelCount(
                channel=_required_choice(
                    key,
                    field="channel_counts.channel",
                    choices=_TRAJECTORY_CHANNELS,
                ),
                count=_required_int(value, field="channel_counts.count"),
            )
            for key, value in sorted(channel_counts.items())
        ),
        metrics=TrajectoryHygieneMetrics(
            controller_event_ratio=_required_ratio(
                metrics.get("controller_event_ratio"),
                field="metrics.controller_event_ratio",
            ),
            compact_controller_char_ratio=_required_ratio(
                metrics.get("compact_controller_char_ratio"),
                field="metrics.compact_controller_char_ratio",
            ),
            non_material_event_ratio=_required_ratio(
                metrics.get("non_material_event_ratio"),
                field="metrics.non_material_event_ratio",
            ),
            learning_candidate_count=_required_int(
                metrics.get("learning_candidate_count"),
                field="metrics.learning_candidate_count",
            ),
            learning_action_coverage=_required_ratio(
                metrics.get("learning_action_coverage"),
                field="metrics.learning_action_coverage",
            ),
            learning_outcome_coverage=_required_ratio(
                metrics.get("learning_outcome_coverage"),
                field="metrics.learning_outcome_coverage",
            ),
            decision_anchor_coverage=_required_ratio(
                metrics.get("decision_anchor_coverage"),
                field="metrics.decision_anchor_coverage",
            ),
            duplicate_learning_action_ratio=_required_ratio(
                metrics.get("duplicate_learning_action_ratio"),
                field="metrics.duplicate_learning_action_ratio",
            ),
        ),
        training_boundary=TrajectoryTrainingBoundary(
            raw_session_read=_required_bool(
                boundary.get("raw_session_read"),
                field="training_boundary.raw_session_read",
            ),
            raw_trajectory_read=_required_bool(
                boundary.get("raw_trajectory_read"),
                field="training_boundary.raw_trajectory_read",
            ),
            run_artifact_read=_required_bool(
                boundary.get("run_artifact_read"),
                field="training_boundary.run_artifact_read",
            ),
            compact_index_only=_required_bool(
                boundary.get("compact_index_only"),
                field="training_boundary.compact_index_only",
            ),
            seed_model_training_eligible=_required_bool(
                boundary.get("seed_model_training_eligible"),
                field="training_boundary.seed_model_training_eligible",
            ),
        ),
    )


def _validate_limit(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationFailed(details={"field": "limit"})


def _mapping_rows(
    value: object,
    *,
    field: str,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise _invalid_payload(field)
    return tuple(value)  # type: ignore[return-value]


def _required_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid_payload(field)
    return value


def _required_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_payload(field)
    return value


def _required_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_payload(field)
    return value


def _required_ratio(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid_payload(field)
    ratio = float(value)
    if ratio < 0 or ratio > 1:
        raise _invalid_payload(field)
    return ratio


def _required_source(value: object) -> str:
    source = _required_text(value, field="sample.source")
    if source != "public_safe_compact_run_index":
        raise _invalid_payload("sample.source")
    return source


def _required_goal_id(value: object, *, field: str) -> str:
    goal_id = _required_text(value, field=field)
    try:
        return validate_goal_id_path_segment(goal_id)
    except (TypeError, ValueError) as exc:
        raise _invalid_payload(field) from exc


def _required_choice(
    value: object,
    *,
    field: str,
    choices: set[str],
) -> str:
    text = _required_text(value, field=field)
    if text not in choices:
        raise _invalid_payload(field)
    return text


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field=field)


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_payload(field)
    return value.strip()


def _invalid_payload(field: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "history_diagnostics",
            "cause": "invalid_payload",
            "field": field,
        }
    )
