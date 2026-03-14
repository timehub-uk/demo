#!/bin/bash
# ============================================================
# BinanceML Pro – One-command setup (Mac / Linux / Ubuntu)
# Requires Python 3.12+
# ============================================================
set -e

echo "╔══════════════════════════════════════════════════╗"
echo "║       BinanceML Pro – Environment Setup          ║"
echo "╚══════════════════════════════════════════════════╝"

# Detect platform
ARCH=$(uname -m)
OS=$(uname -s)
echo "▶ Platform: $OS $ARCH"

# Python version check
PYTHON=$(which python3.12 2>/dev/null || which python3.11 2>/dev/null || which python3 2>/dev/null)
if [ -z "$PYTHON" ]; then
    echo "❌ Python 3.11+ required. Install via: brew install python@3.12"
    exit 1
fi
echo "▶ Python: $($PYTHON --version)"

# Create virtual environment
VENV_DIR="$(dirname "$0")/../.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "▶ Creating virtual environment…"
    $PYTHON -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Upgrade pip
pip install --upgrade pip setuptools wheel --quiet

# Install requirements
# --pre is required for pandas-ta 0.4.x which explicitly targets Python 3.12+
echo "▶ Installing Python dependencies…"
pip install --pre -r "$(dirname "$0")/../requirements.txt" \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    --quiet

# PostgreSQL setup check
echo ""
echo "▶ Checking PostgreSQL…"
if command -v psql &>/dev/null; then
    echo "  PostgreSQL found: $(psql --version)"
    # Create database if it doesn't exist
    createdb binanceml 2>/dev/null && echo "  Database 'binanceml' created." || echo "  Database 'binanceml' already exists."
    createuser binanceml 2>/dev/null && echo "  User 'binanceml' created." || echo "  User 'binanceml' already exists."
    psql -c "ALTER USER binanceml WITH PASSWORD 'binanceml';" 2>/dev/null || true
    psql -c "GRANT ALL PRIVILEGES ON DATABASE binanceml TO binanceml;" 2>/dev/null || true
else
    echo "  ⚠ PostgreSQL not found. Install with: brew install postgresql@16"
    echo "    Then run: brew services start postgresql@16"
fi

# Redis check
echo ""
echo "▶ Checking Redis…"
if command -v redis-cli &>/dev/null; then
    echo "  Redis found: $(redis-cli --version)"
    redis-cli ping 2>/dev/null && echo "  Redis is running." || echo "  ⚠ Redis not running. Start with: brew services start redis"
else
    echo "  ⚠ Redis not found. Install with: brew install redis"
    echo "    Then run: brew services start redis"
fi

# Config directory
echo ""
echo "▶ Creating config directories…"
mkdir -p ~/.binanceml/{models,reports,logs}
echo "  ~/.binanceml/ created."

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Setup complete! Run the app with:               ║"
echo "║    source .venv/bin/activate                     ║"
echo "║    python trading_bot/main.py                    ║"
echo "╚══════════════════════════════════════════════════╝"
