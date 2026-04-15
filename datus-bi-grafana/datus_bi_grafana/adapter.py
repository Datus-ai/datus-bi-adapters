# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

import logging
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx

from datus_bi_core import (
    BIAdapterBase,
    ChartWriteMixin,
    DashboardWriteMixin,
    DatusBiException,
)
from datus_bi_core.models import (
    AuthParam,
    AuthType,
    ChartInfo,
    ChartSpec,
    DashboardInfo,
    DashboardSpec,
    DatasetInfo,
)

logger = logging.getLogger(__name__)

_PANEL_TYPE_MAP = {
    "bar": "barchart",
    "line": "timeseries",
    "pie": "piechart",
    "table": "table",
    "big_number": "stat",
    "scatter": "scatter",
}


class GrafanaAdapter(BIAdapterBase, DashboardWriteMixin, ChartWriteMixin):
    """Grafana BI adapter — supports basic auth (username/password) or Bearer token."""

    def __init__(
        self,
        api_base_url: str,
        auth_params: AuthParam,
        dialect: str,
        timeout: float = 30.0,
    ):
        super().__init__(api_base_url, auth_params, dialect, timeout)
        self._base = (api_base_url or "").rstrip("/")

        # Prefer basic auth (username + password); fall back to Bearer token
        username = (auth_params.username or "").strip()
        password = (auth_params.password or "").strip()
        api_key = (auth_params.api_key or "").strip()

        if username and password:
            self._client = httpx.Client(
                base_url=self._base,
                timeout=timeout,
                auth=(username, password),
                headers={"Content-Type": "application/json"},
                follow_redirects=True,
            )
            self._auth_mode = "basic"
        else:
            self._client = httpx.Client(
                base_url=self._base,
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                follow_redirects=True,
            )
            self._auth_mode = "token"

    def close(self):
        self._client.close()

    def platform_name(self) -> str:
        return "grafana"

    def auth_type(self) -> AuthType:
        return AuthType.LOGIN if self._auth_mode == "basic" else AuthType.API_KEY

    def parse_dashboard_id(self, dashboard_url: str) -> Union[int, str]:
        stripped = (dashboard_url or "").strip()
        if not stripped:
            return ""
        parsed = urlparse(stripped)
        if parsed.scheme and parsed.netloc:
            parts = [p for p in parsed.path.split("/") if p]
            if "d" in parts:
                idx = parts.index("d")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        return stripped

    def _request_json(self, method: str, path: str, **kwargs) -> Any:
        resp = self._client.request(method, path, **kwargs)
        if not resp.is_success:
            raise DatusBiException(
                f"Grafana API {method} {path} returned {resp.status_code}: {resp.text}",
                "grafana",
            )
        if resp.content:
            return resp.json()
        return {}

    # --- Read operations ---

    def get_dashboard_info(
        self, dashboard_id: Union[int, str]
    ) -> Optional[DashboardInfo]:
        try:
            data = self._request_json("GET", f"/api/dashboards/uid/{dashboard_id}")
            dash = data.get("dashboard", {})
            panels = dash.get("panels", [])
            chart_ids = [p["id"] for p in panels if isinstance(p, dict) and "id" in p]
            meta = data.get("meta", {})
            return DashboardInfo(
                id=dashboard_id,
                name=dash.get("title", str(dashboard_id)),
                description=dash.get("description"),
                chart_ids=chart_ids,
                extra={"meta": meta, "uid": dashboard_id},
            )
        except Exception as exc:
            logger.warning(f"get_dashboard_info failed for {dashboard_id}: {exc}")
            return None

    def list_charts(self, dashboard_id: Union[int, str]) -> List[ChartInfo]:
        try:
            data = self._request_json("GET", f"/api/dashboards/uid/{dashboard_id}")
            dash = data.get("dashboard", {})
            panels = dash.get("panels", [])
            return [
                ChartInfo(
                    id=p["id"],
                    name=p.get("title", str(p["id"])),
                    chart_type=p.get("type"),
                    description=p.get("description"),
                    extra={"panel": p},
                )
                for p in panels
                if isinstance(p, dict) and "id" in p
            ]
        except Exception as exc:
            logger.warning(f"list_charts failed for dashboard {dashboard_id}: {exc}")
            return []

    def get_chart(
        self, chart_id: Union[int, str], dashboard_id: Union[int, str, None] = None
    ) -> Optional[ChartInfo]:
        if not dashboard_id:
            raise DatusBiException(
                "Grafana requires dashboard_id to get a panel", "grafana"
            )
        charts = self.list_charts(dashboard_id)
        for chart in charts:
            if str(chart.id) == str(chart_id):
                return chart
        return None

    def list_datasets(self, dashboard_id: Union[int, str]) -> List[DatasetInfo]:
        try:
            data = self._request_json("GET", "/api/datasources")
            return [
                DatasetInfo(
                    id=ds["id"],
                    name=ds.get("name", str(ds["id"])),
                    dialect=ds.get("type", self.dialect),
                    description=ds.get("typeLogoUrl"),
                    extra={"grafana_ds": ds},
                )
                for ds in data
                if isinstance(ds, dict)
            ]
        except Exception as exc:
            logger.warning(f"list_datasets failed: {exc}")
            return []

    def get_dataset(
        self, dataset_id: Union[int, str], dashboard_id: Union[int, str, None] = None
    ) -> Optional[DatasetInfo]:
        try:
            data = self._request_json("GET", f"/api/datasources/{dataset_id}")
            return DatasetInfo(
                id=data.get("id", dataset_id),
                name=data.get("name", str(dataset_id)),
                dialect=data.get("type", self.dialect),
                extra={"grafana_ds": data},
            )
        except Exception as exc:
            logger.warning(f"get_dataset failed for {dataset_id}: {exc}")
            return None

    # --- BIAdapterBase — list_dashboards ---

    def list_dashboards(
        self, search: str = "", page_size: int = 20
    ) -> List[DashboardInfo]:
        params: Dict[str, Any] = {"type": "dash-db", "limit": page_size}
        if search:
            params["query"] = search
        try:
            results = self._request_json("GET", "/api/search", params=params)
            return [
                DashboardInfo(
                    id=d.get("uid", d.get("id", "")),
                    name=d.get("title", ""),
                    extra={"grafana": d},
                )
                for d in results
                if isinstance(d, dict)
            ]
        except Exception as exc:
            logger.warning(f"list_dashboards failed: {exc}")
            return []

    # --- DashboardWriteMixin ---

    def _create_empty_dashboard_payload(
        self, title: str, description: str = ""
    ) -> Dict[str, Any]:
        return {
            "dashboard": {
                "id": None,
                "uid": None,
                "title": title,
                "description": description,
                "panels": [],
                "schemaVersion": 38,
                "version": 0,
            },
            "overwrite": False,
        }

    def create_dashboard(self, spec: DashboardSpec) -> DashboardInfo:
        payload = self._create_empty_dashboard_payload(spec.title, spec.description)
        data = self._request_json("POST", "/api/dashboards/db", json=payload)
        return DashboardInfo(
            id=data.get("uid", data.get("id", "")),
            name=spec.title,
            description=spec.description,
            extra={"url": data.get("url"), "slug": data.get("slug")},
        )

    def update_dashboard(
        self, dashboard_id: Union[int, str], spec: DashboardSpec
    ) -> DashboardInfo:
        data = self._request_json("GET", f"/api/dashboards/uid/{dashboard_id}")
        dash = data.get("dashboard", {})
        dash["title"] = spec.title
        if spec.description:
            dash["description"] = spec.description
        dash.update(spec.extra)
        self._request_json(
            "POST", "/api/dashboards/db", json={"dashboard": dash, "overwrite": True}
        )
        return DashboardInfo(
            id=dashboard_id, name=spec.title, description=spec.description
        )

    def delete_dashboard(self, dashboard_id: Union[int, str]) -> bool:
        try:
            self._request_json("DELETE", f"/api/dashboards/uid/{dashboard_id}")
            return True
        except Exception:
            return False

    # --- ChartWriteMixin ---

    # --- Datasource management ---

    def create_datasource(
        self,
        name: str,
        db_type: str = "grafana-postgresql-datasource",
        url: str = "",
        user: str = "",
        password: str = "",
        database: str = "",
        extra_json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new datasource in Grafana.  Returns the full datasource object (including uid)."""
        payload: Dict[str, Any] = {
            "name": name,
            "type": db_type,
            "access": "proxy",
            "url": url,
            "user": user,
            "jsonData": extra_json_data or {},
        }
        if database:
            payload["jsonData"]["database"] = database
        if password:
            payload["secureJsonData"] = {"password": password}
        resp = self._request_json("POST", "/api/datasources", json=payload)
        # Grafana create response wraps the datasource under {"datasource": {...}, "id": ..., "message": ...}
        return resp.get("datasource", resp)

    def find_or_create_datasource(
        self,
        name: str,
        db_type: str = "grafana-postgresql-datasource",
        url: str = "",
        user: str = "",
        password: str = "",
        database: str = "",
        extra_json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return existing datasource by name, or create it if it doesn't exist."""
        sources = self._request_json("GET", "/api/datasources")
        for ds in sources:
            if ds.get("name") == name:
                return ds
        return self.create_datasource(
            name, db_type, url, user, password, database, extra_json_data
        )

    # --- ChartWriteMixin ---

    def _build_panel(self, spec: ChartSpec, panel_id: int) -> Dict[str, Any]:
        panel_type = _PANEL_TYPE_MAP.get(spec.chart_type, "timeseries")
        datasource_uid: Optional[str] = spec.extra.get("datasource_uid")
        datasource_type: str = spec.extra.get(
            "datasource_type", "grafana-postgresql-datasource"
        )

        # Fall back to dataset_id: look up datasource uid by numeric ID
        if not datasource_uid and spec.dataset_id is not None:
            try:
                ds_data = self._request_json(
                    "GET", f"/api/datasources/{spec.dataset_id}"
                )
                datasource_uid = ds_data.get("uid")
                datasource_type = ds_data.get("type", datasource_type)
            except Exception as exc:
                logger.warning(
                    f"Failed to resolve dataset_id {spec.dataset_id} to datasource: {exc}"
                )

        ds_ref: Optional[Dict[str, str]] = None
        if datasource_uid:
            ds_ref = {"type": datasource_type, "uid": datasource_uid}

        panel: Dict[str, Any] = {
            "id": panel_id,
            "type": panel_type,
            "title": spec.title,
            "description": spec.description,
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
            "targets": [],
            "options": {},
        }
        if ds_ref:
            panel["datasource"] = ds_ref

        if spec.sql:
            target: Dict[str, Any] = {
                "rawSql": spec.sql,
                "refId": "A",
                "format": "table",
            }
            if ds_ref:
                target["datasource"] = ds_ref
            panel["targets"] = [target]

        # Copy extra except internal keys already consumed
        extra = {
            k: v
            for k, v in spec.extra.items()
            if k not in ("datasource_uid", "datasource_type")
        }
        panel.update(extra)
        return panel

    def create_chart(
        self, spec: ChartSpec, dashboard_id: Optional[Union[int, str]] = None
    ) -> ChartInfo:
        if not dashboard_id:
            raise DatusBiException(
                "Grafana requires dashboard_id to create a panel", "grafana"
            )
        data = self._request_json("GET", f"/api/dashboards/uid/{dashboard_id}")
        dash = data.get("dashboard", {})
        panels = dash.get("panels", [])
        new_id = (
            max(
                (p.get("id", 0) for p in panels if isinstance(p.get("id"), int)),
                default=0,
            )
            + 1
        )
        # Stack below existing panels to avoid overlap
        max_y = max(
            (
                p.get("gridPos", {}).get("y", 0) + p.get("gridPos", {}).get("h", 0)
                for p in panels
            ),
            default=0,
        )
        panel = self._build_panel(spec, new_id)
        panel["gridPos"]["y"] = max_y
        panels.append(panel)
        dash["panels"] = panels
        self._request_json(
            "POST", "/api/dashboards/db", json={"dashboard": dash, "overwrite": True}
        )
        return ChartInfo(
            id=new_id,
            name=spec.title,
            description=spec.description,
            chart_type=spec.chart_type,
        )

    def update_chart(self, chart_id: Union[int, str], spec: ChartSpec) -> ChartInfo:
        raise DatusBiException(
            "update_chart requires dashboard_id for Grafana; use create_chart with dashboard_id instead",
            "grafana",
        )

    def delete_chart(self, chart_id: Union[int, str]) -> bool:
        logger.warning(
            "delete_chart requires dashboard_id for Grafana; returning False"
        )
        return False

    def add_chart_to_dashboard(
        self, dashboard_id: Union[int, str], chart_id: Union[int, str]
    ) -> bool:
        # In Grafana, charts live inside dashboards; this is effectively a no-op if chart was created via create_chart
        logger.info(
            f"Grafana: panel {chart_id} should already be in dashboard {dashboard_id}"
        )
        return True
