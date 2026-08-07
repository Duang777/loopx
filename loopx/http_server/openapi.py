"""Offline FastAPI schema generation and canonical TypeScript drift checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .factory import create_app


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_ROOT = (
    REPOSITORY_ROOT
    / "apps"
    / "presentation"
    / "dashboard"
    / "src"
    / "api"
    / "generated"
)
SCHEMA_PATH = GENERATED_ROOT / "openapi.json"
TYPES_PATH = GENERATED_ROOT / "schema.d.ts"
CLIENT_PATH = GENERATED_ROOT / "client.ts"


def generate_openapi_schema() -> dict[str, Any]:
    schema = create_app().openapi()
    if schema.get("openapi") != "3.1.0":
        raise RuntimeError("HTTP schema must remain OpenAPI 3.1.0")
    return schema


def schema_text(schema: Mapping[str, Any]) -> str:
    return json.dumps(
        schema,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def client_text(schema: Mapping[str, Any]) -> str:
    digest = _schema_digest(schema)
    return f'''/**
 * Generated LoopX v1 openapi-fetch wrapper. Do not edit.
 * OpenAPI-SHA256: {digest}
 */
import createClient, {{ type Middleware }} from "openapi-fetch";
import type {{ paths }} from "./schema";

export const LOOPX_CONTROL_SESSION_HEADER = "X-LoopX-Control-Session" as const;

export interface LoopXClientOptions {{
  baseUrl?: string;
}}

export function ifNoneMatch(etag: string | null | undefined): HeadersInit {{
  return etag ? {{ "If-None-Match": etag }} : {{}};
}}

export function createLoopXApiClient(options: LoopXClientOptions = {{}}) {{
  let controlSessionId: string | null = null;
  const controlSessionMiddleware: Middleware = {{
    async onRequest({{ request }}) {{
      if (controlSessionId) {{
        request.headers.set(LOOPX_CONTROL_SESSION_HEADER, controlSessionId);
      }} else {{
        request.headers.delete(LOOPX_CONTROL_SESSION_HEADER);
      }}
      return request;
    }},
  }};
  const client = createClient<paths>({{ baseUrl: options.baseUrl ?? "" }});
  client.use(controlSessionMiddleware);
  return {{
    client,
    setControlSession(value: string | null) {{
      controlSessionId = value;
    }},
  }};
}}

export type LoopXApiClient = ReturnType<typeof createLoopXApiClient>;
'''


def write_schema_and_client() -> None:
    schema = generate_openapi_schema()
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(schema_text(schema), encoding="utf-8")
    CLIENT_PATH.write_text(client_text(schema), encoding="utf-8")


def check_schema_and_client() -> tuple[bool, tuple[str, ...]]:
    schema = generate_openapi_schema()
    return _check_expected(
        {
            SCHEMA_PATH: schema_text(schema),
            CLIENT_PATH: client_text(schema),
        }
    )


def check_official_artifacts() -> tuple[bool, tuple[str, ...]]:
    """Compare schema/client and upstream ``openapi-typescript`` output."""

    clean, existing_drift = check_schema_and_client()
    drift = list(existing_drift)
    executable = shutil.which("openapi-typescript")
    if executable is None:
        raise RuntimeError(
            "openapi-typescript is required for the canonical API drift check"
        )
    schema = generate_openapi_schema()
    with tempfile.TemporaryDirectory(prefix="loopx-openapi-") as temporary:
        temporary_root = Path(temporary)
        input_path = temporary_root / "openapi.json"
        output_path = temporary_root / "schema.d.ts"
        input_path.write_text(schema_text(schema), encoding="utf-8")
        subprocess.run(
            [executable, str(input_path), "-o", str(output_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        generated = output_path.read_text(encoding="utf-8")
    try:
        current_types = TYPES_PATH.read_text(encoding="utf-8")
    except OSError:
        current_types = ""
    if current_types != generated:
        drift.append(str(TYPES_PATH.relative_to(REPOSITORY_ROOT)))
    return clean and not drift, tuple(dict.fromkeys(drift))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write-schema-client", action="store_true")
    action.add_argument("--check-schema-client", action="store_true")
    action.add_argument("--check-official", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.write_schema_client:
        write_schema_and_client()
        print(f"wrote OpenAPI schema and client under {GENERATED_ROOT}")
        return 0
    try:
        clean, drift = (
            check_official_artifacts()
            if args.check_official
            else check_schema_and_client()
        )
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc))
        return 2
    if clean:
        print("generated API artifacts are in sync")
        return 0
    print("generated API drift detected:")
    for path in drift:
        print(f"- {path}")
    return 1


def _check_expected(expected: Mapping[Path, str]) -> tuple[bool, tuple[str, ...]]:
    drift: list[str] = []
    for path, content in expected.items():
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            drift.append(str(path.relative_to(REPOSITORY_ROOT)))
            continue
        if current != content:
            drift.append(str(path.relative_to(REPOSITORY_ROOT)))
    return not drift, tuple(drift)


def _schema_digest(schema: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        schema,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
