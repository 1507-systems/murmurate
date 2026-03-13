import pytest
from murmurate.plugins.base import SitePlugin
from murmurate.transport.base import Transport
from murmurate.models import TransportType

def test_site_plugin_is_abstract():
    with pytest.raises(TypeError):
        SitePlugin()

def test_transport_is_abstract():
    with pytest.raises(TypeError):
        Transport()

def test_transport_type_enum_values():
    assert TransportType.HTTP.value == "http"
    assert TransportType.BROWSER.value == "browser"
    assert TransportType.EITHER.value == "either"
