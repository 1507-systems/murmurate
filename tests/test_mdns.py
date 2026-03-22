"""
Tests for the mDNS advertiser (api/mdns.py).

Verifies:
  - MdnsAdvertiser can be constructed and starts as inactive.
  - start() / stop() lifecycle works when zeroconf is present.
  - start() is a graceful no-op when zeroconf raises during registration.
  - stop() is safe to call when not started.
  - _get_local_ip() returns a non-empty string.
  - is_active reflects registration state.
"""

from unittest.mock import MagicMock, patch

from murmurate.api.mdns import MdnsAdvertiser, _get_local_ip


# ---------------------------------------------------------------------------
# _get_local_ip
# ---------------------------------------------------------------------------

def test_get_local_ip_returns_string():
    """_get_local_ip() should return a non-empty string."""
    ip = _get_local_ip()
    assert isinstance(ip, str)
    assert len(ip) > 0


def test_get_local_ip_falls_back_on_error():
    """_get_local_ip() should return '127.0.0.1' when socket fails."""
    with patch("murmurate.api.mdns.socket.socket") as mock_sock_cls:
        mock_sock_cls.return_value.__enter__.return_value.connect.side_effect = OSError
        ip = _get_local_ip()
    assert ip == "127.0.0.1"


# ---------------------------------------------------------------------------
# MdnsAdvertiser lifecycle
# ---------------------------------------------------------------------------

def test_advertiser_starts_inactive():
    """A fresh MdnsAdvertiser should not be active."""
    adv = MdnsAdvertiser(port=7683, version="0.3.0")
    assert not adv.is_active


def test_stop_when_not_started_is_noop():
    """stop() on an un-started advertiser should not raise."""
    adv = MdnsAdvertiser()
    adv.stop()  # should not raise
    assert not adv.is_active


def test_start_and_stop_with_mock_zeroconf():
    """start() and stop() should call through to zeroconf when available."""
    mock_zc = MagicMock()
    mock_info = MagicMock()

    with patch("murmurate.api.mdns._ZEROCONF_AVAILABLE", True), \
         patch("murmurate.api.mdns.Zeroconf", return_value=mock_zc), \
         patch("murmurate.api.mdns.ServiceInfo", return_value=mock_info):

        adv = MdnsAdvertiser(port=9999, version="0.3.0")
        adv.start()

        assert adv.is_active
        mock_zc.register_service.assert_called_once_with(mock_info)

        adv.stop()

        assert not adv.is_active
        mock_zc.unregister_service.assert_called_once_with(mock_info)
        mock_zc.close.assert_called_once()


def test_start_graceful_on_zeroconf_error():
    """start() should log a warning and remain inactive when zeroconf raises."""
    with patch("murmurate.api.mdns._ZEROCONF_AVAILABLE", True), \
         patch("murmurate.api.mdns.Zeroconf", side_effect=OSError("mDNS unavailable")), \
         patch("murmurate.api.mdns.ServiceInfo", return_value=MagicMock()):

        adv = MdnsAdvertiser()
        adv.start()  # should not raise
        assert not adv.is_active


def test_start_noop_when_zeroconf_missing():
    """start() should log a warning and remain inactive when zeroconf is not installed."""
    with patch("murmurate.api.mdns._ZEROCONF_AVAILABLE", False):
        adv = MdnsAdvertiser()
        adv.start()  # should not raise
        assert not adv.is_active


def test_stop_graceful_on_zeroconf_error():
    """stop() should not propagate exceptions from zeroconf teardown."""
    mock_zc = MagicMock()
    mock_zc.unregister_service.side_effect = OSError("already gone")
    mock_info = MagicMock()

    with patch("murmurate.api.mdns._ZEROCONF_AVAILABLE", True), \
         patch("murmurate.api.mdns.Zeroconf", return_value=mock_zc), \
         patch("murmurate.api.mdns.ServiceInfo", return_value=mock_info):

        adv = MdnsAdvertiser()
        adv.start()
        adv.stop()  # should not raise despite unregister_service raising
        assert not adv.is_active


def test_double_stop_is_noop():
    """Calling stop() twice should not raise."""
    mock_zc = MagicMock()
    mock_info = MagicMock()

    with patch("murmurate.api.mdns._ZEROCONF_AVAILABLE", True), \
         patch("murmurate.api.mdns.Zeroconf", return_value=mock_zc), \
         patch("murmurate.api.mdns.ServiceInfo", return_value=mock_info):

        adv = MdnsAdvertiser()
        adv.start()
        adv.stop()
        adv.stop()  # second stop — should be noop, not raise
