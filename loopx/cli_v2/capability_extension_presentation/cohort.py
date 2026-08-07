from __future__ import annotations

import argparse
from pathlib import Path

from loopx.application import ApplicationError
from loopx.capabilities.content_ops.item_lifecycle import (
    render_content_ops_item_packet_markdown,
)
from loopx.capabilities.content_ops.markdown import (
    render_content_ops_exploration_plan_markdown,
    render_content_ops_private_connector_gate_markdown,
    render_content_ops_walkthrough_artifact_markdown,
)
from loopx.capabilities.decision_context.markdown import (
    render_decision_context_markdown,
)
from loopx.capabilities.material_lifecycle.markdown import (
    render_material_lifecycle_markdown,
)
from loopx.cli_contract import print_compatible_markdown_renderer

from ..registrar import (
    CohortRegistrar,
    CommandBinding,
    CommandOutcome,
    SelectorMatch,
)
from .arguments import register_arguments
from .handlers import (
    handle_capability_list,
    handle_capability_show,
    handle_content_ops_exploration_plan,
    handle_content_ops_item_create,
    handle_content_ops_walkthrough,
    handle_decision_context_architecture,
    handle_decision_context_inspect_profile,
    handle_extension_init,
    handle_extension_install,
    handle_extension_list,
    handle_extension_mutation,
    handle_extension_run,
    handle_material_lifecycle_architecture,
    handle_material_lifecycle_skill_status,
    handle_presentation_package,
    handle_presentation_rollback,
    handle_presentation_verify_readback,
    handle_reward_memory_health,
    handle_reward_memory_candidate_review,
    handle_reward_memory_corpus_registry,
    handle_reward_memory_route,
    handle_semantic_preference_application_receipt,
    handle_semantic_preference_maintenance_receipt,
    handle_value_connector_install_check,
    handle_value_connector_source_map,
)


def _selector(dest: str, value: str) -> tuple[SelectorMatch, ...]:
    return (SelectorMatch(dest=dest, value=value),)


_CONTENT_OPS_ITEM_CREATE_MARKDOWN_RENDERER = print_compatible_markdown_renderer(
    render_content_ops_item_packet_markdown
)
_CONTENT_OPS_EXPLORATION_PLAN_MARKDOWN_RENDERER = (
    print_compatible_markdown_renderer(render_content_ops_exploration_plan_markdown)
)
_CONTENT_OPS_ERROR_MARKDOWN_RENDERER = print_compatible_markdown_renderer(
    render_content_ops_private_connector_gate_markdown
)
_CONTENT_OPS_WALKTHROUGH_MARKDOWN_RENDERER = print_compatible_markdown_renderer(
    render_content_ops_walkthrough_artifact_markdown
)
_DECISION_CONTEXT_MARKDOWN_RENDERER = print_compatible_markdown_renderer(
    render_decision_context_markdown
)
_MATERIAL_LIFECYCLE_MARKDOWN_RENDERER = print_compatible_markdown_renderer(
    render_material_lifecycle_markdown
)


def _map_content_ops_error(
    error: ApplicationError,
    _args: argparse.Namespace,
    _registry_path: Path,
) -> CommandOutcome:
    return CommandOutcome(
        payload={"ok": False, "mode": "content-ops", "error": str(error)},
        exit_code=1,
        markdown_renderer=_CONTENT_OPS_ERROR_MARKDOWN_RENDERER,
    )


