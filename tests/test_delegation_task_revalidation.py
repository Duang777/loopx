"""Version-bound requester decisions through real Turn acceptance and durable IO."""
import asyncio
import json
import os
import sys
import subprocess

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from loopx.collaboration_mcp import Delegations
from test_local_delegation import brief, service as delegation_service, wait

service = delegation_service


def test_original_task_revalidation_repairs_output_without_repeating_host(service):
    root, runner = service
    output = root / "analyst/initial/output.json"
    saved = output.read_bytes()
    output.write_text("{}")
    runner.start("analysis", "analysis-1", brief())
    rejected = wait(runner)
    assert rejected["status"] == "rejected", rejected
    assert rejected["task_failure"]["resume_mode"] == "revalidate_cached_result"
    key = rejected["task_failure"]["turn_key"]
    command = [sys.executable, "-m", "loopx.cli", "--registry", str(runner.registry),
        "--runtime-root", str(runner.root), "delegation", "revalidate", "--goal-id", runner.goal_id,
        "--agent-id", runner.agent_id, "--execution-config", str(runner.config),
        "--operation-id", "analysis-1", "--execute"]
    still_failed = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)
    assert still_failed["status"] == "rejected", still_failed
    assert still_failed["task_failure"]["turn_key"] == key
    output.write_bytes(saved)  # Actual task repair, not a replacement validator.
    async def recheck_mcp():
        params = StdioServerParameters(command=sys.executable, env={
            key: os.environ[key] for key in ("NODE_OPTIONS", "TMPDIR", "TEMP", "TMP")
            if key in os.environ}, args=["-m", "loopx.collaboration_mcp", "--registry", str(runner.registry),
            "--runtime-root", str(runner.root), "--goal-id", runner.goal_id, "--agent-id", runner.agent_id,
            "--workspace", str(root / "lead"), "--execution-config", str(runner.config)])
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("revalidate_delegation", {"operation_id": "analysis-1"})
                assert not result.isError, result
    asyncio.run(recheck_mcp())
    accepted = wait(runner)
    assert accepted["status"] == "accepted", json.dumps({"read": accepted, "record": json.loads(runner.path("analysis-1").read_text())})
    assert "task_failure" not in accepted
    assert (root / "analyst/initial/host-invocations").read_text() == "1"
    assert json.loads(runner.path("analysis-1").read_text())["turn_key"] == key
    with pytest.raises(ValueError, match="original independent task failure"):
        runner.revalidate("analysis-1")


@pytest.mark.parametrize("entrypoint", ["resume", "revalidate"])
def test_committed_revalidation_response_loss_recovers_same_turn(service, monkeypatch, entrypoint):
    root, runner = service
    output = root / "analyst/initial/output.json"
    saved = output.read_bytes()
    output.write_text("{}")
    runner.start("analysis", "analysis-1", brief())
    failed = wait(runner)
    turn_key = failed["task_failure"]["turn_key"]
    output.write_bytes(saved)
    cli = runner._cli
    committed = []
    def lose_response(binding, *args, **kwargs):
        result = cli(binding, *args, **kwargs)
        if "--retry-failed-turn" in args:
            assert result["status"] == "committed"
            committed.append(result["receipt"]["settlement_effect_id"])
            raise subprocess.TimeoutExpired("lost committed response", 1)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(runner, "_cli", lose_response)
        with pytest.raises(subprocess.TimeoutExpired):
            runner.revalidate("analysis-1")
    restarted = Delegations(runner.root, runner.registry, runner.goal_id, runner.agent_id, runner.config)
    assert restarted.read("analysis-1")["recovery_required"] is True
    # Revocation and a stop remain stronger than committed-result recovery.
    configured = restarted.config.read_bytes()
    revoked = json.loads(configured)
    revoked["bindings"][0]["requesters"] = []
    restarted.config.write_text(json.dumps(revoked))
    frozen = restarted.path("analysis-1").read_bytes()
    from loopx.control_plane.effect_runtime import EffectRuntimeRejected
    with pytest.raises(EffectRuntimeRejected, match="no delegation grant"):
        getattr(restarted, entrypoint)("analysis-1")
    assert restarted.path("analysis-1").read_bytes() == frozen
    restarted.config.write_bytes(configured)
    stop_path = restarted._stop_path(restarted.path("analysis-1"))
    stop = restarted._new_stop_record(json.loads(frozen), requested_by="lead", worker=None)
    stop_path.write_text(json.dumps(stop))
    with pytest.raises(ValueError):
        getattr(restarted, entrypoint)("analysis-1")
    assert restarted.path("analysis-1").read_bytes() == frozen
    stop_path.unlink()  # Remove only this synthetic injected fence.
    getattr(restarted, entrypoint)("analysis-1")
    accepted = wait(restarted)
    assert accepted["status"] == "accepted", accepted
    assert json.loads(restarted.path("analysis-1").read_text())["turn_key"] == turn_key
    from loopx.control_plane.turn_driver.journal_store import load_turn_journal, turn_journal_path
    journal = load_turn_journal(turn_journal_path(runner.root, goal_id=runner.goal_id, turn_key=turn_key))
    assert journal["receipt"]["settlement_effect_id"] == committed[0]
    assert (root / "analyst/initial/host-invocations").read_text().strip() == "1"
    restarted.resume("analysis-1")
    assert restarted.read("analysis-1")["status"] == "accepted"
