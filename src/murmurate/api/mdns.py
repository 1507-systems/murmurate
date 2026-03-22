"""
mdns.py — mDNS/Bonjour service advertisement for LAN discovery.

Advertises the Murmurate API server as an HTTP service on the local network
so the control UI (and other tools) can discover it without manual IP entry.

Service type: _murmurate._tcp.local.
Instance name: Murmurate on <hostname>
Port: the configured API port (default 7683)

The service record includes TXT metadata:
  - version: murmurate version string
  - api_path: /api  (where the REST API lives)
  - ui_path: /       (where the web UI lives)

Discovery from a browser extension or companion app:
  - Browse for _murmurate._tcp.local. in DNS-SD
  - Each result gives you hostname + port + /api prefix

Uses the `zeroconf` library (pure-Python mDNS/DNS-SD). It is already
present on this machine as a transitive dependency of esphome, but it is
listed as an optional dependency so users without it can still run without
LAN discovery — they just configure the URL manually.
"""

from __future__ import annotations

import logging
import socket
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# zeroconf is optional. If it is not installed we log a warning and the
# mDNS functions become no-ops so the rest of the daemon is unaffected.
try:
    from zeroconf import ServiceInfo, Zeroconf
    _ZEROCONF_AVAILABLE = True
except ImportError:
    _ZEROCONF_AVAILABLE = False
    Zeroconf = None  # type: ignore[assignment,misc]
    ServiceInfo = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from zeroconf import ServiceInfo as ServiceInfoT, Zeroconf as ZeroconfT


def _get_local_ip() -> str:
    """Return the primary LAN IPv4 address for this machine.

    Opens a UDP socket to 8.8.8.8 (no packet sent) to find which interface
    the OS would use to reach the internet. Falls back to 127.0.0.1.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class MdnsAdvertiser:
    """Manages the lifecycle of the mDNS service record.

    Usage::

        advertiser = MdnsAdvertiser(port=7683, version="0.3.0")
        advertiser.start()   # call once at daemon startup
        ...
        advertiser.stop()    # call once at daemon shutdown

    The advertiser is a no-op (with a logged warning) if the zeroconf
    library is not installed.
    """

    SERVICE_TYPE = "_murmurate._tcp.local."

    def __init__(self, port: int = 7683, version: str = "0.3.0") -> None:
        self.port = port
        self.version = version
        self._zeroconf: "ZeroconfT | None" = None
        self._service_info: "ServiceInfoT | None" = None

    def start(self) -> None:
        """Register the mDNS service record on the local network."""
        if not _ZEROCONF_AVAILABLE:
            logger.warning(
                "zeroconf library not installed — LAN mDNS discovery disabled. "
                "Install with: pip install zeroconf"
            )
            return

        hostname = socket.gethostname()
        local_ip = _get_local_ip()

        # Service instance name: "Murmurate on myhostname._murmurate._tcp.local."
        service_name = f"Murmurate on {hostname}.{self.SERVICE_TYPE}"

        self._service_info = ServiceInfo(
            type_=self.SERVICE_TYPE,
            name=service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=self.port,
            properties={
                "version": self.version,
                "api_path": "/api",
                "ui_path": "/",
                "hostname": hostname,
            },
            server=f"{hostname}.local.",
        )

        try:
            self._zeroconf = Zeroconf()
            self._zeroconf.register_service(self._service_info)
            logger.info(
                "mDNS: advertising Murmurate at %s:%d (LAN discovery enabled)",
                local_ip,
                self.port,
            )
        except Exception as exc:
            logger.warning("mDNS registration failed: %s", exc)
            self._zeroconf = None
            self._service_info = None

    def stop(self) -> None:
        """Unregister the mDNS service record and close the Zeroconf instance."""
        if self._zeroconf is None:
            return
        try:
            if self._service_info:
                self._zeroconf.unregister_service(self._service_info)
            self._zeroconf.close()
            logger.info("mDNS: service record withdrawn")
        except Exception as exc:
            logger.warning("mDNS shutdown error: %s", exc)
        finally:
            self._zeroconf = None
            self._service_info = None

    @property
    def is_active(self) -> bool:
        """Return True if the mDNS record is currently registered."""
        return self._zeroconf is not None
