#!/usr/bin/env bash
# install-macos.sh — Automated installer for Murmurate on macOS.
#
# Usage:
#   bash scripts/install-macos.sh
#   — or —
#   curl -fsSL https://raw.githubusercontent.com/1507-systems/murmurate/main/scripts/install-macos.sh | bash
#
# What it does:
#   1. Creates a virtual environment at ~/.local/share/murmurate/venv/
#   2. Installs Murmurate and all dependencies (optionally with browser support)
#   3. Creates a shell wrapper at ~/.local/bin/murmurate
#   4. Ensures ~/.local/bin is in PATH (via ~/.zprofile)
#   5. Sets up the config directory at ~/.config/murmurate/
#   6. Generates a default config.toml
#   7. Creates 3 starter personas with random topic seeds
#   8. Optionally installs a launchd daemon to run in the background
#
# Requirements: macOS 13+, Python 3.12+, Git

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INSTALL_DIR="$HOME/.local/share/murmurate"
VENV_DIR="$INSTALL_DIR/venv"
WRAPPER_DIR="$HOME/.local/bin"
WRAPPER_PATH="$WRAPPER_DIR/murmurate"
CONFIG_DIR="$HOME/.config/murmurate"
REPO_URL="https://github.com/1507-systems/murmurate.git"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { printf '\033[1;34m→\033[0m %s\n' "$1"; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m!\033[0m %s\n' "$1"; }
fail()  { printf '\033[1;31m✗\033[0m %s\n' "$1" >&2; exit 1; }

confirm() {
    # $1 = prompt, returns 0 for yes, 1 for no
    local reply
    printf '%s [y/N] ' "$1"
    read -r reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
info "Checking prerequisites…"

# macOS check
[[ "$(uname -s)" == "Darwin" ]] || fail "This installer is for macOS only."

# Python version check — try python3 first, then python
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        py_version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        py_major="${py_version%%.*}"
        py_minor="${py_version##*.}"
        if (( py_major >= MIN_PYTHON_MAJOR && py_minor >= MIN_PYTHON_MINOR )); then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    fail "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required. Install it with: brew install python@3.12"
fi
ok "Found $PYTHON ($py_version)"

# Git check
command -v git &>/dev/null || fail "Git is required. Install it with: xcode-select --install"
ok "Found git"

# ---------------------------------------------------------------------------
# Clone or locate the repo
# ---------------------------------------------------------------------------
REPO_DIR=""

if [[ -f "pyproject.toml" ]] && grep -q 'name = "murmurate"' pyproject.toml 2>/dev/null; then
    # Running from inside an existing clone
    REPO_DIR="$(pwd)"
    info "Using existing repo at $REPO_DIR"
else
    # Need to clone
    REPO_DIR="$(mktemp -d)/murmurate"
    info "Cloning Murmurate…"
    git clone --depth 1 "$REPO_URL" "$REPO_DIR"
    ok "Cloned to $REPO_DIR"
fi

# ---------------------------------------------------------------------------
# Virtual environment
# ---------------------------------------------------------------------------
info "Creating virtual environment at $VENV_DIR…"
mkdir -p "$INSTALL_DIR"

if [[ -d "$VENV_DIR" ]]; then
    warn "Virtual environment already exists — reinstalling into it"
fi

"$PYTHON" -m venv "$VENV_DIR"
ok "Virtual environment ready"

# Activate for the rest of the script
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Upgrade pip first
info "Upgrading pip…"
pip install --quiet --upgrade pip

# ---------------------------------------------------------------------------
# Install Murmurate
# ---------------------------------------------------------------------------
info "Installing Murmurate…"
pip install --quiet -e "$REPO_DIR"
ok "Murmurate installed"

# Optional browser support
if confirm "Install browser automation support (Playwright)? This downloads ~150 MB of browser binaries"; then
    info "Installing Playwright support…"
    pip install --quiet -e "${REPO_DIR}[browser]"
    "$VENV_DIR/bin/playwright" install chromium
    ok "Browser support installed"
else
    info "Skipping browser support (HTTP-only transport)"
fi

# ---------------------------------------------------------------------------
# Shell wrapper
# ---------------------------------------------------------------------------
info "Creating shell wrapper at $WRAPPER_PATH…"
mkdir -p "$WRAPPER_DIR"
cat > "$WRAPPER_PATH" << 'WRAPPER'
#!/bin/bash
exec "$HOME/.local/share/murmurate/venv/bin/murmurate" "$@"
WRAPPER
chmod +x "$WRAPPER_PATH"
ok "Shell wrapper created"

# ---------------------------------------------------------------------------
# PATH setup
# ---------------------------------------------------------------------------
# Check if ~/.local/bin is already in PATH
if [[ ":$PATH:" != *":$WRAPPER_DIR:"* ]]; then
    PROFILE="$HOME/.zprofile"
    # SC2016: intentional — we want literal $HOME/$PATH in the written profile line,
    # not expanded at install time, so the profile works for any user.
    # shellcheck disable=SC2016
    PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

    if [[ -f "$PROFILE" ]] && grep -qF '.local/bin' "$PROFILE" 2>/dev/null; then
        info "PATH entry already in $PROFILE (not currently active — restart terminal)"
    else
        info "Adding ~/.local/bin to PATH in $PROFILE…"
        {
            echo ""
            echo "# Added by Murmurate installer"
            echo "$PATH_LINE"
        } >> "$PROFILE"
        ok "PATH updated in $PROFILE"
    fi
    # Also export for the rest of this script
    export PATH="$WRAPPER_DIR:$PATH"
fi

# ---------------------------------------------------------------------------
# Config directory
# ---------------------------------------------------------------------------
info "Setting up config directory at $CONFIG_DIR…"
mkdir -p "$CONFIG_DIR"/{personas,plugins,logs}

# Generate default config.toml if one doesn't already exist
if [[ -f "$CONFIG_DIR/config.toml" ]]; then
    warn "config.toml already exists — not overwriting"
else
    cat > "$CONFIG_DIR/config.toml" << 'TOML'
config_version = 1

[scheduler]
sessions_per_hour = { min = 3, max = 8 }
peak_hours = ["10:00", "20:00"]
quiet_hours_start = "23:30"
quiet_hours_end = "06:30"
burst_probability = 0.15

[transport]
browser_ratio = 0.3
browser_pool_size = 2

[rate_limit]
default_per_domain_rpm = 10

[persona]
max_tree_depth = 5
auto_generate_count = 3
TOML
    ok "Default config.toml created"
fi

# ---------------------------------------------------------------------------
# Starter personas
# ---------------------------------------------------------------------------
# Pool of realistic topic seeds to pick from
SEED_POOL=(
    cooking travel photography gardening astronomy
    woodworking cycling chess history architecture
    birdwatching yoga pottery jazz mythology
    camping surfing calligraphy robotics beekeeping
    origami geocaching knitting sailing philosophy
    skateboarding foraging bonsai ceramics linguistics
    mountaineering fermentation aquascaping meteorology
    bookbinding leathercraft mycology paleontology
    permaculture stenography viticulture
)

pick_random_seeds() {
    # Pick N unique random seeds from the pool
    local count=$1
    local picked=()
    local pool=("${SEED_POOL[@]}")

    for ((i = 0; i < count && ${#pool[@]} > 0; i++)); do
        local idx=$((RANDOM % ${#pool[@]}))
        picked+=("${pool[$idx]}")
        # Remove the picked element
        pool=("${pool[@]:0:$idx}" "${pool[@]:$((idx + 1))}")
    done

    printf '%s\n' "${picked[@]}"
}

PERSONA_NAMES=("wanderer" "nightowl" "bookworm")

info "Creating 3 starter personas…"
for name in "${PERSONA_NAMES[@]}"; do
    persona_file="$CONFIG_DIR/personas/${name}.json"
    if [[ -f "$persona_file" ]]; then
        warn "Persona '$name' already exists — skipping"
        continue
    fi

    # Pick 3 random seeds for this persona
    mapfile -t seeds < <(pick_random_seeds 3)
    seed_args=()
    for s in "${seeds[@]}"; do
        seed_args+=(--seeds "$s")
    done

    if "$VENV_DIR/bin/murmurate" personas add "$name" "${seed_args[@]}" \
            --config-dir "$CONFIG_DIR" 2>/dev/null; then
        ok "Created persona '$name' with seeds: ${seeds[*]}"
    else
        warn "Could not create persona '$name' (non-fatal)"
    fi
done

# ---------------------------------------------------------------------------
# Optional launchd daemon
# ---------------------------------------------------------------------------
echo ""
if confirm "Install launchd daemon to run Murmurate in the background on login?"; then
    info "Installing launchd daemon…"
    if "$VENV_DIR/bin/murmurate" install-daemon --config-dir "$CONFIG_DIR" 2>/dev/null; then
        ok "Daemon plist installed"
    else
        warn "Could not install daemon (non-fatal — you can run 'murmurate install-daemon' later)"
    fi

    PLIST_PATH="$HOME/Library/LaunchAgents/com.murmurate.daemon.plist"
    if [[ -f "$PLIST_PATH" ]]; then
        if confirm "Load the daemon now (starts generating activity immediately)?"; then
            launchctl load "$PLIST_PATH"
            ok "Daemon loaded and running"
        else
            info "Daemon installed but not loaded. Load it later with:"
            echo "  launchctl load ~/Library/LaunchAgents/com.murmurate.daemon.plist"
        fi
    fi
else
    info "Skipping daemon installation. Run manually with: murmurate start"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ok "Murmurate installed successfully!"
echo ""
echo "  Config:   $CONFIG_DIR/"
echo "  Venv:     $VENV_DIR/"
echo "  Wrapper:  $WRAPPER_PATH"
echo ""
echo "  Open a new terminal (or run 'source ~/.zprofile'), then:"
echo ""
echo "    murmurate --version        # verify installation"
echo "    murmurate plugins list     # see available plugins"
echo "    murmurate personas list    # see your personas"
echo "    murmurate run --sessions 1 # run a single test session"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
