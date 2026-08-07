"""FastAPI factory for the loopback-only LoopX HTTP adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from loopx.application import (
    ApplicationContext,
    ApplicationError,
    AuthorityDenied,
    CapabilityUnavailable,
    GoalNotFound,
    GoalRouteConflict,
    LoopXApplication,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
)
from loopx.paths import default_registry_path

from .errors import HttpAdapterError
from .routes import build_api_router
from .schemas import ErrorResponse
from .security import (
    SecurityFailure,
    ServerProfile,
    ServerSettings,
    validate_request_transport,
)
from .serialization import public_safe_payload
from .sessions import ControlSessionManager


def create_app(
    application: Any | None = None,
    *,
    profile: ServerProfile | str = ServerProfile.READ_ONLY,
    registry_path: Path | str | None = None,
    runtime_root_override: str | None = None,
    bind_host: str = "127.0.0.1",
    port: int = 8765,
    public_origin: str | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
    static_dir: Path | str | None = None,
    session_manager: ControlSessionManager | None = None,
) -> FastAPI:
    """Create one process-local HTTP adapter without reading mutable state."""

    server_profile = ServerProfile.parse(profile)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    authority = f"[{bind_host}]:{port}" if bind_host == "::1" else f"{bind_host}:{port}"
    settings = ServerSettings(
        profile=server_profile,
        bind_host=bind_host,
        allowed_hosts=frozenset(allowed_hosts or (authority,)),
        public_origin=public_origin or f"http://{authority}",
        static_dir=Path(static_dir).expanduser() if static_dir is not None else None,
    )
    loopx_application = application or LoopXApplication(
        ApplicationContext(
            registry_path=Path(registry_path or default_registry_path()),
            runtime_root_override=runtime_root_override,
            profile=server_profile.application_profile,
        )
    )
    _validate_application_profile(loopx_application, server_profile)

    app = FastAPI(
        title="LoopX Local HTTP API",
        version="1.0.0",
        description=(
            "Loopback-only typed adapter over LoopXApplication. "
            "It does not expose generic command dispatch or Turn execution."
        ),
        openapi_url="/api/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        openapi_version="3.1.0",
    )
    app.state.loopx_application = loopx_application
    app.state.loopx_http_settings = settings
    app.state.loopx_control_sessions = session_manager or ControlSessionManager()

    @app.middleware("http")
    async def enforce_local_transport(request: Request, call_next: Any) -> Any:
        try:
            validate_request_transport(
                request,
                settings=settings,
                sessions=app.state.loopx_control_sessions,
            )
        except SecurityFailure as exc:
            return _error_response(
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
            )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return _error_response(
            code=exc.code,
            message=exc.message,
            details=dict(exc.details),
            retryable=exc.retryable,
            status_code=_application_status(exc),
        )

    @app.exception_handler(HttpAdapterError)
    async def adapter_error_handler(
        _request: Request,
        exc: HttpAdapterError,
    ) -> JSONResponse:
        return _error_response(
            code=exc.code,
            message=exc.message,
            details=dict(exc.details),
            retryable=exc.retryable,
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = {
            "issues": [
                {
                    "location": [str(item) for item in issue.get("loc", ())],
                    "type": str(issue.get("type") or "invalid"),
                }
                for issue in exc.errors()
            ]
        }
        return _error_response(
            code="request_validation_failed",
            message="The HTTP request does not match the v1 schema.",
            details=details,
            status_code=422,
        )

    app.include_router(build_api_router())
    _install_static_routes(app)
    return app


def _validate_application_profile(application: Any, profile: ServerProfile) -> None:
    context = getattr(application, "context", None)
    application_profile = getattr(context, "profile", None)
    if application_profile is not None and application_profile is not profile.application_profile:
        raise ValueError("Application profile must match the HTTP server profile")


def _application_status(exc: ApplicationError) -> int:
    if isinstance(exc, GoalNotFound):
        return 404
    if isinstance(exc, (AuthorityDenied,)):
        return 403
    if isinstance(exc, ValidationFailed):
        return 422
    if isinstance(exc, (GoalRouteConflict, RevisionConflict, CapabilityUnavailable)):
        return 409
    if isinstance(exc, StateUnavailable):
        return 503
    return 500


def _error_response(
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, object] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    payload = ErrorResponse.model_validate(
        public_safe_payload(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or {},
                    "retryable": retryable,
                }
            }
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _install_static_routes(app: FastAPI) -> None:
    @app.get("/", include_in_schema=False)
    def static_index(request: Request) -> Any:
        return _static_response(request, "")

    @app.get("/{asset_path:path}", include_in_schema=False)
    def static_asset(request: Request, asset_path: str) -> Any:
        return _static_response(request, asset_path)


def _static_response(request: Request, asset_path: str) -> Any:
    if asset_path == "api" or asset_path.startswith("api/"):
        return _error_response(
            code="api_route_not_found",
            message="The requested API route does not exist for this method.",
            status_code=404,
        )
    settings: ServerSettings = request.app.state.loopx_http_settings
    root = settings.static_dir
    if root is None or not root.is_dir() or not (root / "index.html").is_file():
        return _error_response(
            code="static_assets_unavailable",
            message="The Dashboard build artifact is not available.",
            status_code=503,
            details={"recovery": "Build the Dashboard or configure --static-dir."},
        )
    resolved_root = root.resolve()
    candidate = (resolved_root / asset_path).resolve()
    if not candidate.is_relative_to(resolved_root):
        return _error_response(
            code="static_asset_not_found",
            message="The requested static asset was not found.",
            status_code=404,
        )
    if candidate.is_file():
        return FileResponse(candidate)
    if not Path(asset_path).suffix:
        return FileResponse(resolved_root / "index.html")
    return _error_response(
        code="static_asset_not_found",
        message="The requested static asset was not found.",
        status_code=404,
    )