CAPABILITY_EXTENSION_PRESENTATION_COHORT = CohortRegistrar(
    cohort_id="capability-extension-presentation",
    register_arguments=register_arguments,
    bindings=(
        CommandBinding(
            command="capability",
            selectors=_selector("capability_command", "list"),
            application_operation="application.capabilities.catalog.list",
            handler=handle_capability_list,
        ),
        CommandBinding(
            command="capability",
            selectors=_selector("capability_command", "show"),
            application_operation="application.capabilities.catalog.get",
            handler=handle_capability_show,
        ),
        CommandBinding(
            command="decision-context",
            selectors=_selector("decision_context_command", "architecture"),
            application_operation=(
                "application.capabilities.decision_context.describe_architecture"
            ),
            handler=handle_decision_context_architecture,
            markdown_renderer=_DECISION_CONTEXT_MARKDOWN_RENDERER,
        ),
        CommandBinding(
            command="decision-context",
            selectors=_selector("decision_context_command", "inspect-profile"),
            application_operation=(
                "application.capabilities.decision_context.inspect_profile"
            ),
            handler=handle_decision_context_inspect_profile,
            markdown_renderer=_DECISION_CONTEXT_MARKDOWN_RENDERER,
        ),
        CommandBinding(
            command="content-ops",
            selectors=_selector("content_ops_command", "exploration-plan"),
            application_operation=(
                "application.capabilities.content_ops.exploration_plan"
            ),
            handler=handle_content_ops_exploration_plan,
            markdown_renderer=_CONTENT_OPS_EXPLORATION_PLAN_MARKDOWN_RENDERER,
            application_error_mapper=_map_content_ops_error,
        ),
        CommandBinding(
            command="content-ops",
            selectors=_selector("content_ops_command", "walkthrough-artifact"),
            application_operation=(
                "application.capabilities.content_ops.walkthrough_artifact"
            ),
            handler=handle_content_ops_walkthrough,
            markdown_renderer=_CONTENT_OPS_WALKTHROUGH_MARKDOWN_RENDERER,
            application_error_mapper=_map_content_ops_error,
        ),
        CommandBinding(
            command="content-ops",
            selectors=_selector("content_ops_command", "item-create"),
            application_operation="application.capabilities.content_ops.create_item",
            handler=handle_content_ops_item_create,
            markdown_renderer=_CONTENT_OPS_ITEM_CREATE_MARKDOWN_RENDERER,
            application_error_mapper=_map_content_ops_error,
        ),
        CommandBinding(
            command="material-lifecycle",
            selectors=_selector("material_lifecycle_command", "architecture"),
            application_operation=(
                "application.capabilities.material_lifecycle.describe_architecture"
            ),
            handler=handle_material_lifecycle_architecture,
            markdown_renderer=_MATERIAL_LIFECYCLE_MARKDOWN_RENDERER,
        ),
        CommandBinding(
            command="material-lifecycle",
            selectors=_selector("material_lifecycle_command", "skill-status"),
            application_operation=(
                "application.capabilities.material_lifecycle.inspect_skill"
            ),
            handler=handle_material_lifecycle_skill_status,
        ),
        CommandBinding(
            command="reward-memory",
            selectors=_selector("reward_memory_command", "health-check"),
            application_operation="application.capabilities.reward_memory.health",
            handler=handle_reward_memory_health,
        ),
        CommandBinding(
            command="reward-memory",
            selectors=_selector("reward_memory_command", "corpus-registry"),
            application_operation=(
                "application.capabilities.reward_memory.corpus_registry"
            ),
            handler=handle_reward_memory_corpus_registry,
        ),
        CommandBinding(
            command="reward-memory",
            selectors=_selector("reward_memory_command", "candidate-review"),
            application_operation=(
                "application.capabilities.reward_memory.candidate_review"
            ),
            handler=handle_reward_memory_candidate_review,
        ),
        CommandBinding(
            command="reward-memory",
            selectors=_selector("reward_memory_command", "route-check"),
            application_operation="application.capabilities.reward_memory.route",
            handler=handle_reward_memory_route,
        ),
        CommandBinding(
            command="semantic-preference",
            selectors=_selector("semantic_preference_command", "receipt"),
            application_operation=(
                "application.capabilities.semantic_preference.application_receipt"
            ),
            handler=handle_semantic_preference_application_receipt,
        ),
        CommandBinding(
            command="semantic-preference",
            selectors=_selector(
                "semantic_preference_command",
                "maintenance-receipt",
            ),
            application_operation=(
                "application.capabilities.semantic_preference.maintenance_receipt"
            ),
            handler=handle_semantic_preference_maintenance_receipt,
        ),
        CommandBinding(
            command="value-connectors",
            selectors=_selector("value_connectors_command", "install-check"),
            application_operation=(
                "application.capabilities.value_connectors.install_check"
            ),
            handler=handle_value_connector_install_check,
        ),
        CommandBinding(
            command="value-connectors",
            selectors=_selector("value_connectors_command", "source-map"),
            application_operation=(
                "application.capabilities.value_connectors.source_map"
            ),
            handler=handle_value_connector_source_map,
        ),
        CommandBinding(
            command="extension",
            selectors=_selector("extension_command", "init"),
            application_operation="application.extensions.initialize",
            handler=handle_extension_init,
        ),
        CommandBinding(
            command="extension",
            selectors=_selector("extension_command", "list"),
            application_operation="application.extensions.list",
            handler=handle_extension_list,
        ),
        *(
            CommandBinding(
                command="extension",
                selectors=_selector("extension_command", operation),
                application_operation=f"application.extensions.{operation}",
                handler=handle_extension_install,
            )
            for operation in ("install", "upgrade")
        ),
        *(
            CommandBinding(
                command="extension",
                selectors=_selector("extension_command", operation),
                application_operation=f"application.extensions.{operation}",
                handler=handle_extension_mutation,
            )
            for operation in ("enable", "disable", "rollback", "doctor")
        ),
        CommandBinding(
            command="extension",
            selectors=_selector("extension_command", "run"),
            application_operation="application.extensions.run",
            handler=handle_extension_run,
        ),
        CommandBinding(
            command="presentation",
            selectors=_selector("presentation_command", "package"),
            application_operation="application.presentations.package",
            handler=handle_presentation_package,
        ),
        CommandBinding(
            command="presentation",
            selectors=_selector("presentation_command", "rollback"),
            application_operation="application.presentations.rollback",
            handler=handle_presentation_rollback,
        ),
        CommandBinding(
            command="presentation",
            selectors=_selector("presentation_command", "verify-readback"),
            application_operation="application.presentations.verify_readback",
            handler=handle_presentation_verify_readback,
        ),
    ),
)
