from __future__ import annotations

import hashlib
import io
import json
import tarfile
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

from loopx.application import ApplicationContext, Profile
from loopx.application.registry import RegistryServices
from loopx.application.system import SystemServices
from loopx.cli import main as legacy_main
from loopx.cli_v2.entrypoint import main as v2_main
from loopx.cli_v2.project_system_registry import PROJECT_SYSTEM_REGISTRY_COHORT


@dataclass(frozen=True)
class _ApplicationRoot:
    system: SystemServices
    registry: RegistryServices


def _application_factory(args: object, registry_path: Path) -> _ApplicationRoot:
    runtime_root = getattr(args, "runtime_root", None)
    context = ApplicationContext(
        registry_path=registry_path,
        runtime_root_override=runtime_root,
        profile=Profile.CLI,
    )
    return _ApplicationRoot(
        system=SystemServices(context=context),
        registry=RegistryServices(context=context),
    )


def _run_legacy(argv: list[str]) -> None:
    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = legacy_main(argv)
    assert exit_code == 0, output.getvalue()


def _run_v2(argv: list[str]) -> dict[str, object]:
    output = io.StringIO()
    exit_code = v2_main(
        argv,
        application_factory=_application_factory,
        cohorts=(PROJECT_SYSTEM_REGISTRY_COHORT,),
        stdout=output,
    )
    assert exit_code == 0, output.getvalue()
    payload = json.loads(output.getvalue())
    assert isinstance(payload, dict)
    return payload


def test_backup_state_write_side_effects_match_on_isolated_fixtures(
    tmp_path: Path,
) -> None:
    legacy_root = tmp_path / "legacy"
    v2_root = tmp_path / "v2"
    for root in (legacy_root, v2_root):
        (root / "project" / ".loopx").mkdir(parents=True)
        (root / "project" / ".loopx" / "state.txt").write_text(
            "same project state\n",
            encoding="utf-8",
        )
        (root / "runtime").mkdir(parents=True)
        (root / "runtime" / "runtime.txt").write_text(
            "same runtime state\n",
            encoding="utf-8",
        )

    _run_legacy(_backup_argv(legacy_root))
    v2_payload = _run_v2(_backup_argv(v2_root))

    assert v2_payload["written"] is True
    assert str(tmp_path) not in json.dumps(v2_payload)
    assert _backup_snapshot(legacy_root / "output") == _backup_snapshot(
        v2_root / "output"
    )


def _backup_argv(root: Path) -> list[str]:
    return [
        "--registry",
        str(root / "registry.json"),
        "--runtime-root",
        str(root / "runtime"),
        "--format",
        "json",
        "backup-state",
        "--project",
        str(root / "project"),
        "--output-dir",
        str(root / "output"),
        "--backup-id",
        "parity-backup",
        "--no-automations",
        "--no-skills",
        "--current-project-only",
        "--execute",
    ]


def _backup_snapshot(output_dir: Path) -> dict[str, object]:
    archive = output_dir / "loopx-state-parity-backup.tar.gz"
    manifest_path = output_dir / "loopx-state-parity-backup.manifest.json"
    assert archive.is_file()
    assert manifest_path.is_file()
    member_digests: dict[str, object] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            extracted = tar.extractfile(member) if member.isfile() else None
            if extracted is None:
                member_digests[member.name] = None
            elif member.name == "manifest.json":
                member_digests[member.name] = _backup_manifest_projection(
                    json.loads(extracted.read())
                )
            else:
                member_digests[member.name] = hashlib.sha256(
                    extracted.read()
                ).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "files": sorted(path.name for path in output_dir.iterdir()),
        "members": member_digests,
        "manifest": _backup_manifest_projection(manifest),
    }


