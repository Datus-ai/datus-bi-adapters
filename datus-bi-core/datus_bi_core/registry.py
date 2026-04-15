# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

"""
BI Adapter Registry

Responsibilities:
1. Register BI adapters with capabilities metadata
2. Auto-discover plugins via Entry Points
3. Provide adapter metadata for CLI selection
"""

import logging
from typing import ClassVar, Dict, Optional, Set, Type

from datus_bi_core.base import BIAdapterBase
from datus_bi_core.models import AuthType

logger = logging.getLogger(__name__)


class AdapterMetadata:
    """Metadata for a BI adapter."""

    def __init__(
        self,
        platform: str,
        adapter_class: Type[BIAdapterBase],
        auth_type: AuthType,
        display_name: Optional[str] = None,
        capabilities: Optional[Set[str]] = None,
    ) -> None:
        self.platform = platform
        self.adapter_class = adapter_class
        self.auth_type = auth_type
        self.display_name = display_name or platform.capitalize()
        self.capabilities: Set[str] = capabilities or set()


class BIAdapterRegistry:
    """Central registry for BI adapters."""

    _adapters: ClassVar[Dict[str, Type[BIAdapterBase]]] = {}
    _metadata: ClassVar[Dict[str, AdapterMetadata]] = {}
    _initialized: ClassVar[bool] = False

    @classmethod
    def register(
        cls,
        platform: str,
        adapter_class: Type[BIAdapterBase],
        auth_type: AuthType,
        display_name: Optional[str] = None,
        capabilities: Optional[Set[str]] = None,
    ) -> None:
        """Register a BI adapter."""
        key = (platform or "").strip().lower()
        if not key:
            logger.warning("Skipped registering BI adapter with empty platform name.")
            return

        cls._adapters[key] = adapter_class
        cls._metadata[key] = AdapterMetadata(
            platform=key,
            adapter_class=adapter_class,
            auth_type=auth_type,
            display_name=display_name,
            capabilities=capabilities,
        )
        logger.debug(f"Registered BI adapter: {key} -> {adapter_class.__name__}")

    @classmethod
    def get(cls, platform: str) -> Optional[Type[BIAdapterBase]]:
        cls.discover_adapters()
        return cls._adapters.get((platform or "").strip().lower())

    @classmethod
    def get_metadata(cls, platform: str) -> Optional[AdapterMetadata]:
        cls.discover_adapters()
        return cls._metadata.get((platform or "").strip().lower())

    @classmethod
    def get_capabilities(cls, platform: str) -> Set[str]:
        meta = cls.get_metadata(platform)
        return meta.capabilities if meta else set()

    @classmethod
    def list_adapters(cls) -> Dict[str, Type[BIAdapterBase]]:
        cls.discover_adapters()
        return cls._adapters.copy()

    @classmethod
    def is_registered(cls, platform: str) -> bool:
        cls.discover_adapters()
        return (platform or "").strip().lower() in cls._adapters

    @classmethod
    def discover_adapters(cls) -> None:
        """Load built-in adapters and optional plugins."""
        if cls._initialized:
            return
        cls._initialized = True

        cls._load_builtin_adapters()
        cls._discover_plugins()

    @classmethod
    def _load_builtin_adapters(cls) -> None:
        # No built-in adapters; all are loaded via entry_points
        pass

    @classmethod
    def _discover_plugins(cls) -> None:
        try:
            from importlib.metadata import entry_points

            try:
                adapter_eps = entry_points(group="datus.bi_adapters")
            except TypeError:
                eps = entry_points()
                adapter_eps = eps.get("datus.bi_adapters", [])

            for ep in adapter_eps:
                try:
                    register_func = ep.load()
                    register_func()
                    logger.info("Discovered BI adapter: %s", ep.name)
                except Exception as exc:
                    logger.warning("Failed to load BI adapter %s: %s", ep.name, exc)
        except Exception as exc:
            logger.warning("BI adapter entry point discovery failed: %s", exc)


adapter_registry = BIAdapterRegistry()
