#!/usr/bin/env bash
#
# Signalis — Installer (macOS / Linux)
#
# Usage:
#   chmod +x install.sh && ./install.sh
#

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Helpers ───────────────────────────────────────────────────────────────────
ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
fail() { echo -e "  ${RED}✗${NC}  $*" >&2; }
warn() { echo -e "  ${YELLOW}→${NC}  $*"; }
info() { echo -e "  ${DIM}$*${NC}"; }
step() { echo -e "\n${CYAN}[$1]${NC} $2"; }

die() {
    echo ""
    fail "$1"
    echo ""
    exit 1
}

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}"
echo "███████╗██╗ ██████╗ ███╗   ██╗  █████╗ ██╗     ██╗███████╗"
echo "██╔════╝██║██╔════╝ ████╗  ██║ ██╔══██╗██║     ██║██╔════╝"
echo "███████╗██║██║  ███╗██╔██╗ ██║ ███████║██║     ██║███████╗"
echo "╚════██║██║██║   ██║██║╚██╗██║ ██╔══██║██║     ██║╚════██║"
echo "███████║██║╚██████╔╝██║ ╚████║ ██║  ██║███████╗██║███████║"
echo "╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═╝  ╚═╝╚══════╝╚═╝╚══════╝"
echo -e "${NC}"
echo -e "${DIM}  Installer · macOS / Linux${NC}"
echo ""

# ── [1/4] Python ──────────────────────────────────────────────────────────────
step "1/4" "Checking Python..."

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo ""
    fail "Python not found."
    echo ""
    echo -e "  Install Python 3.9+ and try again:"
    if [[ "${OSTYPE:-}" == "darwin"* ]]; then
        echo -e "    ${CYAN}brew install python3${NC}"
        echo -e "    ${DIM}or: https://www.python.org/downloads/${NC}"
    else
        echo -e "    ${CYAN}sudo apt install python3 python3-venv${NC}  ${DIM}(Debian/Ubuntu)${NC}"
        echo -e "    ${CYAN}sudo dnf install python3${NC}              ${DIM}(Fedora/RHEL)${NC}"
        echo -e "    ${DIM}or: https://www.python.org/downloads/${NC}"
    fi
    echo ""
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_CMD" --version 2>&1 | awk '{print $2}')
MAJOR=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.major)")
MINOR=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.minor)")

if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 9 ]; }; then
    die "Python 3.9+ required — found ${PYTHON_VERSION}. Please upgrade."
fi

ok "Python ${PYTHON_VERSION}"

# ── [2/4] Virtual environment + dependencies ──────────────────────────────────
step "2/4" "Installing dependencies..."

VENV_DIR="$SCRIPT_DIR/venv"

if [ -d "$VENV_DIR" ]; then
    # Check if the existing venv's Python is still functional (can break after OS Python updates)
    if ! "$VENV_DIR/bin/python" --version &>/dev/null; then
        warn "Existing venv is broken — recreating..."
        rm -rf "$VENV_DIR"
        if ! "$PYTHON_CMD" -m venv "$VENV_DIR" 2>/dev/null; then
            echo ""
            fail "Failed to recreate virtual environment."
            if [[ "${OSTYPE:-}" != "darwin"* ]]; then
                echo -e "  Try: ${CYAN}sudo apt install python3-venv${NC}"
            fi
            echo ""
            exit 1
        fi
        info "Recreated virtual environment"
    else
        warn "Existing venv found — reusing (run 'rm -rf venv' to start fresh)"
    fi
else
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR" 2>/dev/null; then
        echo ""
        fail "Failed to create virtual environment."
        echo ""
        if [[ "${OSTYPE:-}" != "darwin"* ]]; then
            echo -e "  On Debian/Ubuntu, install the venv module first:"
            echo -e "    ${CYAN}sudo apt install python3-venv${NC}"
            echo ""
            echo -e "  On Fedora/RHEL:"
            echo -e "    ${CYAN}sudo dnf install python3-devel${NC}"
            echo ""
        fi
        exit 1
    fi
    info "Created virtual environment"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

pip install --upgrade pip --quiet --disable-pip-version-check

# Capture pip output — show it only if the install fails so normal runs stay clean
PIP_LOG="$(mktemp)"
if ! pip install -e "$SCRIPT_DIR[all]" --disable-pip-version-check > "$PIP_LOG" 2>&1; then
    echo ""
    echo -e "  ${RED}pip output (last 30 lines):${NC}"
    tail -30 "$PIP_LOG"
    rm -f "$PIP_LOG"
    die "Dependency installation failed. See output above."
fi
rm -f "$PIP_LOG"

ok "Installed (Shaper · Connector — full install)."

BINARY="$VENV_DIR/bin/signalis"

if [ ! -f "$BINARY" ]; then
    die "signalis binary not found at $BINARY — installation may have failed."
fi

# ── [3/4] Global launcher ─────────────────────────────────────────────────────
step "3/4" "Adding to PATH..."

