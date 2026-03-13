# Murmurate — macOS Installation Guide

## Prerequisites

- macOS 13 (Ventura) or later
- Python 3.12+ (check with `python3 --version`)
- Git

If you don't have Python 3.12+, install it via [Homebrew](https://brew.sh):

```bash
brew install python@3.12
```

---

## Quick Install (Automated)

The install script handles everything — cloning, virtual environment, config directory, personas, and optional launchd daemon setup:

```bash
curl -fsSL https://raw.githubusercontent.com/1507-systems/murmurate/main/scripts/install-macos.sh | bash
```

Or clone first and run locally:

```bash
git clone https://github.com/1507-systems/murmurate.git
cd murmurate
bash scripts/install-macos.sh
```

The script will:
1. Create a virtual environment at `~/.local/share/murmurate/venv/`
2. Install Murmurate and all dependencies
3. Create a shell wrapper at `~/.local/bin/murmurate`
4. Set up the config directory at `~/.config/murmurate/`
5. Generate a default `config.toml`
6. Create 3 starter personas with random topic seeds
7. Optionally install a launchd daemon to run in the background

After install, open a new terminal (or `source ~/.zprofile`) and run:

```bash
murmurate --version
murmurate plugins list
```

---

## Manual Install

### 1. Clone the repo

```bash
git clone https://github.com/1507-systems/murmurate.git
cd murmurate
```

### 2. Create a virtual environment

```bash
python3 -m venv ~/.local/share/murmurate/venv
source ~/.local/share/murmurate/venv/bin/activate
```

### 3. Install the package

```bash
pip install -e .
```

For browser automation support (Playwright):

```bash
pip install -e ".[browser]"
playwright install chromium
```

### 4. Create a shell wrapper

So `murmurate` works from anywhere without activating the venv:

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/murmurate << 'WRAPPER'
#!/bin/bash
exec "$HOME/.local/share/murmurate/venv/bin/murmurate" "$@"
WRAPPER
chmod +x ~/.local/bin/murmurate
```

Add `~/.local/bin` to your PATH if it isn't already. In `~/.zprofile`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 5. Set up the config directory

```bash
mkdir -p ~/.config/murmurate/{personas,plugins,logs}
```

### 6. Create a config file

```bash
cat > ~/.config/murmurate/config.toml << 'TOML'
config_version = 1

[scheduler]
sessions_per_hour = { min = 3, max = 8 }
peak_hours = ["10:00", "20:00"]
quiet_hours_start = "23:30"
quiet_hours_end = "06:30"
burst_probability = 0.15

[transport]
http_ratio = 0.7
browser_pool_size = 2

[rate_limit]
default_per_domain_rpm = 10

[persona]
max_topic_depth = 5
auto_generate_count = 3
TOML
```

### 7. Create at least one persona

```bash
murmurate personas add alice --seeds cooking --seeds travel --seeds photography
```

Or let it generate random ones:

```bash
murmurate personas add wanderer
```

### 8. Verify

```bash
murmurate plugins list
murmurate personas list --config-dir ~/.config/murmurate
murmurate run --sessions 1
```

---

## Running as a Background Daemon

### Option A: launchd (recommended)

Murmurate can install a launchd agent that starts automatically on login:

```bash
murmurate install-daemon
```

This creates `~/Library/LaunchAgents/com.murmurate.daemon.plist`. Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.murmurate.daemon.plist
```

Check it's running:

```bash
murmurate status
```

View logs:

```bash
tail -f ~/.config/murmurate/logs/daemon.log
```

To stop and unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.murmurate.daemon.plist
murmurate uninstall-daemon
```

### Option B: Manual foreground

```bash
murmurate start
```

This runs until you Ctrl+C or send SIGTERM.

---

## Updating

```bash
cd /path/to/murmurate
git pull
source ~/.local/share/murmurate/venv/bin/activate
pip install -e .
```

If the daemon is running, restart it:

```bash
launchctl unload ~/Library/LaunchAgents/com.murmurate.daemon.plist
launchctl load ~/Library/LaunchAgents/com.murmurate.daemon.plist
```

---

## Uninstalling

```bash
# Stop the daemon if running
launchctl unload ~/Library/LaunchAgents/com.murmurate.daemon.plist 2>/dev/null
murmurate uninstall-daemon 2>/dev/null

# Remove the install
rm -rf ~/.local/share/murmurate
rm -f ~/.local/bin/murmurate

# Optionally remove config and data
rm -rf ~/.config/murmurate
```

---

## Troubleshooting

**`murmurate: command not found`**
Make sure `~/.local/bin` is in your PATH. Add to `~/.zprofile`:
```bash
export PATH="$HOME/.local/bin:$PATH"
```
Then restart your terminal.

**`No personas found`**
Create one: `murmurate personas add myname --seeds topic1 --seeds topic2`

**`ModuleNotFoundError: No module named 'murmurate'`**
The venv isn't activated or the wrapper points to the wrong place. Check:
```bash
~/.local/share/murmurate/venv/bin/python -c "import murmurate; print(murmurate.__version__)"
```

**Daemon not starting**
Check the error log: `cat ~/.config/murmurate/logs/daemon-error.log`
