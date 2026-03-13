"""Generate and install daemon service files."""

import shutil
import sys
from pathlib import Path

def generate_launchd_plist(config_dir: Path, label: str = "com.murmurate.daemon") -> str:
    """Generate a macOS launchd plist XML for running murmurate as a daemon."""
    python_path = sys.executable
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>-m</string>
        <string>murmurate</string>
        <string>run</string>
        <string>--config-dir</string>
        <string>{config_dir}</string>
        <string>--log-format</string>
        <string>json</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{config_dir}/logs/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>{config_dir}/logs/daemon-error.log</string>
</dict>
</plist>"""

def install_launchd(config_dir: Path, label: str = "com.murmurate.daemon") -> Path:
    """Install launchd plist to ~/Library/LaunchAgents/."""
    plist_content = generate_launchd_plist(config_dir, label)
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content)
    return plist_path

def uninstall_launchd(label: str = "com.murmurate.daemon") -> bool:
    """Remove launchd plist. Returns True if file existed."""
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if plist_path.exists():
        plist_path.unlink()
        return True
    return False

def generate_systemd_unit(config_dir: Path) -> str:
    """Generate a systemd user unit file."""
    python_path = sys.executable
    return f"""[Unit]
Description=Murmurate - Decoy Internet Activity Generator
After=network.target

[Service]
Type=simple
ExecStart={python_path} -m murmurate run --config-dir {config_dir} --log-format json
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
"""
