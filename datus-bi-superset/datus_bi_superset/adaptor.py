# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Union
from urllib.parse import parse_qs, urlparse
import httpx
import sqlglot

from datus_bi_core import (
    BIAdaptorBase,
    ChartWriteMixin,
    DashboardWriteMixin,
    DatasetWriteMixin,
    ListDashboardsMixin,
)
from datus_bi_core.models import (
    AuthParam,
    AuthType,
    ChartInfo,
    ChartSpec,
    ColumnInfo,
    DashboardInfo,
    DashboardSpec,
    DatasetInfo,
    DatasetSpec,
    DimensionDef,
    MetricDef,
    QuerySpec,
)
from datus_bi_superset.util import build_query_context, uses_legacy_api


def _rison_encode(obj: Any) -> str:
    """Minimal RISON encoder for Superset API ``q`` parameters."""
    if obj is None:
        return "!n"
    if isinstance(obj, bool):
        return "!t" if obj else "!f"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return str(obj)
    if isinstance(obj, str):
        # Safe identifier chars need no quoting
        if re.match(r"^[A-Za-z0-9_\-./]+$", obj):
            return obj
        return "'" + obj.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(obj, (list, tuple)):
        return "!(" + ",".join(_rison_encode(v) for v in obj) + ")"
    if isinstance(obj, dict):
        pairs = ",".join(f"{k}:{_rison_encode(v)}" for k, v in obj.items())
        return f"({pairs})"
    return _rison_encode(str(obj))


logger = logging.getLogger(__name__)


def _extract_table_names(
    sql: str, dialect: str, ignore_empty: bool = False
) -> List[str]:
    """Extract table names from SQL using sqlglot (inline replacement for datus.utils.sql_utils)."""
    if not sql or (ignore_empty and not sql.strip()):
        return []
    read_dialect = dialect
    # Map common dialect names to sqlglot-supported names
    dialect_map = {
        "postgresql": "postgres",
        "mssql": "tsql",
    }
    read_dialect = dialect_map.get(read_dialect, read_dialect)
    try:
        parsed = sqlglot.parse_one(
            sql, read=read_dialect, error_level=sqlglot.ErrorLevel.IGNORE
        )
        if parsed is None:
            return []
    except Exception:
        return []

    table_names = []
    cte_names = set()

    # Collect CTE names
    for cte in parsed.find_all(sqlglot.exp.CTE):
        alias = cte.args.get("alias")
        if alias:
            cte_names.add(alias.name)

    # Collect table references
    for table in parsed.find_all(sqlglot.exp.Table):
        name = table.name
        if not name or name in cte_names:
            continue
        parts = []
        if table.catalog:
            parts.append(table.catalog)
        if table.db:
            parts.append(table.db)
        parts.append(name)
        full_name = ".".join(parts)
        if full_name not in table_names:
            table_names.append(full_name)

    return table_names


class SupersetAdaptorError(RuntimeError):
    """Errors raised by the Superset adaptor."""


_CHART_TYPE_MAP = {
    "bar": "echarts_timeseries_bar",
    "line": "echarts_timeseries_line",
    "pie": "pie",
    "table": "table",
    "big_number": "big_number_total",
    "scatter": "echarts_timeseries_scatter",
}


