# conftest.py — pytest configuration and shared fixtures
# Populated in later tasks as fixtures are needed (DB setup, async client, etc.)

import inspect
from types import SimpleNamespace

import aioresponses.core as _aioresponses_core
from aiohttp import ClientResponse

# aiohttp 3.14 made `stream_writer` a required keyword argument of
# ClientResponse.__init__, but aioresponses (<=0.7.9) still builds mocked
# responses without it. Give mocked responses a stub writer so they construct.
# Remove once aioresponses passes stream_writer itself.
if "stream_writer" in inspect.signature(ClientResponse.__init__).parameters:

    class _CompatClientResponse(ClientResponse):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("stream_writer", SimpleNamespace(output_size=0))
            super().__init__(*args, **kwargs)

    _aioresponses_core.ClientResponse = _CompatClientResponse
