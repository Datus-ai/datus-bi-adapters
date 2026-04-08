# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

from datus_bi_core.models import (
    ChartInfo,
    ChartSpec,
    DashboardInfo,
    DashboardSpec,
    DatasetInfo,
    DatasetSpec,
)


class DashboardWriteMixin(ABC):
    @abstractmethod
    def create_dashboard(self, spec: DashboardSpec) -> DashboardInfo: ...

    @abstractmethod
    def update_dashboard(
        self, dashboard_id: Union[int, str], spec: DashboardSpec
    ) -> DashboardInfo: ...

    @abstractmethod
    def delete_dashboard(self, dashboard_id: Union[int, str]) -> bool: ...


class ChartWriteMixin(ABC):
    @abstractmethod
    def create_chart(
        self, spec: ChartSpec, dashboard_id: Optional[Union[int, str]] = None
    ) -> ChartInfo: ...

    @abstractmethod
    def update_chart(self, chart_id: Union[int, str], spec: ChartSpec) -> ChartInfo: ...

    @abstractmethod
    def delete_chart(self, chart_id: Union[int, str]) -> bool: ...

    @abstractmethod
    def add_chart_to_dashboard(
        self, dashboard_id: Union[int, str], chart_id: Union[int, str]
    ) -> bool: ...


class DatasetWriteMixin(ABC):
    @abstractmethod
    def create_dataset(self, spec: DatasetSpec) -> DatasetInfo: ...

    @abstractmethod
    def delete_dataset(self, dataset_id: Union[int, str]) -> bool: ...

    @abstractmethod
    def list_bi_databases(self) -> List[Dict[str, Any]]: ...
