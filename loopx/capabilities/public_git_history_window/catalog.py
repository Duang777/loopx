from __future__ import annotations

from typing import Any

PUBLIC_GIT_HISTORY_WINDOW_CAPABILITY: dict[str, Any] = {
    "id": "public_git_history_window",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "title": "Public Git history write window",
    "status": "active-preview",
    "default_enabled": False,
    "real_world_anchor": (
        "goal-scoped publication windows for public repository history"
    ),
    "user_value": (
        "Preserve local progress while deferring public commit, push, merge, tag, "
        "and release effects during configured local-time windows."
    ),
    "entry_command": (
        "loopx public-git-history-window evaluate --goal-id <goal-id> "
        "--effect-id <stable-effect-id> --action <history-action> "
        "--repository-visibility <public|private|unknown> "
        "--repository-identity <provider/repository> --format json"
    ),
    "commands": [
        {
            "command": (
                "loopx configure-goal --goal-id <goal-id> "
                "--public-git-history-window-config "
                ".loopx/config/<policy>.json [--execute]"
            ),
            "purpose": "Preview or register one ignored goal-local policy pointer.",
            "write_boundary": (
                "registry pointer only; private window values remain in ignored "
                "goal-local configuration"
            ),
        },
        {
            "command": (
                "loopx public-git-history-window evaluate --goal-id <goal-id> "
                "--effect-id <stable-effect-id> --action <action> "
                "--repository-visibility <public|private|unknown> "
                "--repository-identity <provider/repository> --format json"
            ),
            "purpose": (
                "Return a typed allow, defer, or reject decision and receipt before "
                "a repository effect executes."
            ),
            "write_boundary": "read-only evaluation; no git or remote write",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "public_git_history_window_config_v0",
            "module": "loopx.capabilities.public_git_history_window.policy",
            "doc": "docs/capabilities/public-git-history-window/README.md",
        },
        {
            "schema_version": "public_git_history_window_decision_v0",
            "module": "loopx.capabilities.public_git_history_window.effect_program",
            "doc": "docs/capabilities/public-git-history-window/README.md",
        },
        {
            "schema_version": "public_git_history_window_receipt_v0",
            "module": "loopx.capabilities.public_git_history_window.effect_program",
            "doc": "docs/capabilities/public-git-history-window/README.md",
        },
    ],
    "smokes": [
        "python -m pytest tests/capabilities/test_public_git_history_window.py -q"
    ],
    "docs": ["docs/capabilities/public-git-history-window/README.md"],
    "boundaries": [
        "The capability owns public history effects only; PR comments, reviews, labels, reviewer requests, and metadata remain available.",
        "PR creation is allowed only when the head already exists remotely and the caller performs no implicit push.",
        "Unknown repository visibility fails closed; private repositories are outside a public-only policy.",
        "Auto-merge enablement is rejected because it cannot guarantee an execution-time policy recheck.",
        "Outgoing unpublished commits are checked for blocked author and committer timestamps; timestamps are never rewritten.",
        "The evaluator is the provider-neutral contract. Raw git callers that bypass it are not intercepted by v0.",
    ],
    "next_real_step": (
        "Bind the evaluator to each shipped commit, push, merge, tag, and release "
        "caller before claiming host-level enforcement."
    ),
}
