from __future__ import annotations

from dataclasses import dataclass

from .provider import (
    BenchmarkInspectionProvider,
    CoreSplitControlBenchmarkProvider,
    SplitControlBenchmarkProvider,
)
from .service import BenchmarkInspectionService, SplitControlBenchmarkService


@dataclass(frozen=True, slots=True)
class BenchmarkProviders:
    split_control: SplitControlBenchmarkProvider = CoreSplitControlBenchmarkProvider()
    inspection: BenchmarkInspectionProvider | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkServices:
    providers: BenchmarkProviders = BenchmarkProviders()

    @property
    def split_control(self) -> SplitControlBenchmarkService:
        return SplitControlBenchmarkService(self.providers.split_control)

    @property
    def inspection(self) -> BenchmarkInspectionService:
        return BenchmarkInspectionService(self.providers.inspection)
