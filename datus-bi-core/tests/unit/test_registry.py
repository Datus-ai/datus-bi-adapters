from datus_bi_core.models import AuthType
from datus_bi_core.registry import BIAdapterRegistry


class MockAdapter:
    pass


def test_register_and_get():
    # Save original state
    orig_adapters = BIAdapterRegistry._adapters.copy()
    orig_metadata = BIAdapterRegistry._metadata.copy()
    orig_init = BIAdapterRegistry._initialized
    try:
        BIAdapterRegistry._initialized = True  # Skip discovery
        BIAdapterRegistry.register(
            "mock_platform",
            MockAdapter,
            auth_type=AuthType.LOGIN,
            display_name="Mock",
            capabilities={"list_dashboards"},
        )
        assert BIAdapterRegistry.get("mock_platform") is MockAdapter
    finally:
        BIAdapterRegistry._adapters = orig_adapters
        BIAdapterRegistry._metadata = orig_metadata
        BIAdapterRegistry._initialized = orig_init


def test_get_capabilities():
    orig_adapters = BIAdapterRegistry._adapters.copy()
    orig_metadata = BIAdapterRegistry._metadata.copy()
    orig_init = BIAdapterRegistry._initialized
    try:
        BIAdapterRegistry._initialized = True
        BIAdapterRegistry.register(
            "mock2",
            MockAdapter,
            auth_type=AuthType.API_KEY,
            capabilities={"dashboard_write", "chart_write"},
        )
        caps = BIAdapterRegistry.get_capabilities("mock2")
        assert "dashboard_write" in caps
        assert "chart_write" in caps
        assert len(caps) == 2
    finally:
        BIAdapterRegistry._adapters = orig_adapters
        BIAdapterRegistry._metadata = orig_metadata
        BIAdapterRegistry._initialized = orig_init


def test_list_adapters():
    orig_adapters = BIAdapterRegistry._adapters.copy()
    orig_metadata = BIAdapterRegistry._metadata.copy()
    orig_init = BIAdapterRegistry._initialized
    try:
        BIAdapterRegistry._initialized = True
        BIAdapterRegistry._adapters = {}
        BIAdapterRegistry._metadata = {}
        BIAdapterRegistry.register("mock_list", MockAdapter, auth_type=AuthType.LOGIN)
        all_adapters = BIAdapterRegistry.list_adapters()
        assert "mock_list" in all_adapters
        assert all_adapters["mock_list"] is MockAdapter
    finally:
        BIAdapterRegistry._adapters = orig_adapters
        BIAdapterRegistry._metadata = orig_metadata
        BIAdapterRegistry._initialized = orig_init


def test_is_registered():
    orig_adapters = BIAdapterRegistry._adapters.copy()
    orig_metadata = BIAdapterRegistry._metadata.copy()
    orig_init = BIAdapterRegistry._initialized
    try:
        BIAdapterRegistry._initialized = True
        BIAdapterRegistry._adapters = {}
        BIAdapterRegistry._metadata = {}
        BIAdapterRegistry.register("mock_check", MockAdapter, auth_type=AuthType.LOGIN)
        assert BIAdapterRegistry.is_registered("mock_check") is True
        assert BIAdapterRegistry.is_registered("nonexistent") is False
    finally:
        BIAdapterRegistry._adapters = orig_adapters
        BIAdapterRegistry._metadata = orig_metadata
        BIAdapterRegistry._initialized = orig_init


def test_get_metadata():
    orig_adapters = BIAdapterRegistry._adapters.copy()
    orig_metadata = BIAdapterRegistry._metadata.copy()
    orig_init = BIAdapterRegistry._initialized
    try:
        BIAdapterRegistry._initialized = True
        BIAdapterRegistry._adapters = {}
        BIAdapterRegistry._metadata = {}
        BIAdapterRegistry.register(
            "mock_meta",
            MockAdapter,
            auth_type=AuthType.API_KEY,
            display_name="Mock Meta",
            capabilities={"read"},
        )
        meta = BIAdapterRegistry.get_metadata("mock_meta")
        assert meta is not None
        assert meta.platform == "mock_meta"
        assert meta.auth_type == AuthType.API_KEY
        assert meta.display_name == "Mock Meta"
        assert meta.capabilities == {"read"}
        assert BIAdapterRegistry.get_metadata("nonexistent") is None
    finally:
        BIAdapterRegistry._adapters = orig_adapters
        BIAdapterRegistry._metadata = orig_metadata
        BIAdapterRegistry._initialized = orig_init


def test_register_empty_platform():
    orig_adapters = BIAdapterRegistry._adapters.copy()
    orig_metadata = BIAdapterRegistry._metadata.copy()
    orig_init = BIAdapterRegistry._initialized
    try:
        BIAdapterRegistry._initialized = True
        BIAdapterRegistry._adapters = {}
        BIAdapterRegistry._metadata = {}
        BIAdapterRegistry.register("", MockAdapter, auth_type=AuthType.LOGIN)
        assert BIAdapterRegistry.get("") is None
    finally:
        BIAdapterRegistry._adapters = orig_adapters
        BIAdapterRegistry._metadata = orig_metadata
        BIAdapterRegistry._initialized = orig_init