def _backup_manifest_projection(manifest: dict[str, object]) -> dict[str, object]:
    included = manifest["included"]
    summary = manifest["summary"]
    assert isinstance(included, list)
    assert isinstance(summary, dict)
    return {
        "backup_id": manifest["backup_id"],
        "included": [
            {
                "key": row["key"],
                "archive_path": row["archive_path"],
                "stats": row["stats"],
            }
            for row in included
            if isinstance(row, dict)
        ],
        "summary": {
            "included_target_count": summary["included_target_count"],
            "missing_target_count": summary["missing_target_count"],
            "logical_source_bytes": summary["logical_source_bytes"],
        },
    }


def test_archive_runtime_write_side_effects_match_on_isolated_fixtures(
    tmp_path: Path,
) -> None:
    legacy_root = tmp_path / "legacy"
    v2_root = tmp_path / "v2"
    for root in (legacy_root, v2_root):
        (root / "runtime" / "goals" / "obsolete").mkdir(parents=True)
        (root / "runtime" / "goals" / "obsolete" / "note.txt").write_text(
            "same runtime payload\n",
            encoding="utf-8",
        )
        (root / "registry.json").write_text(
            json.dumps({"schema_version": "0.1", "goals": []}),
            encoding="utf-8",
        )

    _run_legacy(_archive_argv(legacy_root))
    v2_payload = _run_v2(_archive_argv(v2_root))

    assert v2_payload["archived"] is True
    assert str(tmp_path) not in json.dumps(v2_payload)
    assert _archive_snapshot(legacy_root) == _archive_snapshot(v2_root)


def _archive_argv(root: Path) -> list[str]:
    return [
        "--registry",
        str(root / "registry.json"),
        "--runtime-root",
        str(root / "runtime"),
        "--format",
        "json",
        "archive-runtime",
        "--goal-id",
        "obsolete",
        "--archive-root",
        str(root / "archive"),
        "--execute",
    ]


def _archive_snapshot(root: Path) -> dict[str, object]:
    archived_roots = [path for path in (root / "archive").iterdir() if path.is_dir()]
    assert len(archived_roots) == 1
    archived_root = archived_roots[0]
    return {
        "source_exists": (root / "runtime" / "goals" / "obsolete").exists(),
        "archive_prefix": archived_root.name.split("-20", 1)[0],
        "files": {
            path.relative_to(archived_root).as_posix(): path.read_text(encoding="utf-8")
            for path in archived_root.rglob("*")
            if path.is_file()
        },
    }


def test_migrate_state_write_side_effects_match_on_isolated_fixtures(
    tmp_path: Path,
) -> None:
    source_registry = tmp_path / "legacy-registry.json"
    source_registry.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": "old-goal",
                        "domain": "fixture",
                        "status": "active",
                        "repo": "project",
                        "state_file": ".loopx/active.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    legacy_root = tmp_path / "legacy-target"
    v2_root = tmp_path / "v2-target"
    legacy_root.mkdir()
    v2_root.mkdir()

    _run_legacy(_migration_argv(legacy_root, source_registry))
    v2_payload = _run_v2(_migration_argv(v2_root, source_registry))

    assert v2_payload["wrote_project_registry"] is True
    assert str(tmp_path) not in json.dumps(v2_payload)
    assert _registry_snapshot(legacy_root / "registry.json") == _registry_snapshot(
        v2_root / "registry.json"
    )


def _migration_argv(root: Path, source_registry: Path) -> list[str]:
    return [
        "--registry",
        str(root / "registry.json"),
        "--runtime-root",
        str(root / "runtime"),
        "--format",
        "json",
        "migrate-state",
        "--legacy-registry",
        str(source_registry),
        "--legacy-runtime-root",
        str(root / "legacy-runtime"),
        "--target-runtime-root",
        str(root / "runtime"),
        "--goal-id",
        "old-goal",
        "--goal-id-map",
        "old-goal=new-goal",
        "--no-global-sync",
        "--execute",
    ]


def _registry_snapshot(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "schema_version": payload["schema_version"],
        "goals": payload["goals"],
    }
