"""
plugins/base.py — Abstract SitePlugin interface.

Each site-specific plugin (DuckDuckGo, Wikipedia, Reddit, etc.) subclasses
SitePlugin and implements the two core async methods: execute_search and
browse_result. The plugin tells the scheduler what transport it prefers and
what rate limit to apply, keeping that knowledge close to the site logic.

The forward reference to Transport uses `from __future__ import annotations`
so that SitePlugin can reference Transport without a circular import. The
transport package imports from models only; plugins import from both models
and transport — annotations-mode defers the evaluation of that reference.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from murmurate.models import BrowseAction, SearchResult, SessionContext, TransportType

if TYPE_CHECKING:
    from murmurate.transport.base import Transport


class SitePlugin(ABC):
    """
    Abstract base for site-specific browsing plugins.

    Concrete plugins define the domains they handle, their preferred transport,
    and implement the two-phase browsing loop: search then browse. The runner
    calls execute_search to get a list of results, then browse_result for each
    one the persona decides to visit.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short unique identifier for this plugin, e.g. 'duckduckgo'."""
        ...

    @property
    @abstractmethod
    def domains(self) -> list[str]:
        """
        List of hostnames this plugin handles.

        Used by the plugin registry to route sessions to the right plugin.
        Example: ['duckduckgo.com', 'ddg.co']
        """
        ...

    @property
    @abstractmethod
    def preferred_transport(self) -> TransportType:
        """
        Which transport this plugin works best with.

        Plugins that rely on JS rendering must use BROWSER; lightweight
        API-style plugins can use HTTP. EITHER lets the scheduler decide.
        """
        ...

    @property
    @abstractmethod
    def rate_limit_rpm(self) -> int:
        """
        Maximum requests per minute this plugin should send to the target site.

        The rate limiter enforces this at runtime to avoid triggering
        bot-detection or overwhelming small sites.
        """
        ...

    @abstractmethod
    async def execute_search(
        self,
        context: SessionContext,
        transport: Transport,
    ) -> list[SearchResult]:
        """
        Run a search query and return the list of results from the SERP.

        The plugin uses context.queries[context.current_query_index] as the
        search term, issues the request via transport, and parses the page
        into SearchResult objects.
        """
        ...

    @abstractmethod
    async def browse_result(
        self,
        result: SearchResult,
        context: SessionContext,
        transport: Transport,
    ) -> BrowseAction:
        """
        Navigate to a single search result URL and record what was found.

        The plugin uses transport to fetch the page, extracts outbound links
        and content snippets, and returns a BrowseAction capturing the visit.
        """
        ...
