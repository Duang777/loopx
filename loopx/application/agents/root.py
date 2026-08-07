from __future__ import annotations

from dataclasses import dataclass

from .provider import CoreWorkerBridgeProvider, WorkerBridgeProvider
from .service import WorkerBridgeService


@dataclass(frozen=True, slots=True)
class AgentProviders:
    worker_bridge: WorkerBridgeProvider = CoreWorkerBridgeProvider()


@dataclass(frozen=True, slots=True)
class AgentServices:
    providers: AgentProviders = AgentProviders()

    @property
    def worker_bridge(self) -> WorkerBridgeService:
        return WorkerBridgeService(self.providers.worker_bridge)