LAUNCHER_PATH=""
SHELL_NOTE=""
USER_SHELL="$(basename "${SHELL:-bash}")"

# Try /usr/local/bin first (no sudo — only if already writable)
if [ -w "/usr/local/bin" ]; then
    ln -sf "$BINARY" /usr/local/bin/signalis
    LAUNCHER_PATH="/usr/local/bin/signalis"
fi

# Fall back to ~/.local/bin (always writable, no permissions needed)
if [ -z "$LAUNCHER_PATH" ]; then
    mkdir -p "$HOME/.local/bin"
    ln -sf "$BINARY" "$HOME/.local/bin/signalis"
    LAUNCHER_PATH="$HOME/.local/bin/signalis"

    # Fish shell uses a different config location and syntax
    if [ "$USER_SHELL" = "fish" ]; then
        TARGET_RC="$HOME/.config/fish/config.fish"
        mkdir -p "$(dirname "$TARGET_RC")"
        if ! grep -q '\.local/bin' "$TARGET_RC" 2>/dev/null; then
            {
                echo ''
                echo '# Signalis'
                echo 'fish_add_path ~/.local/bin'
            } >> "$TARGET_RC"
            SHELL_NOTE="config.fish"
        fi
    else
        # Pick the right rc file per shell + OS:
        #   zsh              → .zshrc  (sourced for all interactive shells)
        #   bash on macOS    → .bash_profile  (Terminal opens login shells; .bashrc is not sourced)
        #   bash on Linux    → .bashrc
        #   anything else    → .profile
        case "$USER_SHELL" in
            zsh)  TARGET_RC="$HOME/.zshrc" ;;
            bash)
                if [[ "${OSTYPE:-}" == "darwin"* ]]; then
                    TARGET_RC="$HOME/.bash_profile"
                else
                    TARGET_RC="$HOME/.bashrc"
                fi
                ;;
            *)    TARGET_RC="$HOME/.profile" ;;
        esac

        if ! grep -q '\.local/bin' "$TARGET_RC" 2>/dev/null; then
            {
                echo ''
                echo '# Signalis'
                echo 'export PATH="$HOME/.local/bin:$PATH"'
            } >> "$TARGET_RC"
            SHELL_NOTE="$(basename "$TARGET_RC")"
        fi
    fi
fi

ok "signalis → ${LAUNCHER_PATH}"

if [ -n "$SHELL_NOTE" ]; then
    warn "Added ~/.local/bin to PATH in ~/${SHELL_NOTE}"
    echo ""
    echo -e "  ${BOLD}Run this now to activate in your current terminal:${NC}"
    echo ""
    if [ "$USER_SHELL" = "fish" ]; then
        echo -e "    ${CYAN}source ~/.config/fish/config.fish${NC}"
    else
        echo -e "    ${CYAN}source ~/${SHELL_NOTE}${NC}"
    fi
    echo ""
fi

# ── [4/4] Configuration ───────────────────────────────────────────────────────
step "4/4" "Configuration..."

ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        ok "Created .env from template"
    else
        warn ".env.example not found — skipping .env creation"
    fi
else
    warn ".env already exists — keeping your settings"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${DIM}  ________________________________________${NC}"
echo -e "${GREEN}${BOLD}  Installation complete.${NC}"
echo -e "${DIM}  ________________________________________${NC}"
echo ""

# Prompt for API key setup if any keys are missing
HAS_EXA=$(grep -s 'EXA_API_KEY=.' "$ENV_FILE" || true)
HAS_AI=$(grep -sE '(OPENAI_API_KEY|ANTHROPIC_API_KEY)=.' "$ENV_FILE" || true)

if [ -z "$HAS_EXA" ] || [ -z "$HAS_AI" ]; then
    echo -e "  ${YELLOW}API keys not configured.${NC} ${DIM}Exa + an AI provider are needed for signals & context.${NC}"
    echo ""
    read -r -p "  Set up API keys now? [Y/n]: " run_setup
    echo ""
    if [[ "${run_setup:-}" != "n" && "${run_setup:-}" != "N" ]]; then
        "$BINARY" setup
    else
        echo -e "  ${DIM}Run ${BOLD}signalis setup${NC}${DIM} whenever you're ready.${NC}"
    fi
else
    echo -e "  ${DIM}API keys are configured. Run ${BOLD}signalis setup${NC}${DIM} to update them.${NC}"
fi

echo ""
echo -e "  Launch with:"
echo ""
# If PATH was written to a shell rc file, remind the user to source it first
if [ -n "$SHELL_NOTE" ]; then
    if [ "$USER_SHELL" = "fish" ]; then
        echo -e "    ${DIM}1.${NC}  source ~/.config/fish/config.fish"
    else
        echo -e "    ${DIM}1.${NC}  source ~/${SHELL_NOTE}"
    fi
    echo -e "    ${DIM}2.${NC}  ${CYAN}${BOLD}signalis${NC}"
else
    echo -e "    ${CYAN}${BOLD}signalis${NC}"
fi
echo ""
