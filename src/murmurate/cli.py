"""
cli.py — Murmurate CLI, implemented with Click.

Entry points:
  murmurate run              — run browsing sessions in the foreground
  murmurate start            — start daemon (foreground, for launchd/systemd)
  murmurate status           — check whether the background daemon is running
  murmurate stop             — send stop signal to the daemon
  murmurate install-daemon   — install as a system daemon
  murmurate uninstall-daemon — remove installed daemon service
  murmurate personas         — create and inspect personas
  murmurate plugins          — inspect available plugins
  murmurate history          — view recent session history
  murmurate stats            — view activity statistics

The `run` command is the main operational path: it wires up all subsystems
(config, database, personas, plugins, transports, scheduler) and drives them
until the requested number of sessions completes or the user interrupts.

The `start` command is similar but runs indefinitely (no --sessions limit),
writes a PID file, and is intended for use with launchd or systemd.

All other commands are read-only introspection helpers that never require the
full async stack to be running.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="murmurate")
def cli():
    """Murmurate — realistic decoy internet activity generator."""
    pass


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--sessions", "-n",
    type=int, default=None,
    help="Number of sessions to run (default: unlimited)",
)
@click.option(
    "--config-dir",
    type=click.Path(exists=False), default=None,
    help="Config directory path",
)
@click.option(
    "--log-format",
    type=click.Choice(["json", "text"]), default="text",
    help="Log output format",
)
def run(sessions, config_dir, log_format):
    """Run browsing sessions (foreground)."""
    from murmurate.config import load_config, resolve_config_dir
    from murmurate.log import setup_logging

    # Resolve config directory using the three-tier priority chain (CLI → env → default)
    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)
    config = load_config(config_path)
    setup_logging(log_file=None, level="INFO", json_format=(log_format == "json"))

    asyncio.run(_run_sessions(config, config_path, sessions))


# ---------------------------------------------------------------------------
# start command (daemon foreground mode for launchd/systemd)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--config-dir", type=click.Path(exists=False), default=None)
@click.option("--log-format", type=click.Choice(["json", "text"]), default="json")
@click.option("--api/--no-api", default=False, help="Enable the REST API server")
@click.option("--api-port", type=int, default=7683, help="API server port")
@click.option("--api-host", default="127.0.0.1", help="API server bind address")
@click.option("--api-token", default=None, help="Bearer token for API auth")
def start(config_dir, log_format, api, api_port, api_host, api_token):
    """Start the daemon (foreground, for use with launchd/systemd)."""
    from murmurate.config import load_config, resolve_config_dir
    from murmurate.log import setup_logging
    from murmurate.daemon.lifecycle import check_already_running, write_pid, cleanup_pid

    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)
    pid_file = config_path / "murmurate.pid"

    if check_already_running(pid_file):
        click.echo("Daemon already running. Use 'murmurate stop' first.")
        sys.exit(1)

    config = load_config(config_path)
    setup_logging(log_file=None, level="INFO", json_format=(log_format == "json"))

    write_pid(pid_file)
    try:
        if api:
            asyncio.run(_run_with_api(config, config_path, api_host, api_port, api_token))
        else:
            asyncio.run(_run_sessions(config, config_path, None))
    finally:
        cleanup_pid(pid_file)


async def _run_with_api(config, config_dir: Path, host: str, port: int, token: str | None) -> None:
    """Start the API server alongside the daemon scheduler.

    Both the scheduler and the API server share the same event loop. The API
    server gets references to the live scheduler, database, and plugin registry
    so it can serve real-time data without IPC.
    """
    from aiohttp import web
    from murmurate.api.server import ApiState, create_app
    from murmurate.database import StateDB
    from murmurate.persona.engine import PersonaEngine
    from murmurate.persona.storage import load_all_personas
    from murmurate.plugins.registry import PluginRegistry
    from murmurate.scheduler.timing import TimingModel
    from murmurate.scheduler.rate_limiter import RateLimiter
    from murmurate.scheduler.scheduler import Scheduler
    from murmurate.transport.http import HttpTransport

    db = StateDB(config_dir / "state.db")
    await db.initialize()

    personas = load_all_personas(config_dir / "personas")

    registry = PluginRegistry()
    registry.load_bundled()
    registry.load_user_plugins(config_dir / "plugins")

    http = HttpTransport(config=config)
    await http.start()

    timing = TimingModel(config.scheduler)
    rate_limiter = RateLimiter(db)
    engine = PersonaEngine()

    scheduler = Scheduler(
        config=config,
        personas=personas,
        registry=registry,
        http_transport=http,
        browser_transport=None,
        db=db,
        timing=timing,
        rate_limiter=rate_limiter,
        persona_engine=engine,
    )

    # Build the API server with shared state
    api_state = ApiState(
        config=config,
        config_dir=config_dir,
        db=db,
        registry=registry,
        scheduler=scheduler,
        api_token=token,
    )
    app = create_app(api_state)

    # Start the API server as a background task
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    import logging
    logging.getLogger(__name__).info("API server listening on http://%s:%d", host, port)

    try:
        if personas:
            results = await scheduler.run(max_sessions=None)
            click.echo(f"Completed {len(results)} sessions.")
        else:
            click.echo("No personas found. API server running — create personas via the UI.")
            # Keep running so the API server stays alive
            while True:
                await asyncio.sleep(60)
    finally:
        await runner.cleanup()
        await http.stop()
        await db.close()


async def _run_sessions(config, config_dir: Path, max_sessions: int | None) -> None:
    """Wire up all subsystems and drive the scheduler until completion.

    This function is intentionally separated from the Click command so it can
    be called from tests or other async contexts without invoking Click's runner.
    """
    from murmurate.database import StateDB
    from murmurate.persona.engine import PersonaEngine
    from murmurate.persona.storage import load_all_personas
    from murmurate.plugins.registry import PluginRegistry
    from murmurate.scheduler.timing import TimingModel
    from murmurate.scheduler.rate_limiter import RateLimiter
    from murmurate.scheduler.scheduler import Scheduler
    from murmurate.transport.http import HttpTransport

    db = StateDB(config_dir / "state.db")
    await db.initialize()

    personas = load_all_personas(config_dir / "personas")
    if not personas:
        click.echo("No personas found. Use 'murmurate personas add' to create one.")
        return

    registry = PluginRegistry()
    registry.load_bundled()
    registry.load_user_plugins(config_dir / "plugins")

    http = HttpTransport(config=config)
    await http.start()

    timing = TimingModel(config.scheduler)
    rate_limiter = RateLimiter(db)
    engine = PersonaEngine()

    scheduler = Scheduler(
        config=config,
        personas=personas,
        registry=registry,
        http_transport=http,
        browser_transport=None,
        db=db,
        timing=timing,
        rate_limiter=rate_limiter,
        persona_engine=engine,
    )

    try:
        results = await scheduler.run(max_sessions=max_sessions)
        click.echo(f"Completed {len(results)} sessions.")
    finally:
        await http.stop()
        await db.close()


# ---------------------------------------------------------------------------
# api command (standalone API server without scheduler)
# ---------------------------------------------------------------------------

@cli.command("api")
@click.option("--config-dir", type=click.Path(exists=False), default=None)
@click.option("--port", type=int, default=7683, help="API server port")
@click.option("--host", default="127.0.0.1", help="API server bind address")
@click.option("--api-token", default=None, help="Bearer token for API auth")
def api_server(config_dir, port, host, api_token):
    """Run the Control UI API server (without the scheduler)."""
    from murmurate.config import load_config, resolve_config_dir

    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)
    config = load_config(config_path)
    asyncio.run(_run_api_only(config, config_path, host, port, api_token))


async def _run_api_only(config, config_dir: Path, host: str, port: int, token: str | None) -> None:
    """Run just the API server — no scheduler, no session execution.

    Useful for managing personas, viewing history, and editing config
    when you don't want to actually generate traffic.
    """
    from aiohttp import web
    from murmurate.api.server import ApiState, create_app
    from murmurate.database import StateDB
    from murmurate.plugins.registry import PluginRegistry

    db = StateDB(config_dir / "state.db")
    await db.initialize()

    registry = PluginRegistry()
    registry.load_bundled()
    registry.load_user_plugins(config_dir / "plugins")

    api_state = ApiState(
        config=config,
        config_dir=config_dir,
        db=db,
        registry=registry,
        scheduler=None,
        api_token=token,
    )
    app = create_app(api_state)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    click.echo(f"Murmurate Control UI API running on http://{host}:{port}")
    click.echo("Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
        await db.close()


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--config-dir",
    type=click.Path(exists=False), default=None,
)
def status(config_dir):
    """Show daemon status and recent activity."""
    from murmurate.config import resolve_config_dir

    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)
    pid_file = config_path / "murmurate.pid"

    if pid_file.exists():
        pid = pid_file.read_text().strip()
        click.echo(f"Daemon running (PID: {pid})")
    else:
        click.echo("Daemon not running")


# ---------------------------------------------------------------------------
# stop command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--config-dir",
    type=click.Path(exists=False), default=None,
)
def stop(config_dir):
    """Stop the running daemon."""
    from murmurate.config import resolve_config_dir
    from murmurate.daemon.lifecycle import stop_daemon

    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)
    pid_file = config_path / "murmurate.pid"

    if stop_daemon(pid_file):
        click.echo("Stop signal sent.")
    else:
        click.echo("Daemon not running.")


# ---------------------------------------------------------------------------
# personas subgroup
# ---------------------------------------------------------------------------

@cli.group()
def personas():
    """Manage personas."""
    pass


@personas.command("list")
@click.option(
    "--config-dir",
    type=click.Path(exists=False), default=None,
)
def personas_list(config_dir):
    """List all personas."""
    from murmurate.config import resolve_config_dir
    from murmurate.persona.storage import load_all_personas

    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)
    persona_dir = config_path / "personas"
    personas_data = load_all_personas(persona_dir)

    if not personas_data:
        click.echo("No personas found.")
        return

    for p in personas_data:
        # Show a preview of the first three seeds so the list stays readable
        seeds = ", ".join(p.seeds[:3])
        click.echo(f"  {p.name} — seeds: {seeds} — sessions: {p.total_sessions}")


@personas.command("add")
@click.argument("name")
@click.option(
    "--seeds", "-s",
    multiple=True,
    help="Topic seeds (may be specified multiple times)",
)
@click.option(
    "--config-dir",
    type=click.Path(exists=False), default=None,
)
def personas_add(name, seeds, config_dir):
    """Create a new persona."""
    from datetime import datetime, timezone

    from murmurate.config import resolve_config_dir
    from murmurate.models import PersonaState, TopicNode
    from murmurate.persona.fingerprint import generate_fingerprint
    from murmurate.persona.storage import save_persona
    from murmurate.persona.topics import get_random_seeds

    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)

    # Fall back to randomly sampled seeds if none were provided
    if not seeds:
        seeds = get_random_seeds(3)
    else:
        seeds = list(seeds)

    fp = generate_fingerprint()
    now = datetime.now(timezone.utc).isoformat()

    # Each seed becomes a root node in the topic tree (depth=0)
    tree = [
        TopicNode(topic=s, depth=0, children=[], query_count=0, last_used=None)
        for s in seeds
    ]

    persona = PersonaState(
        name=name,
        version=1,
        seeds=seeds,
        topic_tree=tree,
        fingerprint=fp,
        created_at=now,
    )

    persona_dir = config_path / "personas"
    persona_dir.mkdir(parents=True, exist_ok=True)
    save_persona(persona, persona_dir)
    click.echo(f"Created persona '{name}' with seeds: {', '.join(seeds)}")


# ---------------------------------------------------------------------------
# plugins subgroup
# ---------------------------------------------------------------------------

@cli.group()
def plugins():
    """Manage plugins."""
    pass


@plugins.command("list")
def plugins_list():
    """List available plugins."""
    from murmurate.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.load_bundled()

    for name, plugin in registry.all_plugins.items():
        click.echo(
            f"  {name} — {plugin.preferred_transport.value} — {plugin.rate_limit_rpm} RPM"
        )


@plugins.command("info")
@click.argument("name")
def plugins_info(name):
    """Show plugin details."""
    from murmurate.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.load_bundled()

    info = registry.get_plugin_info(name)
    if not info:
        click.echo(f"Plugin '{name}' not found.")
        return

    for k, v in info.items():
        click.echo(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# history command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--last", "-n",
    type=int, default=10,
    help="Number of recent sessions to show",
)
@click.option(
    "--config-dir",
    type=click.Path(exists=False), default=None,
)
def history(last, config_dir):
    """Show recent session history."""
    from murmurate.config import resolve_config_dir
    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)
    db_path = config_path / "state.db"

    if not db_path.exists():
        click.echo("No session history found.")
        return

    asyncio.run(_show_history(db_path, last))


async def _show_history(db_path, limit):
    """Load and display recent sessions from the state database."""
    from murmurate.database import StateDB
    db = StateDB(db_path)
    await db.initialize()
    try:
        sessions = await db.get_session_history(limit)
        if not sessions:
            click.echo("No sessions found.")
            return
        for s in sessions:
            status = s.get("status", "unknown")
            plugin = s.get("plugin_name", "?")
            persona = s.get("persona_name", "?")
            started = s.get("started_at", "?")[:19]
            click.echo(f"  [{status}] {persona} → {plugin} at {started}")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--days", "-d",
    type=int, default=7,
    help="Number of days to analyze",
)
@click.option(
    "--config-dir",
    type=click.Path(exists=False), default=None,
)
def stats(days, config_dir):
    """Show activity statistics."""
    from murmurate.config import resolve_config_dir
    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)
    db_path = config_path / "state.db"

    if not db_path.exists():
        click.echo("No session data found.")
        return

    asyncio.run(_show_stats(db_path, days))


async def _show_stats(db_path, days):
    """Compute and display activity statistics from the state database."""
    from murmurate.database import StateDB
    db = StateDB(db_path)
    await db.initialize()
    try:
        sessions = await db.get_session_history(limit=10000)
        if not sessions:
            click.echo("No sessions found.")
            return

        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        recent = [s for s in sessions if s.get("started_at", "") >= cutoff]

        total = len(recent)
        completed = sum(1 for s in recent if s.get("status") == "completed")
        failed = sum(1 for s in recent if s.get("status") == "failed")

        # Plugin distribution
        plugins = {}
        for s in recent:
            p = s.get("plugin_name", "unknown")
            plugins[p] = plugins.get(p, 0) + 1

        click.echo(f"Statistics for last {days} days:")
        click.echo(f"  Total sessions: {total} ({completed} completed, {failed} failed)")
        if plugins:
            click.echo("  Plugin distribution:")
            for name, count in sorted(plugins.items(), key=lambda x: -x[1]):
                pct = count / total * 100 if total > 0 else 0
                click.echo(f"    {name}: {count} ({pct:.0f}%)")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# install-daemon / uninstall-daemon commands
# ---------------------------------------------------------------------------

@cli.command("install-daemon")
@click.option("--config-dir", type=click.Path(exists=False), default=None)
@click.option("--systemd", is_flag=True, help="Generate systemd unit instead of launchd plist")
def install_daemon(config_dir, systemd):
    """Install as a system daemon (launchd on macOS, systemd on Linux)."""
    from murmurate.config import resolve_config_dir
    from murmurate.daemon.install import install_launchd, generate_systemd_unit

    config_path = resolve_config_dir(Path(config_dir) if config_dir else None)

    if systemd:
        unit = generate_systemd_unit(config_path)
        unit_path = Path.home() / ".config" / "systemd" / "user" / "murmurate.service"
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(unit)
        click.echo(f"Systemd unit installed: {unit_path}")
        click.echo("Run: systemctl --user enable --now murmurate")
    else:
        plist_path = install_launchd(config_path)
        click.echo(f"LaunchAgent installed: {plist_path}")
        click.echo("Run: launchctl load " + str(plist_path))


@cli.command("uninstall-daemon")
@click.option("--systemd", is_flag=True, help="Remove systemd unit instead of launchd plist")
def uninstall_daemon(systemd):
    """Remove the installed daemon service."""
    if systemd:
        unit_path = Path.home() / ".config" / "systemd" / "user" / "murmurate.service"
        if unit_path.exists():
            unit_path.unlink()
            click.echo(f"Systemd unit removed: {unit_path}")
        else:
            click.echo("No systemd unit found.")
    else:
        from murmurate.daemon.install import uninstall_launchd
        if uninstall_launchd():
            click.echo("LaunchAgent removed.")
        else:
            click.echo("No LaunchAgent found.")
