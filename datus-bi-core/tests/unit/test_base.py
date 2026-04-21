import pytest

from datus_bi_core.base import BIAdapterBase
from datus_bi_core.models import (
    AuthParam,
    AuthType,
    ChartInfo,
    DashboardInfo,
    DatasetInfo,
    PaginatedResult,
)


class MinimalAdapter(BIAdapterBase):
    def platform_name(self) -> str:
        return "minimal"

    def auth_type(self) -> AuthType:
        return AuthType.API_KEY

    def parse_dashboard_id(self, dashboard_url: str):
        return dashboard_url

    def get_dashboard_info(self, dashboard_id):
        return None

    def list_charts(self, dashboard_id, limit=50, offset=0):
        return PaginatedResult[ChartInfo](items=[], total=0)

    def get_chart(self, chart_id, dashboard_id=None):
        return None

    def list_datasets(self, dashboard_id, limit=50, offset=0):
        return PaginatedResult[DatasetInfo](items=[], total=0)

    def get_dataset(self, dataset_id, dashboard_id=None):
        return None

    def list_dashboards(self, search: str = "", limit: int = 50, offset: int = 0):
        return PaginatedResult[DashboardInfo](items=[], total=0)


def test_base_default_get_chart_data_is_unsupported():
    adapter = MinimalAdapter(
        api_base_url="http://localhost",
        auth_params=AuthParam(api_key="test"),
        dialect="postgresql",
    )

    with pytest.raises(NotImplementedError) as exc_info:
        adapter.get_chart_data("1")

    assert "does not support get_chart_data" in str(exc_info.value)


def test_paginated_result_defaults():
    """PaginatedResult defaults: empty items, None total."""
    empty = PaginatedResult[DashboardInfo]()
    assert empty.items == []
    assert empty.total is None


def test_paginated_result_carries_total():
    """PaginatedResult preserves the upstream total for pagination hints."""
    row = DashboardInfo(id=1, name="d1")
    page = PaginatedResult[DashboardInfo](items=[row], total=137)
    assert page.items == [row]
    assert page.total == 137


def test_list_dashboards_signature_accepts_limit_offset():
    """Regression: the base signature evolved from (search, page_size=20) to
    (search, limit=50, offset=0). Make sure callers can pass both keyword
    args without the abstract stub rejecting them.
    """
    adapter = MinimalAdapter(
        api_base_url="http://localhost",
        auth_params=AuthParam(api_key="test"),
        dialect="postgresql",
    )
    page = adapter.list_dashboards(search="foo", limit=10, offset=20)
    assert isinstance(page, PaginatedResult)
    assert page.items == []
