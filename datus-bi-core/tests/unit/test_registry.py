from datus_bi_core.models import AuthType
from datus_bi_core.registry import BIAdaptorRegistry


class MockAdaptor:
    pass


def test_register_and_get():
    # Save original state
    orig_adaptors = BIAdaptorRegistry._adaptors.copy()
    orig_metadata = BIAdaptorRegistry._metadata.copy()
    orig_init = BIAdaptorRegistry._initialized
    try:
        BIAdaptorRegistry._initialized = True  # Skip discovery
        BIAdaptorRegistry.register(
            "mock_platform",
            MockAdaptor,
            auth_type=AuthType.LOGIN,
            display_name="Mock",
            capabilities={"list_dashboards"},
        )
        assert BIAdaptorRegistry.get("mock_platform") is MockAdaptor
    finally:
        BIAdaptorRegistry._adaptors = orig_adaptors
        BIAdaptorRegistry._metadata = orig_metadata
        BIAdaptorRegistry._initialized = orig_init


def test_get_capabilities():
    orig_adaptors = BIAdaptorRegistry._adaptors.copy()
    orig_metadata = BIAdaptorRegistry._metadata.copy()
    orig_init = BIAdaptorRegistry._initialized
    try:
        BIAdaptorRegistry._initialized = True
        BIAdaptorRegistry.register(
            "mock2",
            MockAdaptor,
            auth_type=AuthType.API_KEY,
            capabilities={"dashboard_write", "chart_write"},
        )
        caps = BIAdaptorRegistry.get_capabilities("mock2")
        assert "dashboard_write" in caps
    finally:
        BIAdaptorRegistry._adaptors = orig_adaptors
        BIAdaptorRegistry._metadata = orig_metadata
        BIAdaptorRegistry._initialized = orig_init


def test_register_empty_platform():
    orig_adaptors = BIAdaptorRegistry._adaptors.copy()
    orig_metadata = BIAdaptorRegistry._metadata.copy()
    orig_init = BIAdaptorRegistry._initialized
    try:
        BIAdaptorRegistry._initialized = True
        BIAdaptorRegistry._adaptors = {}
        BIAdaptorRegistry._metadata = {}
        BIAdaptorRegistry.register("", MockAdaptor, auth_type=AuthType.LOGIN)
        assert BIAdaptorRegistry.get("") is None
    finally:
        BIAdaptorRegistry._adaptors = orig_adaptors
        BIAdaptorRegistry._metadata = orig_metadata
        BIAdaptorRegistry._initialized = orig_init
