"""Console entrypoint for the optional loopback HTTP adapter."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from loopx.paths import default_registry_path

from .factory import create_app
from .security import ServerProfile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loopx-http-server",
        description="Serve the typed LoopX v1 API on an exact loopback address.",
    )
    parser.add_argument("--registry", default=str(default_registry_path()))
    parser.add_argument("--runtime-root")
    parser.add_argument(
        "--profile",
        choices=[item.value for item in ServerProfile],
        default=ServerProfile.READ_ONLY.value,
    )
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "::1"),
        default="127.0.0.1",
        help="Exact loopback bind address; LAN and wildcard binds are forbidden.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--origin", help="Exact numeric-loopback browser origin.")
    parser.add_argument("--static-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = create_app(
        profile=args.profile,
        registry_path=Path(args.registry),
        runtime_root_override=args.runtime_root,
        bind_host=args.host,
        port=args.port,
        public_origin=args.origin,
        static_dir=args.static_dir,
    )
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - packaging diagnostic
        raise SystemExit(
            "loopx-http-server requires the optional HTTP dependencies; "
            "install loopx[http]"
        ) from exc
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
