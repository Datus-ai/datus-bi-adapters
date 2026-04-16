# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class AuthType(Enum):
    LOGIN = "login"
    API_KEY = "api_key"


class AuthParam(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


# --- Existing read models (migrated from base_adapter.py) ---


class ColumnInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    data_type: Optional[str] = None
    description: Optional[str] = None
    table: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class MetricDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    expression: str
    table: Optional[str] = None
    description: Optional[str] = None
    origin: str = "dataset"  # dataset | chart | semantic
    extra: Dict[str, Any] = Field(default_factory=dict)


class DimensionDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    title: Optional[str] = None
    data_type: Optional[str] = None
    table: Optional[str] = None
    description: Optional[str] = None
    origin: str = "dataset"
    extra: Dict[str, Any] = Field(default_factory=dict)


class DatasetInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Union[int, str]
    name: str
    dialect: Optional[str] = None
    description: Optional[str] = None
    tables: Optional[List[str]] = None
    columns: Optional[List[ColumnInfo]] = None
    metrics: Optional[List[MetricDef]] = None
    dimensions: Optional[List[DimensionDef]] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class QuerySpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["sql", "semantic"]
    payload: Dict[str, Any] = Field(default_factory=dict)
    sql: Optional[List[str]] = None
    tables: Optional[List[str]] = None
    metrics: Optional[List[MetricDef]] = None
    dimensions: Optional[List[DimensionDef]] = None


class ChartInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Union[int, str]
    name: str
    description: Optional[str] = None
    query: Optional[QuerySpec] = None
    chart_type: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class ChartDataResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    chart_id: Union[int, str]
    columns: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    sql: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class DashboardInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Union[int, str]
    name: str
    description: Optional[str] = None
    chart_ids: List[Union[int, str]] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


# --- New write operation models ---


class ChartSpec(BaseModel):
    """LLM-constructed chart creation/modification request spec."""

    chart_type: str  # "bar"|"line"|"pie"|"table"|"big_number"|"scatter"
    title: str
    description: str = ""
    dataset_id: Optional[Union[int, str]] = None
    sql: Optional[str] = None
    x_axis: Optional[str] = None
    metrics: Optional[List[str]] = None
    dimensions: Optional[List[str]] = None
    filters: Optional[List[Dict[str, Any]]] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class DatasetSpec(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    name: str
    sql: Optional[str] = None
    database_id: int
    db_schema: str = ""
    description: str = ""


class DashboardSpec(BaseModel):
    title: str
    description: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict)
