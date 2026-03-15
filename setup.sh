#!/bin/bash
# ============================================================
# BinanceML Pro – Setup Script
# Usage:
#   ./setup.sh              – First-time install
#   ./setup.sh -update      – Upgrade all dependencies
#   ./setup.sh -full-reset  – Wipe everything and reinstall
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS="$SCRIPT_DIR/trading_bot/requirements.txt"

# ── Colours ─────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YEL='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
NC='\033[0m'   # no colour

ok()   { echo -e "${GRN}  ✔  $*${NC}"; }
info() { echo -e "${BLU}  ▶  $*${NC}"; }
warn() { echo -e "${YEL}  ⚠  $*${NC}"; }
err()  { echo -e "${RED}  ✘  $*${NC}"; }
sep()  { echo -e "${CYN}────────────────────────────────────────────────────${NC}"; }

# ── Argument handling ────────────────────────────────────────
MODE="install"
case "${1:-}" in
    -update)      MODE="update" ;;
    -full-reset)  MODE="reset"  ;;
    "")           MODE="install" ;;
    *)
        err "Unknown flag: $1"
        echo "  Usage: $0 [no flag | -update | -full-reset]"
        exit 1
        ;;
esac

# ============================================================
# FULL RESET
# ============================================================
if [ "$MODE" = "reset" ]; then
    echo ""
    echo -e "${RED}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║       BinanceML Pro – Full Reset                 ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    warn "This will delete the virtual environment and ~/.binanceml config."
    read -rp "  Are you sure? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

    sep
    info "Removing virtual environment: $VENV_DIR"
    if [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR"
        ok "Virtual environment removed."
    else
        warn "No virtual environment found – skipping."
    fi

    info "Removing config directory: ~/.binanceml"
    if [ -d "$HOME/.binanceml" ]; then
        rm -rf "$HOME/.binanceml"
        ok "Config directory removed."
    else
        warn "No config directory found – skipping."
    fi

    sep
    info "Starting fresh install…"
    echo ""
    MODE="install"   # fall through to install
fi

# ============================================================
# HEADER
# ============================================================
echo ""
if [ "$MODE" = "update" ]; then
    echo -e "${CYN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${CYN}║       BinanceML Pro – Update                     ║${NC}"
    echo -e "${CYN}╚══════════════════════════════════════════════════╝${NC}"
else
    echo -e "${CYN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${CYN}║       BinanceML Pro – Environment Setup          ║${NC}"
    echo -e "${CYN}╚══════════════════════════════════════════════════╝${NC}"
fi
echo ""

# ── Platform info ────────────────────────────────────────────
ARCH=$(uname -m)
OS=$(uname -s)
info "Platform: $OS $ARCH"

# ============================================================
# SYSTEM DEPENDENCIES  (Ubuntu/Debian only)
# ============================================================
if [ "$OS" = "Linux" ] && command -v apt-get &>/dev/null; then
    sep
    info "Installing system dependencies for PyQt6 (Ubuntu/Debian)…"
    PKGS=(libegl1 libgl1 libglib2.0-0 libdbus-1-3 libxcb-cursor0 python3.12-venv)
    for pkg in "${PKGS[@]}"; do
        echo -n "    Installing $pkg … "
        if sudo apt-get install -y --no-install-recommends "$pkg" > /tmp/apt_$pkg.log 2>&1; then
            ok "done"
        else
            err "FAILED (see /tmp/apt_$pkg.log)"
            cat /tmp/apt_$pkg.log
        fi
    done
fi

# ============================================================
# PYTHON CHECK
# ============================================================
sep
info "Checking Python…"
PYTHON=$(which python3.12 2>/dev/null || which python3 2>/dev/null || true)
if [ -z "$PYTHON" ]; then
    err "Python 3.12 not found."
    echo "    macOS:  brew install python@3.12"
    echo "    Ubuntu: sudo apt-get install python3.12 python3.12-venv"
    exit 1
fi
PY_VER=$($PYTHON --version 2>&1)
ok "Found: $PY_VER at $PYTHON"

# ============================================================
# VIRTUAL ENVIRONMENT
# ============================================================
sep
if [ "$MODE" = "update" ]; then
    if [ ! -d "$VENV_DIR" ]; then
        warn "No virtual environment found – creating one first."
        info "Creating virtual environment at $VENV_DIR …"
        $PYTHON -m venv "$VENV_DIR"
        ok "Virtual environment created."
    else
        ok "Virtual environment exists: $VENV_DIR"
    fi
else
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating virtual environment at $VENV_DIR …"
        if $PYTHON -m venv "$VENV_DIR" 2>&1; then
            ok "Virtual environment created."
        else
            err "Failed to create virtual environment."
            exit 1
        fi
    else
        ok "Virtual environment already exists – reusing."
    fi
fi

info "Activating virtual environment…"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
ok "Activated: $(which python) ($(python --version))"

# ============================================================
# PIP / SETUPTOOLS
# ============================================================
sep
info "Upgrading pip, setuptools and wheel…"
if pip install --upgrade pip setuptools wheel 2>&1 | tee /tmp/binanceml_pip_bootstrap.log | grep -E '(Successfully|already|ERROR|error|warning)' --color=never; then
    ok "pip/setuptools/wheel up to date."
else
    warn "pip upgrade produced unexpected output – check /tmp/binanceml_pip_bootstrap.log"
fi

# ============================================================
# PYTHON DEPENDENCIES
# ============================================================
sep
if [ "$MODE" = "update" ]; then
    info "Upgrading Python dependencies from $REQUIREMENTS …"
    PIP_UPGRADE_FLAG="--upgrade"
else
    info "Installing Python dependencies from $REQUIREMENTS …"
    PIP_UPGRADE_FLAG=""
fi
echo ""

# Run pip and stream output; capture exit code separately
set +e
pip install --pre $PIP_UPGRADE_FLAG \
    -r "$REQUIREMENTS" \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    2>&1 | tee /tmp/binanceml_pip_install.log
PIP_EXIT=${PIPESTATUS[0]}
set -e

echo ""
if [ "$PIP_EXIT" -eq 0 ]; then
    ok "All Python dependencies installed successfully."
else
    err "pip exited with code $PIP_EXIT – see full log: /tmp/binanceml_pip_install.log"
    echo ""
    echo "  Common failures:"
    echo "    • ta-lib          → sudo apt-get install libta-lib-dev  (or brew install ta-lib)"
    echo "    • psycopg2-binary → sudo apt-get install libpq-dev"
    echo "    • torch           → check https://pytorch.org for platform-specific wheels"
    echo ""
    echo "  Errors from log:"
    grep -i "error\|failed\|no matching" /tmp/binanceml_pip_install.log | head -20 || true
    echo ""
    exit 1
fi

# ── Strip the 'platform' meta-package if pip pulled it in ──
#    (platform-info 0.1.0 has no usable wheel and is not needed)
sep
info "Checking for unwanted transitive package: platform-info…"
if pip show platform-info &>/dev/null 2>&1; then
    warn "platform-info is installed – removing it (not required, breaks on some systems)."
    pip uninstall -y platform-info 2>&1
    ok "platform-info removed."
else
    ok "platform-info not present – nothing to remove."
fi

# ============================================================
# POSTGRESQL
# ============================================================
sep
info "Checking PostgreSQL…"
if command -v psql &>/dev/null; then
    ok "Found: $(psql --version)"
    echo -n "    Creating database 'binanceml'… "
    createdb binanceml 2>/dev/null && ok "created." || warn "already exists."
    echo -n "    Creating user 'binanceml'… "
    createuser binanceml 2>/dev/null && ok "created." || warn "already exists."
    echo -n "    Setting password and privileges… "
    psql -c "ALTER USER binanceml WITH PASSWORD 'binanceml';" 2>/dev/null && \
    psql -c "GRANT ALL PRIVILEGES ON DATABASE binanceml TO binanceml;" 2>/dev/null && \
        ok "done." || warn "could not apply (may need superuser)."
else
    warn "PostgreSQL not found."
    echo "    macOS:  brew install postgresql@16 && brew services start postgresql@16"
    echo "    Ubuntu: sudo apt-get install postgresql postgresql-contrib"
fi

# ============================================================
# REDIS
# ============================================================
sep
info "Checking Redis…"
if command -v redis-cli &>/dev/null; then
    ok "Found: $(redis-cli --version)"
    if redis-cli ping 2>/dev/null | grep -q PONG; then
        ok "Redis is running."
    else
        warn "Redis is installed but not running."
        echo "    macOS:  brew services start redis"
        echo "    Ubuntu: sudo systemctl start redis-server"
    fi
else
    warn "Redis not found."
    echo "    macOS:  brew install redis && brew services start redis"
    echo "    Ubuntu: sudo apt-get install redis-server"
fi

# ============================================================
# CONFIG DIRECTORIES
# ============================================================
sep
info "Creating config directories in ~/.binanceml …"
mkdir -p "$HOME/.binanceml"/{models,reports,logs}
ok "~/.binanceml/{models,reports,logs} ready."

# ============================================================
# DONE
# ============================================================
sep
echo ""
if [ "$MODE" = "update" ]; then
    echo -e "${GRN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GRN}║  Update complete!                                ║${NC}"
    echo -e "${GRN}╚══════════════════════════════════════════════════╝${NC}"
else
    echo -e "${GRN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GRN}║  Setup complete!  Run the app with:              ║${NC}"
    echo -e "${GRN}║                                                  ║${NC}"
    echo -e "${GRN}║    source .venv/bin/activate                     ║${NC}"
    echo -e "${GRN}║    python trading_bot/main.py                    ║${NC}"
    echo -e "${GRN}║                                                  ║${NC}"
    echo -e "${GRN}║  Other commands:                                 ║${NC}"
    echo -e "${GRN}║    ./setup.sh -update      – upgrade deps        ║${NC}"
    echo -e "${GRN}║    ./setup.sh -full-reset  – wipe & reinstall    ║${NC}"
    echo -e "${GRN}╚══════════════════════════════════════════════════╝${NC}"
fi
echo ""