class SupersetAdaptor(
    BIAdaptorBase,
    ListDashboardsMixin,
    DashboardWriteMixin,
    ChartWriteMixin,
    DatasetWriteMixin,
):
    """Adaptor that extracts chart SQL and metadata from Superset."""

    def __init__(
        self,
        api_base_url: str,
        auth_params: AuthParam,
        dialect: str,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(api_base_url, auth_params, dialect, timeout)

        self.auth_params = auth_params
        self._api_base = self._normalize_api_base(self.api_base_url)
        self.base_url = api_base_url.rstrip("/")
        if self.base_url.endswith("/api/v1"):
            self.base_url = self.base_url[:-7]
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            verify=self.api_base_url.startswith("https://"),
            follow_redirects=True,
        )
        self._owns_client = True

        self._auth_header_value: Optional[Dict[str, str]] = None
        self._token_expiration: Optional[float] = None
        self._dataset_cache: Dict[str, DatasetInfo] = {}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def platform_name(self) -> str:
        return "superset"

    def auth_type(self) -> AuthType:
        return AuthType.LOGIN

    def parse_dashboard_id(self, dashboard_url: str) -> Union[int, str]:
        stripped = (dashboard_url or "").strip()
        if not stripped:
            return ""

        if stripped.isdigit():
            return int(stripped)

        parsed = urlparse(stripped)
        if parsed.scheme and parsed.netloc:
            segments = [segment for segment in parsed.path.split("/") if segment]
            for segment in reversed(segments):
                if segment:
                    return segment

            query_params = parse_qs(parsed.query)
            for key in ("dashboard_id", "id"):
                values = query_params.get(key)
                if values:
                    return values[0]

        return stripped

    def get_dashboard_base_info(self, dashboard_url: str) -> DashboardInfo:
        dashboard_id = self.parse_dashboard_id(dashboard_url)
        dashboard_info = self.get_dashboard_info(dashboard_id)
        if dashboard_info is None:
            raise SupersetAdaptorError(f"Dashboard {dashboard_id} not found")
        return dashboard_info

    def get_dashboard_info(
        self, dashboard_id: Union[int, str]
    ) -> Optional[DashboardInfo]:
        try:
            dashboard = self._get_dashboard(dashboard_id)
        except SupersetAdaptorError as exc:
            logger.warning(f"Failed to fetch dashboard {dashboard_id}: {exc}")
            raise exc

        name = (
            dashboard.get("dashboard_title")
            or dashboard.get("title")
            or dashboard.get("slug")
            or str(dashboard_id)
        )
        description = dashboard.get("description") or dashboard.get(
            "description_markeddown"
        )

        chart_ids: List[Union[int, str]] = []
        try:
            charts = self._get_dashboard_charts(dashboard_id)
            for chart_meta in charts:
                chart_id = self._extract_chart_id(chart_meta)
                if chart_id is not None:
                    chart_ids.append(chart_id)
        except SupersetAdaptorError as exc:
            logger.warning(
                f"Failed to fetch charts for dashboard {dashboard_id}: {exc}"
            )

        if chart_ids:
            seen = set()
            deduped: List[Union[int, str]] = []
            for chart_id in chart_ids:
                if chart_id in seen:
                    continue
                seen.add(chart_id)
                deduped.append(chart_id)
            chart_ids = deduped

        return DashboardInfo(
            id=dashboard.get("id", dashboard_id),
            name=name,
            description=description,
            chart_ids=chart_ids,
            extra={"raw": dashboard},
        )

    def list_charts(self, dashboard_id: Union[int, str]) -> List[ChartInfo]:
        try:
            charts = self._get_dashboard_charts(dashboard_id)
        except SupersetAdaptorError as exc:
            logger.warning(f"Failed to list charts for dashboard {dashboard_id}: {exc}")
            return []

        results: List[ChartInfo] = []
        for chart_meta in charts:
            chart_id = self._extract_chart_id(chart_meta)
            if chart_id is None:
                logger.warning(f"Skip chart without chart_id: {chart_meta}")
                continue

            results.append(
                ChartInfo(
                    id=chart_id,
                    name=chart_meta.get("slice_name")
                    or chart_meta.get("name")
                    or str(chart_id),
                    description=self._chart_description(chart_meta, chart_detail=None),
                    chart_type=chart_meta.get("viz_type")
                    or chart_meta.get("form_data", {}).get("viz_type"),
                )
            )
        return results

    def list_datasets(self, dashboard_id: Union[int, str]) -> List[DatasetInfo]:
        try:
            charts = self._get_dashboard_charts(dashboard_id)
        except SupersetAdaptorError as exc:
            logger.warning(
                f"Failed to list datasets for dashboard {dashboard_id}: {exc}"
            )
            return []

        dataset_map: Dict[str, Dict[str, Any]] = {}
        for chart_meta in charts:
            form_data = _load_json_field(chart_meta.get("form_data")) or {}
            query_context = _load_json_field(chart_meta.get("query_context"))
            ref = self._extract_datasource_ref(
                form_data=form_data,
                chart_meta=chart_meta,
                query_context=query_context
                if isinstance(query_context, dict)
                else None,
            )
            if not ref:
                continue
            key = str(ref["id"])
            entry = dataset_map.setdefault(
                key,
                {
                    "ref": dict(ref),
                    "tables": [],
                    "metrics": [],
                    "dimensions": [],
                    "dialect": self.dialect,
                },
            )
            if ref.get("name") and not entry["ref"].get("name"):
                entry["ref"]["name"] = ref["name"]

            table_name = entry["ref"].get("name") or ref.get("name")

            dataset_block = (
                chart_meta.get("dataset")
                if isinstance(chart_meta.get("dataset"), dict)
                else None
            )
            if dataset_block:
                if not table_name:
                    table_name = dataset_block.get("table_name") or dataset_block.get(
                        "datasource_name"
                    )
                columns = self._parse_dataset_columns(dataset_block, table_name)
                entry["metrics"].extend(
                    self._parse_dataset_metrics(dataset_block, table_name)
                )
                entry["dimensions"].extend(
                    self._parse_dataset_dimensions(dataset_block, table_name, columns)
                )
                entry["tables"].extend(self._tables_from_sql(dataset_block.get("sql")))

            if isinstance(query_context, dict):
                query_metrics, query_dimensions = (
                    self._extract_query_metrics_dimensions(query_context, table_name)
                )
                entry["metrics"].extend(query_metrics)
                entry["dimensions"].extend(query_dimensions)

            form_metrics, form_dimensions = self._extract_form_data_metrics_dimensions(
                form_data, table_name
            )
            entry["metrics"].extend(form_metrics)
            entry["dimensions"].extend(form_dimensions)

        datasets: List[DatasetInfo] = []
        for entry in dataset_map.values():
            ref = entry["ref"]
            dataset_id = ref["id"]
            dataset_name = ref.get("name") or str(dataset_id)
            tables = self._dedupe_tables(entry["tables"])
            metrics = self._dedupe_metrics(entry["metrics"])
            dimensions = self._dedupe_dimensions(entry["dimensions"])
            datasets.append(
                DatasetInfo(
                    id=dataset_id,
                    name=dataset_name,
                    dialect=entry["dialect"],
                    tables=tables or None,
                    metrics=metrics or None,
                    dimensions=dimensions or None,
                    extra={"datasource": ref},
                )
            )
        return datasets

    def get_chart(
        self, chart_id: Union[int, str], dashboard_id: Union[int, str, None] = None
    ) -> Optional[ChartInfo]:
        try:
            chart_detail = self._get_chart(chart_id)
        except SupersetAdaptorError as exc:
            logger.warning(f"Failed to fetch chart {chart_id}: {exc}")
            return None
        dataset_info = chart_detail.get("dataset")
        if not isinstance(dataset_info, dict):
            dataset_info = None
        outer_form_data = _load_json_field(chart_detail.get("form_data"))
        if outer_form_data is None:
            outer_form_data = _load_json_field(chart_detail.get("params"))
        if not isinstance(outer_form_data, dict):
            outer_form_data = None

        slice_detail = chart_detail.get("slice") or chart_detail
        if slice_detail is not chart_detail:
            chart_detail = slice_detail

        slice_form_data = _load_json_field(slice_detail.get("form_data"))
        if slice_form_data is None:
            slice_form_data = _load_json_field(slice_detail.get("params"))
        if not isinstance(slice_form_data, dict):
            slice_form_data = None

        def _matches_chart(fd: Optional[Dict[str, Any]]) -> bool:
            if not isinstance(fd, dict):
                return False
            chart_key = (
                slice_detail.get("slice_id") or slice_detail.get("id") or chart_id
            )
            if chart_key is None:
                return False
            candidate = fd.get("slice_id") or fd.get("chart_id") or fd.get("id")
            if candidate is None:
                return False
            return str(candidate) == str(chart_key)

        form_data: Dict[str, Any] = {}
        if _matches_chart(outer_form_data):
            if slice_form_data:
                form_data.update(slice_form_data)
            form_data.update(outer_form_data)
        elif slice_form_data:
            form_data = slice_form_data
        elif outer_form_data:
            form_data = outer_form_data
        query_context = self._extract_query_context(
            chart_detail, form_data, dataset_info
        )

        if not dataset_info:
            datasource_ref = self._extract_datasource_ref(
                form_data=form_data,
                chart_detail=chart_detail,
                query_context=query_context,
            )
            tables = self._resolve_tables(datasource_ref)
        else:
            datasource_ref = None
            tables = self._tables_from_sql(dataset_info.get("sql"))
        table_name_for_tagging: Optional[str] = None

        sqls: List[str] = []
        used_query_indexes: Optional[set[int]] = None
        try:
            sqls, used_query_indexes = self._collect_sql_from_chart(
                dashboard_id,
                slice_detail,
                form_data,
                query_context,
            )
        except SupersetAdaptorError as exc:
            logger.warning(f"Failed to fetch SQL for chart {chart_id}: {exc}")

        metrics: List[MetricDef] = []
        dimensions: List[DimensionDef] = []
        if query_context:
            metrics, dimensions = self._extract_query_metrics_dimensions(
                query_context,
                table_name_for_tagging,
                only_query_indexes=used_query_indexes,
            )

        if sqls:
            for sql_text in sqls:
                tables.extend(self._tables_from_sql(sql_text))
        tables = self._dedupe_tables(tables)

        query_spec: Optional[QuerySpec] = None
        if query_context or sqls:
            payload: Dict[str, Any] = {}
            if query_context:
                payload["query_context"] = query_context
            if form_data:
                payload["form_data"] = form_data
            if datasource_ref:
                payload["datasource"] = datasource_ref

            query_spec = QuerySpec(
                kind="sql" if sqls else "semantic",
                payload=payload,
                sql=sqls,
                tables=tables or None,
                metrics=metrics or None,
                dimensions=dimensions or None,
            )

        return ChartInfo(
            id=chart_detail.get("id", chart_id),
            name=chart_detail.get("slice_name")
            or chart_detail.get("name")
            or str(chart_id),
            description=self._chart_description(None, chart_detail=chart_detail),
            query=query_spec,
            chart_type=chart_detail.get("viz_type")
            or chart_detail.get("chart_type")
            or form_data.get("viz_type"),
            extra={"raw": chart_detail, "datasource": datasource_ref},
        )

    def get_dataset(
        self, dataset_id: Union[int, str], dashboard_id: Union[int, str, None] = None
    ) -> Optional[DatasetInfo]:
        if dataset_id is None:
            return None
        cache_key = str(dataset_id)
        cached = self._dataset_cache.get(cache_key)
        if cached:
            return cached

        try:
            data = self._request_json("GET", f"dataset/{dataset_id}")
        except SupersetAdaptorError as exc:
            logger.warning(f"Failed to fetch dataset {dataset_id}: {exc}")
            return None

        dataset = data.get("result", data)
        resolved_id = dataset.get("id", dataset_id)
        name = (
            dataset.get("table_name")
            or dataset.get("datasource_name")
            or dataset.get("name")
            or dataset.get("verbose_name")
            or str(resolved_id)
        )
        description = dataset.get("description") or dataset.get(
            "description_markeddown"
        )

        table_name = dataset.get("table_name") or dataset.get("datasource_name") or name
        columns = self._parse_dataset_columns(dataset, table_name)
        metrics = self._parse_dataset_metrics(dataset, table_name)
        dimensions = self._parse_dataset_dimensions(dataset, table_name, columns)
        tables = self._tables_from_sql(dataset.get("sql"))
        tables = self._dedupe_tables(tables)

        extra = {
            "database": dataset.get("database"),
            "schema": dataset.get("schema"),
            "sql": dataset.get("sql"),
            "extra": dataset.get("extra"),
        }

        dataset_info = DatasetInfo(
            id=resolved_id,
            name=name,
            dialect=self.dialect,
            description=description,
            tables=tables or None,
            columns=columns or None,
            metrics=metrics or None,
            dimensions=dimensions or None,
            extra=extra,
        )
        self._dataset_cache[cache_key] = dataset_info
        return dataset_info

    def extract_dashboard_id(self, dashboard_url: str) -> Union[int, str]:
        return self.parse_dashboard_id(dashboard_url)

    # =========================================================================
    # ListDashboardsMixin
    # =========================================================================

    def list_dashboards(
        self, search: str = "", page_size: int = 20
    ) -> List[DashboardInfo]:
        filters = []
        if search:
            filters.append(
                {
                    "col": "dashboard_title",
                    "opr": "title_or_slug",
                    "value": search,
                }
            )
        params = {"q": _rison_encode({"page_size": page_size, "filters": filters})}
        try:
            data = self._request_json("GET", "dashboard", params=params)
            results = data.get("result", [])
            return [
                DashboardInfo(
                    id=d["id"],
                    name=d.get("dashboard_title", str(d["id"])),
                    description=d.get("description"),
                    chart_ids=[],
                )
                for d in results
            ]
        except Exception as exc:
            logger.warning(f"list_dashboards failed: {exc}")
            return []

    # =========================================================================
    # DashboardWriteMixin
    # =========================================================================

    def create_dashboard(self, spec: DashboardSpec) -> DashboardInfo:
        payload: Dict[str, Any] = {"dashboard_title": spec.title, **spec.extra}
        data = self._request_json("POST", "dashboard", json=payload)
        result = data.get("result", {})
        dashboard_id = data.get("id") or result.get("id", 0)
        return DashboardInfo(
            id=dashboard_id,
            name=result.get("dashboard_title", spec.title),
            description=spec.description,
        )

    def update_dashboard(
        self, dashboard_id: Union[int, str], spec: DashboardSpec
    ) -> DashboardInfo:
        payload = {
            k: v
            for k, v in {
                "dashboard_title": spec.title,
                **spec.extra,
            }.items()
            if v
        }
        data = self._request_json("PUT", f"dashboard/{dashboard_id}", json=payload)
        result = data.get("result", data)
        return DashboardInfo(
            id=result.get("id", dashboard_id),
            name=result.get("dashboard_title", spec.title),
            description=spec.description,
        )

    def delete_dashboard(self, dashboard_id: Union[int, str]) -> bool:
        try:
            self._request_json("DELETE", f"dashboard/{dashboard_id}")
            return True
        except Exception:
            return False

    # =========================================================================
    # ChartWriteMixin
    # =========================================================================

    @staticmethod
    def _metric_to_adhoc(metric: str) -> Dict[str, Any]:
        """Convert a metric expression to a Superset adhoc metric.

        Supported formats:
          - "column_name"          → SUM(column_name)   (default)
          - "AVG(column_name)"     → AVG(column_name)
          - "MAX(column_name)"     → MAX(column_name)
          - "MIN(column_name)"     → MIN(column_name)
          - "COUNT(column_name)"   → COUNT(column_name)
          - "COUNT(*)"             → COUNT(*)
        """
        import re

        m = re.match(r"^(SUM|AVG|MAX|MIN|COUNT|COUNT_DISTINCT)\((.+)\)$", metric.strip(), re.IGNORECASE)
        if m:
            agg = m.group(1).upper()
            col = m.group(2).strip()
        else:
            agg = "SUM"
            col = metric.strip()

        if col == "*":
            return {
                "aggregate": "COUNT",
                "expressionType": "SIMPLE",
                "label": "COUNT(*)",
                "optionName": "metric_count_star",
            }
        return {
            "aggregate": agg,
            "column": {"column_name": col},
            "expressionType": "SIMPLE",
            "label": f"{agg}({col})",
            "optionName": f"metric_{agg.lower()}_{col}",
        }

    def _build_form_data(self, spec: ChartSpec) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "viz_type": _CHART_TYPE_MAP.get(spec.chart_type, spec.chart_type),
        }
        if spec.dataset_id:
            base["datasource"] = f"{spec.dataset_id}__table"
        if spec.metrics:
            # Convert plain column names to SIMPLE adhoc metric expressions so
            # Superset can execute them without pre-defined dataset metrics.
            adhoc_metrics = [
                self._metric_to_adhoc(m) if isinstance(m, str) else m
                for m in spec.metrics
            ]
            viz = base["viz_type"]
            if viz in ("big_number_total", "big_number") and len(adhoc_metrics) == 1:
                # big_number charts expect singular "metric", not "metrics" array
                base["metric"] = adhoc_metrics[0]
                base["y_axis_format"] = "SMART_NUMBER"
            else:
                base["metrics"] = adhoc_metrics
        if spec.dimensions:
            base["groupby"] = spec.dimensions
        if spec.x_axis:
            base["x_axis"] = spec.x_axis
            base["granularity_sqla"] = spec.x_axis
        if spec.filters:
            base["adhoc_filters"] = spec.filters
        return {**base, **spec.extra}

    def create_chart(
        self, spec: ChartSpec, dashboard_id: Optional[Union[int, str]] = None
    ) -> ChartInfo:
        form_data = self._build_form_data(spec)
        payload: Dict[str, Any] = {
            "slice_name": spec.title,
            "description": spec.description,
            "viz_type": form_data.get("viz_type", spec.chart_type),
            "params": json.dumps(form_data),
        }
        if spec.dataset_id:
            payload["datasource_id"] = spec.dataset_id
            payload["datasource_type"] = "table"
        data = self._request_json("POST", "chart", json=payload)
        result = data.get("result", data)
        chart_id = data.get("id") or result.get("id", 0)
        if dashboard_id and chart_id:
            try:
                self.add_chart_to_dashboard(dashboard_id, chart_id)
            except Exception as exc:
                logger.warning(
                    f"Failed to add chart {chart_id} to dashboard {dashboard_id}: {exc}"
                )
        return ChartInfo(
            id=chart_id,
            name=spec.title,
            description=spec.description,
            chart_type=spec.chart_type,
        )

    def update_chart(self, chart_id: Union[int, str], spec: ChartSpec) -> ChartInfo:
        form_data = self._build_form_data(spec)
        payload: Dict[str, Any] = {
            "slice_name": spec.title,
            "params": json.dumps(form_data),
        }
        if spec.description:
            payload["description"] = spec.description
        if spec.dataset_id:
            payload["datasource_id"] = spec.dataset_id
            payload["datasource_type"] = "table"
        data = self._request_json("PUT", f"chart/{chart_id}", json=payload)
        result = data.get("result", data)
        return ChartInfo(
            id=result.get("id", chart_id),
            name=spec.title,
            description=spec.description,
            chart_type=spec.chart_type,
        )

    def delete_chart(self, chart_id: Union[int, str]) -> bool:
        try:
            # Remove chart references from associated dashboards' position_json
            try:
                chart_data = self._request_json("GET", f"chart/{chart_id}")
                chart_result = chart_data.get("result", chart_data)
                dashboards = chart_result.get("dashboards", [])
                for dash in dashboards:
                    dash_id = dash.get("id")
                    if dash_id is not None:
                        self._remove_chart_from_position(dash_id, chart_id)
            except Exception as exc:
                logger.debug(f"Could not clean dashboard references for chart {chart_id}: {exc}")

            self._request_json("DELETE", f"chart/{chart_id}")
            return True
        except Exception:
            return False

    def _remove_chart_from_position(self, dashboard_id: Union[int, str], chart_id: Union[int, str]) -> None:
        """Remove a chart and its parent ROW from a dashboard's position_json."""
        try:
            data = self._request_json("GET", f"dashboard/{dashboard_id}")
            dash = data.get("result", data)
            position_data = dash.get("position_data") or dash.get("position_json")
            if isinstance(position_data, str):
                position_data = json.loads(position_data)
            if not isinstance(position_data, dict):
                return

            chart_key = f"CHART-{chart_id}"
            if chart_key not in position_data:
                return

            # Find the parent ROW that contains this chart
            chart_entry = position_data.pop(chart_key)
            parent_row_id = None
            for parent in reversed(chart_entry.get("parents", [])):
                if parent.startswith("ROW-"):
                    parent_row_id = parent
                    break

            # Remove chart from parent ROW's children; remove ROW if empty
            if parent_row_id and parent_row_id in position_data:
                row = position_data[parent_row_id]
                children = row.get("children", [])
                if chart_key in children:
                    children.remove(chart_key)
                if not children:
                    position_data.pop(parent_row_id)
                    # Also remove ROW from GRID_ID.children
                    grid = position_data.get("GRID_ID")
                    if grid and parent_row_id in grid.get("children", []):
                        grid["children"].remove(parent_row_id)

            self._request_json(
                "PUT",
                f"dashboard/{dashboard_id}",
                json={"position_json": json.dumps(position_data)},
            )
        except Exception as exc:
            logger.debug(f"_remove_chart_from_position({dashboard_id}, {chart_id}) failed: {exc}")

    def add_chart_to_dashboard(
        self, dashboard_id: Union[int, str], chart_id: Union[int, str]
    ) -> bool:
        try:
            data = self._request_json("GET", f"dashboard/{dashboard_id}")
            dash = data.get("result", data)
            position_data = dash.get("position_data") or dash.get("position_json")
            if isinstance(position_data, str):
                position_data = json.loads(position_data)
            if not isinstance(position_data, dict):
                position_data = {}

            chart_key = f"CHART-{chart_id}"
            row_key = f"ROW-{str(uuid.uuid4())[:8]}"

            # Ensure the required ROOT → GRID skeleton exists
            if "ROOT_ID" not in position_data:
                position_data["ROOT_ID"] = {
                    "type": "ROOT",
                    "id": "ROOT_ID",
                    "children": ["GRID_ID"],
                }
            if "GRID_ID" not in position_data:
                position_data["GRID_ID"] = {
                    "type": "GRID",
                    "id": "GRID_ID",
                    "children": [],
                    "parents": ["ROOT_ID"],
                }

            # Add a new ROW containing the chart
            position_data[row_key] = {
                "type": "ROW",
                "id": row_key,
                "children": [chart_key],
                "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            position_data[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_key],
                "meta": {"chartId": int(chart_id), "width": 12, "height": 50},
            }

            # Register the row in GRID_ID.children
            grid = position_data["GRID_ID"]
            if row_key not in grid["children"]:
                grid["children"].append(row_key)

            self._request_json(
                "PUT",
                f"dashboard/{dashboard_id}",
                json={"position_json": json.dumps(position_data)},
            )

            # Also update the chart's dashboards list so that Superset's
            # dashboard_slices relationship is properly set (the position_json
            # PUT alone does not sync this table).
            try:
                chart_data = self._request_json("GET", f"chart/{chart_id}")
                chart_result = chart_data.get("result", chart_data)
                existing_dash_ids = [
                    d.get("id") for d in chart_result.get("dashboards", []) if d.get("id")
                ]
                dash_id_int = int(dashboard_id)
                if dash_id_int not in existing_dash_ids:
                    existing_dash_ids.append(dash_id_int)
                self._request_json(
                    "PUT",
                    f"chart/{chart_id}",
                    json={"dashboards": existing_dash_ids},
                )
            except Exception as exc:
                logger.warning(f"Failed to sync dashboard_slices for chart {chart_id}: {exc}")

            return True
        except Exception as exc:
            logger.warning(f"add_chart_to_dashboard failed: {exc}")
            return False

    # =========================================================================
    # DatasetWriteMixin
    # =========================================================================

    def create_dataset(self, spec: DatasetSpec) -> DatasetInfo:
        if spec.sql:
            # Virtual (SQL-based) dataset
            payload: Dict[str, Any] = {
                "table_name": spec.name,
                "sql": spec.sql,
                "database": spec.database_id,
                "schema": spec.db_schema,
            }
        else:
            # Physical table dataset: table already exists in the DB
            payload = {
                "table_name": spec.name,
                "database": spec.database_id,
                "schema": spec.db_schema,
            }
        data = self._request_json("POST", "dataset", json=payload)
        result = data.get("result", {})
        dataset_id = data.get("id") or result.get("id", 0)
        return DatasetInfo(
            id=dataset_id,
            name=spec.name,
            dialect=self.dialect,
            description=spec.description,
        )

    def update_dataset(
        self, dataset_id: Union[int, str], spec: DatasetSpec
    ) -> DatasetInfo:
        payload = {
            k: v
            for k, v in {
                "sql": spec.sql,
                "description": spec.description,
                "table_name": spec.name,
            }.items()
            if v
        }
        data = self._request_json("PUT", f"dataset/{dataset_id}", json=payload)
        result = data.get("result", data)
        return DatasetInfo(
            id=result.get("id", dataset_id),
            name=spec.name,
            dialect=self.dialect,
            description=spec.description,
        )

    def delete_dataset(self, dataset_id: Union[int, str]) -> bool:
        try:
            self._request_json("DELETE", f"dataset/{dataset_id}")
            return True
        except Exception as exc:
            logger.warning(f"delete_dataset {dataset_id} failed: {exc}")
            return False

    def register_database(self, name: str, sqlalchemy_uri: str) -> Dict[str, Any]:
        """Register a new database connection in Superset.

        Returns dict with 'id' and 'name' of the created database.
        """
        payload = {
            "database_name": name,
            "sqlalchemy_uri": sqlalchemy_uri,
            "expose_in_sqllab": True,
            "allow_ctas": True,
            "allow_cvas": True,
            "allow_dml": True,
        }
        data = self._request_json("POST", "database/", json=payload)
        result = data.get("result", data)
        return {"id": result.get("id"), "name": name}

    def list_bi_databases(self) -> List[Dict[str, Any]]:
        try:
            data = self._request_json("GET", "database/")
            return [
                {"id": d.get("id"), "name": d.get("database_name", d.get("name", ""))}
                for d in data.get("result", [])
            ]
        except Exception as exc:
            logger.warning(f"list_bi_databases failed: {exc}")
            return []

    # =========================================================================
    # Internal helpers (migrated from original)
    # =========================================================================

    def _chart_description(
        self,
        chart_meta: Optional[Dict[str, Any]],
        chart_detail: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        description = None
        if chart_meta:
            description = chart_meta.get("description") or chart_meta.get(
                "description_markeddown"
            )
        if not description and chart_detail:
            description = chart_detail.get("description") or chart_detail.get(
                "description_markeddown"
            )
        return description

    def _extract_query_context(
        self,
        chart_detail: Dict[str, Any],
        form_data: Dict[str, Any],
        dataset_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        raw_context = chart_detail.get("query_context")

        if raw_context:
            parsed_context = _load_json_field(raw_context)
        else:
            parsed_context = build_query_context(form_data=form_data)

        if isinstance(parsed_context, dict):
            _normalize_series_columns_in_query_context(parsed_context)
            return parsed_context
        return None

    def _collect_sql_from_chart(
        self,
        dashboard_id: Any,
        chart_info: Dict[str, Any],
        form_data: Dict[str, Any],
        query_context: Optional[Dict[str, Any]],
    ) -> tuple[List[str], Optional[set[int]]]:
        viz_type = form_data.get("viz_type")
        sqls = []
        query_indexes = None
        if uses_legacy_api(viz_type):
            sqls, query_indexes = self._collect_sql_via_explore_json(
                chart_info, dashboard_id
            )
        if sqls:
            return sqls, query_indexes
        chart_id = chart_info.get("slice_id")

        if query_context:
            try:
                sqls, query_indexes = self._collect_sql_via_chart_data(
                    chart_id, query_context
                )
            except SupersetAdaptorError as exc:
                logger.warning(
                    f"chart/data failed for {chart_id}, trying explore_json: {exc}"
                )

        if sqls:
            return sqls, query_indexes

        logger.debug(f"No sqls for chart {chart_id}")
        return [], None

    def _collect_sql_via_explore_json(
        self, chart_info: Dict[str, Any], dashboard_id: Any
    ) -> tuple[List[str], Optional[set[int]]]:
        chart_id = chart_info.get("slice_id")
        try:
            form_data = chart_info.get("form_data")
            form_data.setdefault("url_params", {})

            if dashboard_id:
                form_data["dashboard_id"] = dashboard_id
            self._ensure_authenticated()
            headers = {
                "Referer": f"{self.base_url}/superset/explore/?slice_id={chart_id}"
            }
            headers.update(self._auth_headers())
            explore_json_resp = self._client.post(
                url="/superset/explore_json/",
                params={
                    "query": "true",
                    "form_data": json.dumps({"slice_id": chart_id}),
                },
                data={"form_data": json.dumps(form_data)},
                headers=headers,
            )
            if not explore_json_resp.is_success:
                return [], None
            if sql := explore_json_resp.json().get("query"):
                return ([sql], {0})
        except Exception as exc:
            logger.warning(f"Explore_json failed for {chart_id} {exc}")
        return [], None

    def _collect_sql_via_chart_data(
        self,
        chart_id: Union[str, int],
        query_context: Dict[str, Any],
    ) -> tuple[List[str], Optional[set[int]]]:
        payload = dict(query_context)
        _normalize_series_columns_in_query_context(payload)
        payload.setdefault("result_format", "json")
        payload.setdefault("result_type", "query")

        try:
            response_data = self._request_json("POST", "chart/data", json=payload)
        except SupersetAdaptorError as exc:
            raise SupersetAdaptorError(
                f"chart/data failed for {chart_id}: {exc}"
            ) from exc

        sqls: List[str] = []
        used_query_indexes: set[int] = set()
        results = response_data.get("result", [])

        for idx, block in enumerate(results):
            before = len(sqls)
            self._append_sql_from_block(block, sqls)
            if len(sqls) > before:
                used_query_indexes.add(idx)

        return sqls, (used_query_indexes or None)

    def _append_sql_from_block(self, block: Dict[str, Any], sqls: List[str]) -> None:
        if sql_text := block.get("query"):
            sqls.append(sql_text.strip())

    def _get_dashboard(self, dashboard_id: Union[str, int]) -> Dict[str, Any]:
        data = self._request_json("GET", f"dashboard/{dashboard_id}")
        if "result" in data and isinstance(data["result"], dict):
            return data["result"]
        return data

    def _get_dashboard_charts(
        self, dashboard_id: Union[str, int]
    ) -> List[Dict[str, Any]]:
        data = self._request_json("GET", f"dashboard/{dashboard_id}/charts")
        charts = data.get("result", data)
        if not isinstance(charts, list):
            raise SupersetAdaptorError(f"Unexpected charts payload: {charts}")
        return charts

    def _get_chart(self, chart_id: Union[str, int]) -> Dict[str, Any]:
        data = self._request_json("GET", f"explore/?slice_id={chart_id}")
        chart = data.get("result", data)
        return chart

    def _normalize_api_base(self, api_base_url: str) -> str:
        base = (api_base_url or "").rstrip("/")
        if base.endswith("/api/v1"):
            return base
        return f"{base}/api/v1"

    def _extract_chart_id(
        self, chart_meta: Dict[str, Any]
    ) -> Optional[Union[int, str]]:
        form_data = _load_json_field(chart_meta.get("form_data")) or {}
        chart_id = (
            form_data.get("slice_id")
            or chart_meta.get("slice_id")
            or chart_meta.get("chart_id")
            or chart_meta.get("id")
        )
        return chart_id

    def _extract_datasource_ref(
        self,
        form_data: Optional[Dict[str, Any]] = None,
        chart_meta: Optional[Dict[str, Any]] = None,
        chart_detail: Optional[Dict[str, Any]] = None,
        query_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        ds_id: Optional[Union[int, str]] = None
        ds_type: Optional[str] = None
        name: Optional[str] = None

        if query_context:
            datasource = query_context.get("datasource")
            if isinstance(datasource, dict):
                ds_id = ds_id or _coerce_id(datasource.get("id"))
                ds_type = (
                    ds_type
                    or datasource.get("type")
                    or datasource.get("datasource_type")
                )
                name = (
                    name
                    or datasource.get("name")
                    or datasource.get("datasource_name")
                    or datasource.get("table_name")
                )

        if chart_detail:
            if not ds_id:
                ds_id = chart_detail.get("datasource_id") or chart_detail.get(
                    "dataset_id"
                )
                ds_type = ds_type or chart_detail.get("datasource_type")
            if not name:
                dataset_block = (
                    chart_detail.get("dataset")
                    if isinstance(chart_detail.get("dataset"), dict)
                    else {}
                )
                for candidate in (
                    chart_detail.get("datasource_name"),
                    chart_detail.get("table_name"),
                    dataset_block.get("datasource_name"),
                    dataset_block.get("table_name"),
                ):
                    if candidate:
                        name = candidate
                        break

        if chart_meta:
            ds_id = (
                ds_id or chart_meta.get("datasource_id") or chart_meta.get("dataset_id")
            )
            ds_type = ds_type or chart_meta.get("datasource_type")

        if form_data:
            ds_id = (
                ds_id or form_data.get("datasource_id") or form_data.get("dataset_id")
            )
            ds_type = ds_type or form_data.get("datasource_type")
            if not ds_id and "datasource" in form_data:
                parsed_id, parsed_type = _parse_datasource_value(
                    form_data.get("datasource")
                )
                ds_id = parsed_id or ds_id
                ds_type = parsed_type or ds_type

        ds_id = _coerce_id(ds_id)
        if ds_id is None:
            return None

        return {"id": ds_id, "type": ds_type}

    def _resolve_tables(self, datasource_ref: Optional[Dict[str, Any]]) -> List[str]:
        if not datasource_ref:
            return []

        dataset_id = datasource_ref.get("id")
        dataset_info = self.get_dataset(dataset_id) if dataset_id is not None else None
        return list(dataset_info.tables or []) if dataset_info else []

    def _tables_from_sql(self, sql: Optional[str]) -> List[str]:
        if not sql:
            return []
        read_dialect = self.dialect
        return [
            name
            for name in _extract_table_names(sql, read_dialect, ignore_empty=True)
            if name
        ]

    def _extract_query_metrics_dimensions(
        self,
        query_context: Dict[str, Any],
        table_name: Optional[str],
        only_query_indexes: Optional[set[int]] = None,
    ) -> tuple[List[MetricDef], List[DimensionDef]]:
        metrics: List[MetricDef] = []
        dimensions: List[DimensionDef] = []

        queries = query_context.get("queries") or []
        if not isinstance(queries, list):
            return metrics, dimensions

        for idx, query in enumerate(queries):
            if only_query_indexes is not None and idx not in only_query_indexes:
                continue
            if not isinstance(query, dict):
                continue
            metrics.extend(self._metrics_from_query(query, table_name))
            dimensions.extend(self._dimensions_from_query(query, table_name))

        return self._dedupe_metrics(metrics), self._dedupe_dimensions(dimensions)

    def _extract_form_data_metrics_dimensions(
        self, form_data: Dict[str, Any], table_name: Optional[str]
    ) -> tuple[List[MetricDef], List[DimensionDef]]:
        metrics: List[MetricDef] = []
        dimensions: List[DimensionDef] = []

        raw_metrics = form_data.get("metrics")
        if raw_metrics is None and "metric" in form_data:
            raw_metrics = [form_data.get("metric")]
        if isinstance(raw_metrics, list):
            for metric in raw_metrics:
                metric_def = self._normalize_metric(metric, table_name, origin="chart")
                if metric_def:
                    metrics.append(metric_def)
        elif raw_metrics:
            metric_def = self._normalize_metric(raw_metrics, table_name, origin="chart")
            if metric_def:
                metrics.append(metric_def)

        raw_dimensions: List[Any] = []
        for key in ("groupby", "columns", "all_columns"):
            items = form_data.get(key)
            if isinstance(items, list):
                raw_dimensions.extend(items)
        for key in ("granularity", "granularity_sqla", "time_column", "time_col"):
            value = form_data.get(key)
            if value:
                raw_dimensions.append(value)

        for item in raw_dimensions:
            dim = self._normalize_dimension(item, table_name, origin="chart")
            if dim:
                dimensions.append(dim)

        return self._dedupe_metrics(metrics), self._dedupe_dimensions(dimensions)

    def _metrics_from_query(
        self, query: Dict[str, Any], table_name: Optional[str]
    ) -> List[MetricDef]:
        metrics: List[MetricDef] = []
        for metric in query.get("metrics") or []:
            metric_def = self._normalize_metric(metric, table_name, origin="chart")
            if metric_def:
                metrics.append(metric_def)
        return metrics

    def _dimensions_from_query(
        self, query: Dict[str, Any], table_name: Optional[str]
    ) -> List[DimensionDef]:
        dimensions: List[DimensionDef] = []
        for key in ("groupby", "columns"):
            items = query.get(key) or []
            if not isinstance(items, list):
                continue
            for item in items:
                dim = self._normalize_dimension(item, table_name, origin="chart")
                if dim:
                    dimensions.append(dim)

        time_column = query.get("time_column") or query.get("time_col")
        if time_column:
            dim = self._normalize_dimension(time_column, table_name, origin="chart")
            if dim:
                dimensions.append(dim)

        return dimensions

    def _normalize_metric(
        self, metric: Any, table_name: Optional[str], origin: str
    ) -> Optional[MetricDef]:
        if isinstance(metric, str):
            name = metric.strip()
            if not name:
                return None
            return MetricDef(
                name=name, expression=name, table=table_name, origin=origin
            )

        if not isinstance(metric, dict):
            return None

        name = metric.get("label") or metric.get("metric_name") or metric.get("name")
        description = metric.get("description") or metric.get("verbose_name")

        expression = (
            metric.get("expression")
            or metric.get("sqlExpression")
            or metric.get("sql_expression")
        )
        if not expression and metric.get("expressionType") == "SIMPLE":
            aggregate = metric.get("aggregate") or metric.get("aggregation")
            column = metric.get("column") or {}
            column_name = None
            if isinstance(column, dict):
                column_name = column.get("column_name") or column.get("name")
            elif isinstance(column, str):
                column_name = column
            if aggregate and column_name:
                expression = f"{aggregate}({column_name})"

        if not expression and metric.get("expressionType") == "SQL":
            expression = metric.get("sqlExpression")

        if not name and expression:
            name = expression
        if not name:
            return None

        return MetricDef(
            name=str(name),
            expression=str(expression or name),
            table=table_name,
            description=description,
            origin=origin,
            extra=metric,
        )

    def _normalize_dimension(
        self, item: Any, table_name: Optional[str], origin: str
    ) -> Optional[DimensionDef]:
        if isinstance(item, str):
            name = item.strip()
            if not name:
                return None
            return DimensionDef(name=name, table=table_name, origin=origin)

        if not isinstance(item, dict):
            return None

        name = (
            item.get("column_name")
            or item.get("name")
            or item.get("label")
            or item.get("verbose_name")
        )
        if not name:
            return None

        title = item.get("verbose_name") or item.get("label")
        data_type = item.get("type") or item.get("data_type") or item.get("datatype")
        description = item.get("description")

        return DimensionDef(
            name=str(name),
            title=title,
            data_type=data_type,
            table=table_name,
            description=description,
            origin=origin,
            extra=item,
        )

    def _dedupe_metrics(self, metrics: List[MetricDef]) -> List[MetricDef]:
        seen = set()
        unique: List[MetricDef] = []
        for metric in metrics:
            key = (metric.name, metric.expression)
            if key in seen:
                continue
            seen.add(key)
            unique.append(metric)
        return unique

    def _dedupe_dimensions(self, dimensions: List[DimensionDef]) -> List[DimensionDef]:
        seen = set()
        unique: List[DimensionDef] = []
        for dimension in dimensions:
            key = (dimension.name,)
            if key in seen:
                continue
            seen.add(key)
            unique.append(dimension)
        return unique

    def _dedupe_tables(self, tables: List[str]) -> List[str]:
        seen = set()
        unique: List[str] = []
        for table in tables:
            if not table:
                continue
            name = str(table)
            if name in seen:
                continue
            seen.add(name)
            unique.append(name)
        return unique

    def _parse_dataset_columns(
        self, dataset: Dict[str, Any], table_name: Optional[str]
    ) -> List[ColumnInfo]:
        columns: List[ColumnInfo] = []
        for column in dataset.get("columns") or []:
            if not isinstance(column, dict):
                continue
            name = column.get("column_name") or column.get("name")
            if not name:
                continue
            columns.append(
                ColumnInfo(
                    name=str(name),
                    data_type=column.get("type") or column.get("data_type"),
                    description=column.get("description"),
                    table=table_name,
                    extra=column,
                )
            )
        return columns

    def _parse_dataset_metrics(
        self, dataset: Dict[str, Any], table_name: Optional[str]
    ) -> List[MetricDef]:
        metrics: List[MetricDef] = []
        for metric in dataset.get("metrics") or []:
            metric_def = self._normalize_metric(metric, table_name, origin="dataset")
            if metric_def:
                metrics.append(metric_def)
        return self._dedupe_metrics(metrics)

    def _parse_dataset_dimensions(
        self,
        dataset: Dict[str, Any],
        table_name: Optional[str],
        columns: List[ColumnInfo],
    ) -> List[DimensionDef]:
        raw_columns = dataset.get("columns") or []
        has_flags = any(
            isinstance(col, dict)
            and any(key in col for key in ("groupby", "filterable", "is_dttm"))
            for col in raw_columns
        )

        dimensions: List[DimensionDef] = []
        if raw_columns:
            for column in raw_columns:
                if not isinstance(column, dict):
                    continue
                if has_flags and not (
                    column.get("groupby")
                    or column.get("filterable")
                    or column.get("is_dttm")
                ):
                    continue
                dim = self._normalize_dimension(column, table_name, origin="dataset")
                if dim:
                    dimensions.append(dim)

        if not dimensions and columns:
            for column in columns:
                dimensions.append(
                    DimensionDef(
                        name=column.name,
                        title=column.name,
                        data_type=column.data_type,
                        table=column.table,
                        description=column.description,
                        origin="dataset",
                    )
                )

        return self._dedupe_dimensions(dimensions)

    def _request_json(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        response = self._request(method, endpoint, **kwargs)
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise SupersetAdaptorError(
                f"Invalid JSON response for {endpoint}: {exc}"
            ) from exc

    def _request(
        self, method: str, endpoint: str, require_auth: bool = True, **kwargs
    ) -> httpx.Response:
        url = f"{self._api_base}/{endpoint.lstrip('/')}"
        headers = kwargs.pop("headers", {})
        if require_auth:
            self._ensure_authenticated()
            headers.update(self._auth_headers())

        try:
            response = self._client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise SupersetAdaptorError(
                f"Superset API {method} {endpoint} failed with {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SupersetAdaptorError(
                f"Superset API {method} {endpoint} failed: {exc}"
            ) from exc

    def _auth_headers(self) -> Dict[str, str]:
        if not self._auth_header_value:
            return {}
        return self._auth_header_value

    def _ensure_authenticated(self) -> None:
        if (
            self._auth_header_value
            and self._token_expiration
            and time.time() < self._token_expiration
        ):
            return
        self._authenticate()

    def _authenticate(self) -> None:
        if self._try_login_by_browser():
            logger.info("Login by browser succeeded")
            return
        logger.info("Login by api succeeded")
        payload = {
            "username": self.auth_params.username,
            "password": self.auth_params.password,
            "refresh": True,
            "provider": "db"
            if not self.auth_params.extra
            else self.auth_params.extra.get("provider") or "db",
        }
        try:
            response = self._request(
                "POST", "security/login", require_auth=False, json=payload
            )
        except SupersetAdaptorError as exc:
            raise SupersetAdaptorError(f"Authentication failed: {exc}") from exc

        data = response.json()
        token_payload = data.get("result", data)
        access_token = token_payload.get("access_token")
        token_type = token_payload.get("token_type", "Bearer")
        expires_in = token_payload.get("expires_in")

        if not access_token:
            raise SupersetAdaptorError("Superset login response missing access_token")

        auth_headers = {"Authorization": f"{token_type} {access_token}".strip()}
        self._auth_header_value = auth_headers

        # Fetch CSRF token required for write operations (POST/PUT/DELETE)
        try:
            csrf_resp = self._client.get(
                f"{self._api_base}/security/csrf_token/",
                headers=auth_headers,
            )
            if csrf_resp.is_success:
                csrf_token = csrf_resp.json().get("result")
                if csrf_token:
                    self._auth_header_value = {
                        **auth_headers,
                        "X-CSRFToken": csrf_token,
                    }
        except Exception as exc:
            logger.debug(f"Failed to fetch CSRF token, write ops may fail: {exc}")

        if isinstance(expires_in, (int, float)) and expires_in > 0:
            self._token_expiration = time.time() + expires_in - 60
        else:
            self._token_expiration = time.time() + 3600

    def _try_login_by_browser(self) -> bool:
        login_page_resp = self._client.get("/login")
        if not login_page_resp.is_success:
            return False
        login_page_html = login_page_resp.text

        csrf_match = re.search(
            r'name="csrf_token" type="hidden" value="([^"]+)"', login_page_html
        )
        csrf_token = csrf_match.group(1) if csrf_match else None
        if not csrf_token:
            return False
        browser_base_url = self.api_base_url.rstrip("/")
        if browser_base_url.endswith("/api/v1"):
            browser_base_url = browser_base_url[:-7]
        login_resp = self._client.post(
            "/login/",
            data={
                "username": self.auth_params.username,
                "password": self.auth_params.password,
                "csrf_token": csrf_token,
            },
            headers={
                "Referer": f"{browser_base_url}/login/",
            },
            follow_redirects=True,
        )
        if not login_resp.is_success:
            return False
        csrf_response = self._client.get("/api/v1/security/csrf_token/")
        if not csrf_response.is_success:
            return False
        csrf_token = csrf_response.json().get("result")
        if csrf_token:
            self._auth_header_value = {"X-CSRFToken": csrf_token}
            self._token_expiration = time.time() + 3600
            return True
        return False


# =========================================================================
# Module-level helper functions (migrated from original)
# =========================================================================


def _normalize_series_columns_in_query_context(query_context: Dict[str, Any]) -> None:
    queries = query_context.get("queries")
    if not isinstance(queries, list):
        return
    for query in queries:
        if not isinstance(query, dict):
            continue
        _normalize_series_columns_in_query(query)


def _normalize_series_columns_in_query(query: Dict[str, Any]) -> None:
    series_columns = query.get("series_columns")
    if series_columns is None:
        return

    def _ensure_list(value: Any) -> Optional[List[Any]]:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return [value]

    def _column_name(item: Any) -> Optional[str]:
        if isinstance(item, dict):
            return item.get("column_name") or item.get("name") or item.get("label")
        if item is None:
            return None
        return str(item)

    def _dedupe(items: List[str]) -> List[str]:
        seen: set[str] = set()
        unique: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return unique

    series_list = _ensure_list(series_columns)
    if series_list is None:
        return

    series_names = _dedupe(
        [name for item in series_list if (name := _column_name(item))]
    )

    columns_list = _ensure_list(query.get("columns")) or []
    column_names = _dedupe(
        [name for item in columns_list if (name := _column_name(item))]
    )

    if series_names:
        for name in series_names:
            if name not in column_names:
                column_names.append(name)
        query["columns"] = column_names
    elif columns_list:
        query["columns"] = columns_list

    query["series_columns"] = series_names


def _parse_datasource_value(
    value: Any,
) -> tuple[Optional[Union[int, str]], Optional[str]]:
    if value is None:
        return None, None
    if isinstance(value, dict):
        return _coerce_id(value.get("id")), value.get("type") or value.get(
            "datasource_type"
        )
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        if "__" in value:
            id_part, type_part = value.split("__", 1)
            return _coerce_id(id_part), type_part
        if value.isdigit():
            return int(value), None
    return None, None


def _coerce_id(value: Any) -> Optional[Union[int, str]]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _load_json_field(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.debug(f"Failed to decode JSON field: {value[:128]}")
    return None
