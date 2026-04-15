# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Union

from datus_bi_core.models import (
    AuthParam,
    AuthType,
    ChartInfo,
    DashboardInfo,
    DatasetInfo,
)


class BIAdapterBase(ABC):
    """
    Two-layer design:
      1) Discovery: list dashboards/charts/datasets
      2) Extraction: fetch structured assets for analysis (QuerySpec / DatasetInfo)
    """

    def __init__(
        self,
        api_base_url: str,
        auth_params: AuthParam,
        dialect: str,
        timeout: Optional[float] = 30.0,
    ) -> None:
        self.api_base_url = api_base_url
        self.auth_params = auth_params
        self.dialect = dialect
        self.timeout = timeout

    @abstractmethod
    def platform_name(self) -> str: ...

    @abstractmethod
    def auth_type(self) -> AuthType: ...

    @abstractmethod
    def parse_dashboard_id(self, dashboard_url: str) -> Union[int, str]: ...

    @abstractmethod
    def get_dashboard_info(
        self, dashboard_id: Union[int, str]
    ) -> Optional[DashboardInfo]: ...

    @abstractmethod
    def list_charts(self, dashboard_id: Union[int, str]) -> List[ChartInfo]: ...

    @abstractmethod
    def get_chart(
        self, chart_id: Union[int, str], dashboard_id: Union[int, str, None] = None
    ) -> Optional[ChartInfo]: ...

    @abstractmethod
    def list_datasets(self, dashboard_id: Union[int, str]) -> List[DatasetInfo]: ...

    @abstractmethod
    def get_dataset(
        self, dataset_id: Union[int, str], dashboard_id: Union[int, str, None] = None
    ) -> Optional[DatasetInfo]: ...

    @abstractmethod
    def list_dashboards(
        self, search: str = "", page_size: int = 20
    ) -> List[DashboardInfo]: ...

    def close(self):
        return
