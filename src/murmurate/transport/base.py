"""
transport/base.py — Abstract Transport interface.

All concrete transport implementations (HTTP via aiohttp, Browser via Playwright)
must subclass Transport and implement execute_session. The Transport abstraction
lets plugins and the scheduler remain agnostic to how requests are actually made.
"""

from abc import ABC, abstractmethod

from murmurate.models import BrowsingSession, SessionResult


class Transport(ABC):
    """
    Abstract base class for all transport implementations.

    A transport is responsible for taking a BrowsingSession (which describes
    what to do, for which persona, using which plugin) and carrying it out —
    making HTTP requests or driving a real browser — returning a SessionResult.
    """

    @abstractmethod
    async def execute_session(self, session: BrowsingSession) -> SessionResult:
        """Execute a full browsing session and return results."""
        ...
