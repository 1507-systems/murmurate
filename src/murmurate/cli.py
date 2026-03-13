"""
cli.py — Murmurate CLI, implemented with Click.

Entry points:
  murmurate run          — run browsing sessions in the foreground
  murmurate status       — check whether the background daemon is running
  murmurate stop         — send stop signal to the daemon
  murmurate personas     — create and inspect personas
  murmurate plugins      — inspect available plugins
  murmurate history      — view recent session history
  murmurate stats        — view activity statistics

The `run` command is the main operational path: it wires up all subsystems
(config, database, personas, plugins, transports, scheduler) and drives them
until the requested number of sessions completes or the user interrupts.

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
    # Daemon lifecycle is implemented in Task 19; this is a placeholder that
    # confirms the command is wired up and communicates intent to the user.
    click.echo("Sending stop signal...")


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
    # Full implementation requires database queries; placeholder for Task 18.
    # The database query layer is built out in Task 17 and will be wired here.
    click.echo(f"Last {last} sessions:")


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
    # Full implementation requires database aggregation; placeholder for Task 18.
    click.echo(f"Statistics for last {days} days:")
