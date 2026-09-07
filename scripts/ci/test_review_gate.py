"""The required gate must not report success for absent or skipped core work."""

from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from review_gate import CORE_JOBS, requires_core_tests, verify


def needs(core: bool = True) -> dict:
    return {
        "changes": {"result": "success", "outputs": {"core_tests": str(core).lower()}},
        **{job: {"result": "success" if core else "skipped"} for job in CORE_JOBS},
    }


class ReviewGateTests(unittest.TestCase):
    def test_documentation_only(self):
        self.assertFalse(requires_core_tests(["README.md", "docs/guide.md"]))

    def test_unknown_and_executable_paths_require_tests(self):
        for path in (
            "loopx/prompt.md", "docs/build.py", "AGENTS.md", ".github/CODEOWNERS",
            ".github/workflows/python-tests.yml", "scripts/ci/review_gate.py",
            "packages/new-package/index.ts", "new-config.json", "docs/demo.js",
        ):
            with self.subTest(path=path):
                self.assertTrue(requires_core_tests(["docs/guide.md", path]))

    def test_empty_diff_is_not_an_exemption(self):
        self.assertTrue(requires_core_tests([]))

    def test_rename_out_of_code_is_not_an_exemption(self):
        self.assertTrue(requires_core_tests(["loopx/code.py", "docs/code.md"]))

    def test_core_success(self):
        verify(needs())

    def test_explicit_documentation_skip(self):
        verify(needs(False))

    def test_every_unsuccessful_core_result_is_rejected(self):
        for job in CORE_JOBS:
            for result in ("skipped", "failure", "cancelled", "neutral", "", None):
                value = needs()
                value[job]["result"] = result
                with self.subTest(job=job, result=result), self.assertRaises(ValueError):
                    verify(value)

    def test_missing_or_extra_dependencies_are_rejected(self):
        for job in ("changes", *CORE_JOBS):
            value = needs()
            del value[job]
            with self.subTest(job=job), self.assertRaises(ValueError):
                verify(value)
        with self.assertRaises(ValueError):
            verify({**needs(), "extra": {"result": "success"}})

    def test_invalid_classification_is_rejected(self):
        for result in ("failure", "cancelled", "skipped"):
            value = needs()
            value["changes"]["result"] = result
            with self.assertRaises(ValueError):
                verify(value)
        for output in ({}, {"core_tests": ""}, {"core_tests": True}, None):
            value = needs()
            value["changes"]["outputs"] = output
            with self.assertRaises(ValueError):
                verify(value)

    def test_docs_cannot_hide_a_failed_job(self):
        for job in CORE_JOBS:
            value = copy.deepcopy(needs(False))
            value[job]["result"] = "failure"
            with self.assertRaises(ValueError):
                verify(value)

    def test_real_git_diff_handles_code_deletion_and_missing_base(self):
        script = str(Path(__file__).with_name("review_gate.py"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # pytest-cov injects subprocess startup variables. The synthetic
            # checkout must not contribute temporary source paths to real CI.
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("PYTEST", "COVERAGE", "COV_CORE"))}

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, env=env, text=True
                ).strip()

            git("init", "-q")
            git("config", "user.name", "CI Fixture")
            git("config", "user.email", "ci@example.invalid")
            git("config", "core.hooksPath", str(root / "no-hooks"))
            (root / "docs").mkdir()
            (root / "loopx").mkdir()
            (root / "docs/readme.md").write_text("baseline\n")
            (root / "loopx/code.py").write_text("pass\n")
            git("add", "docs/readme.md", "loopx/code.py")
            git("commit", "-qm", "baseline")
            base = git("rev-parse", "HEAD")
            (root / "docs/readme.md").write_text("documentation only\n")
            git("commit", "-qam", "docs")
            result = subprocess.check_output(
                [sys.executable, script, "classify", "--base", base, "--head", "HEAD"],
                cwd=root, env=env, text=True,
            )
            self.assertEqual(result.strip(), "core_tests=false")
            git("mv", "loopx/code.py", "docs/code.md")
            git("commit", "-qm", "move code into docs")
            result = subprocess.check_output(
                [sys.executable, script, "classify", "--base", base, "--head", "HEAD"],
                cwd=root, env=env, text=True,
            )
            self.assertEqual(result.strip(), "core_tests=true")
            failed = subprocess.run(
                [sys.executable, script, "classify", "--base", "missing-ref", "--head", "HEAD"],
                cwd=root, env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertNotIn("core_tests=false", failed.stdout)


if __name__ == "__main__":
    unittest.main()
