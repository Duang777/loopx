from __future__ import annotations

from typing import Protocol, cast

from loopx.application.agents import AgentServices
from loopx.application.benchmarks import BenchmarkServices
from loopx.application.errors import CapabilityUnavailable
from loopx.application.maintenance import MaintenanceServices


class MaintainerBenchmarkAgentApplication(Protocol):
    """Frozen T7C root accessor; production composition belongs to T8."""

    @property
    def agents(self) -> AgentServices: ...

    @property
    def benchmarks(self) -> BenchmarkServices: ...

    @property
    def maintenance(self) -> MaintenanceServices: ...


def require_application_root(
    application: object,
) -> MaintainerBenchmarkAgentApplication:
    missing = [
        name
        for name in ("agents", "benchmarks", "maintenance")
        if getattr(application, name, None) is None
    ]
    if missing:
        raise CapabilityUnavailable(
            details={
                "operation": "application.t7c_root",
                "provider": "maintainer_benchmark_agent_root",
                "missing_accessors": missing,
            }
        )
    return cast(MaintainerBenchmarkAgentApplication, application)
