from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import ValidationFailed


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationFailed(details={"field": field})
    return text


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field=field)


def _execute(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValidationFailed(details={"field": "execute"})
    return value


@dataclass(frozen=True, slots=True)
class PresentationPackageRequest:
    site_dir: Path
    output_dir: Path
    site_id: str
    desktop_visual_check: str
    mobile_visual_check: str
    link_check: str
    state_dir: Path | None = None
    entry_path: str = "index.html"
    revision: str | None = None
    publisher_kind: str = "local"
    base_url: str | None = None
    execute: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "site_dir", Path(self.site_dir).expanduser())
        object.__setattr__(self, "output_dir", Path(self.output_dir).expanduser())
        object.__setattr__(
            self,
            "site_id",
            _required_text(self.site_id, field="site_id"),
        )
        object.__setattr__(
            self,
            "entry_path",
            _required_text(self.entry_path, field="entry_path"),
        )
        object.__setattr__(
            self,
            "desktop_visual_check",
            _required_text(
                self.desktop_visual_check,
                field="desktop_visual_check",
            ),
        )
        object.__setattr__(
            self,
            "mobile_visual_check",
            _required_text(
                self.mobile_visual_check,
                field="mobile_visual_check",
            ),
        )
        object.__setattr__(
            self,
            "link_check",
            _required_text(self.link_check, field="link_check"),
        )
        publisher_kind = _required_text(
            self.publisher_kind,
            field="publisher_kind",
        )
        if publisher_kind not in {"local", "github-pages"}:
            raise ValidationFailed(details={"field": "publisher_kind"})
        object.__setattr__(self, "publisher_kind", publisher_kind)
        object.__setattr__(
            self,
            "revision",
            _optional_text(self.revision, field="revision"),
        )
        object.__setattr__(
            self,
            "base_url",
            _optional_text(self.base_url, field="base_url"),
        )
        object.__setattr__(self, "execute", _execute(self.execute))
        if self.state_dir is not None:
            object.__setattr__(self, "state_dir", Path(self.state_dir).expanduser())


@dataclass(frozen=True, slots=True)
class PresentationRollbackRequest:
    output_dir: Path
    state_dir: Path | None = None
    revision: str | None = None
    execute: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_dir", Path(self.output_dir).expanduser())
        if self.state_dir is not None:
            object.__setattr__(self, "state_dir", Path(self.state_dir).expanduser())
        object.__setattr__(
            self,
            "revision",
            _optional_text(self.revision, field="revision"),
        )
        object.__setattr__(self, "execute", _execute(self.execute))


@dataclass(frozen=True, slots=True)
class PresentationReadbackRequest:
    output_dir: Path
    state_dir: Path | None = None
    receipt_url: str | None = None
    retries: int = 3
    retry_delay_seconds: float = 1.0
    execute: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_dir", Path(self.output_dir).expanduser())
        if self.state_dir is not None:
            object.__setattr__(self, "state_dir", Path(self.state_dir).expanduser())
        receipt_url = _optional_text(self.receipt_url, field="receipt_url")
        if receipt_url is not None and not _is_absolute_http_url(receipt_url):
            raise ValidationFailed(details={"field": "receipt_url"})
        if not isinstance(self.retries, int) or isinstance(self.retries, bool):
            raise ValidationFailed(details={"field": "retries"})
        if self.retries < 1 or self.retries > 10:
            raise ValidationFailed(details={"field": "retries"})
        if not isinstance(self.retry_delay_seconds, (int, float)) or isinstance(
            self.retry_delay_seconds,
            bool,
        ):
            raise ValidationFailed(details={"field": "retry_delay_seconds"})
        if self.retry_delay_seconds < 0 or self.retry_delay_seconds > 30:
            raise ValidationFailed(details={"field": "retry_delay_seconds"})
        object.__setattr__(self, "receipt_url", receipt_url)
        object.__setattr__(self, "execute", _execute(self.execute))


@dataclass(frozen=True, slots=True)
class PresentationDeploymentContract:
    artifact_root: str
    provider_owns_deploy_receipt: bool
    loopx_receipt_readback: str


@dataclass(frozen=True, slots=True)
class PresentationPublisher:
    kind: str
    base_url: str | None
    latest_url: str
    revision_url: str
    http_readback_required: bool
    deployment_contract: PresentationDeploymentContract | None = None


@dataclass(frozen=True, slots=True)
class PresentationValidation:
    desktop_visual_check: str
    mobile_visual_check: str
    link_check: str


@dataclass(frozen=True, slots=True)
class PresentationPackageResult:
    schema_version: str
    mode: str
    dry_run: bool
    write_required: bool
    write_performed: bool
    semantic_noop: bool
    requested_revision: str
    active_revision: str
    previous_revision: str | None
    semantic_digest: str
    publisher: PresentationPublisher
    output_dir: str
    manifest_path: str
    receipt_path: str
    state_receipt_log: str
    validation: PresentationValidation
    ok: bool = True


@dataclass(frozen=True, slots=True)
class PresentationRollbackResult:
    schema_version: str
    mode: str
    dry_run: bool
    write_required: bool
    write_performed: bool
    from_revision: str
    active_revision: str
    semantic_digest: str
    publisher: PresentationPublisher
    output_dir: str
    manifest_path: str
    receipt_path: str
    state_receipt_log: str
    ok: bool = True


@dataclass(frozen=True, slots=True)
class PresentationReadbackResult:
    schema_version: str
    mode: str
    dry_run: bool
    verified: bool
    receipt_url: str
    attempts: int
    site_id: str
    revision: str
    semantic_digest: str
    state_receipt_log: str
    ok: bool = True


def _is_absolute_http_url(value: str) -> bool:
    if value != value.strip() or any(char.isspace() for char in value):
        return False
    prefix = next(
        (candidate for candidate in ("https://", "http://") if value.startswith(candidate)),
        None,
    )
    if prefix is None:
        return False
    remainder = value[len(prefix) :]
    authority = remainder
    for delimiter in ("/", "?", "#"):
        authority = authority.split(delimiter, 1)[0]
    return bool(authority)
