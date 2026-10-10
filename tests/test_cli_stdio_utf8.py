"""The shipped CLI must pin its own stdio to UTF-8.

`sys.stdin` / `sys.stdout` default to the host locale codec - `cp936` on a
zh-CN Windows host, and whatever ``PYTHONIOENCODING`` names elsewhere. Under
that codec the console script raises `UnicodeEncodeError` on non-ASCII output
and decodes UTF-8 stdin with the locale codec, so a non-ASCII title either
crashes the command or silently corrupts the request.

`test_loopx_text_io_utf8.py` and `test_runtime_subprocess_utf8.py` guard the
files and subprocesses LoopX opens; these tests cover the process's own
streams, which were the remaining locale-dependent surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# A codec the shipped CLI must not fall back to. `gbk` cannot encode the emoji
# title below, so a missing pin is a hard failure rather than a silent byte
# difference.
LOCALE_CODEC = "gbk"
EMOJI_TITLE = "🚀 修复 deploy"

_INTRO = "from loopx.entrypoint import main; raise SystemExit(main())"
_PREVIEW = (
    "--format",
    "json",
    "content-ops",
    "issue-fix-metadata-preview",
    "--url",
    "https://github.com/huangruiteng/loopx/issues/123",
)


def _metadata() -> bytes:
    return json.dumps({"number": 123, "state": "open", "title": EMOJI_TITLE}).encode("utf-8")


def _run_preview(
    runtime_root: Path, *metadata_args: str, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    environment = {
        **os.environ,
        "PYTHONIOENCODING": LOCALE_CODEC,
        "PYTHONUTF8": "0",
        "LOOPX_USAGE_PING": "0",
    }
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _INTRO,
            "--runtime-root",
            str(runtime_root),
            *_PREVIEW,
            *metadata_args,
        ],
        cwd=REPO_ROOT,
        env=environment,
        input=stdin,
        capture_output=True,
        timeout=180,
    )


def _title(payload_bytes: bytes) -> str:
    payload = json.loads(payload_bytes.decode("utf-8"))
    assert payload["ok"] is True
    return payload["issue_fix_intake"]["issue_metadata"]["title_summary"]


def test_non_ascii_stdout_survives_a_locale_codec(tmp_path: Path) -> None:
    """A non-ASCII title must not raise `UnicodeEncodeError` on gbk stdout."""

    metadata = tmp_path / "metadata.json"
    metadata.write_bytes(_metadata())

    result = _run_preview(tmp_path / "runtime", "--metadata-json", str(metadata))

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert _title(result.stdout) == EMOJI_TITLE


def test_utf8_stdin_is_not_decoded_with_the_locale_codec(tmp_path: Path) -> None:
    """`--metadata-json -` must read UTF-8 stdin, matching the file route."""

    stdin_result = _run_preview(
        tmp_path / "stdin-runtime", "--metadata-json", "-", stdin=_metadata()
    )
    metadata = tmp_path / "metadata.json"
    metadata.write_bytes(_metadata())
    file_result = _run_preview(
        tmp_path / "file-runtime", "--metadata-json", str(metadata)
    )

    assert stdin_result.returncode == 0, stdin_result.stderr.decode("utf-8", "replace")
    assert file_result.returncode == 0, file_result.stderr.decode("utf-8", "replace")
    assert _title(stdin_result.stdout) == EMOJI_TITLE
    assert stdin_result.stdout == file_result.stdout
