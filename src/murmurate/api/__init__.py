"""
api — REST API server for the Murmurate Control UI.

Embeds an aiohttp web server inside the daemon process, exposing endpoints
for daemon status, persona management, session history, plugin info, and
configuration. The web server starts alongside the scheduler when the daemon
runs with --api enabled.
"""
