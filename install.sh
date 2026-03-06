#!/usr/bin/env bash
# install.sh — Install the modelmux MCP server
#
# Usage:
#   ./install.sh                    # Install for Claude Code (user scope)
#   ./install.sh --claude           # Install for Claude Code
#   ./install.sh --codex            # Install for Codex CLI
#   ./install.sh --gemini           # Install for Gemini CLI
#   ./install.sh --all              # Install for all platforms
#   ./install.sh --check            # Check prerequisites only
#   ./install.sh --uninstall        # Remove MCP server registration
#   ./install.sh --local            # Use local source instead of PyPI

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUB_DIR="${SCRIPT_DIR}/mcp/modelmux"
USE_LOCAL=false
# uvx source: PyPI by default, local with --local flag
UVX_SRC="modelmux"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; }

check_prerequisites() {
    local ok=true

    echo "Checking prerequisites..."

    # Python 3.10+
    if command -v python3 &>/dev/null; then
        local pyver
        pyver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        local major minor
        major=$(echo "$pyver" | cut -d. -f1)
        minor=$(echo "$pyver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            info "Python ${pyver}"
        else
            error "Python ${pyver} (need 3.10+)"
            ok=false
        fi
    else
        error "Python 3 not found"
        ok=false
    fi

    # uv or uvx
    if command -v uvx &>/dev/null; then
        info "uvx $(uvx --version 2>/dev/null || echo 'available')"
    elif command -v uv &>/dev/null; then
        info "uv $(uv --version 2>/dev/null || echo 'available')"
    else
        error "uv/uvx not found (install: curl -LsSf https://astral.sh/uv/install.sh | sh)"
        ok=false
    fi

    # Model CLIs (optional, at least one needed)
    local has_any=false
    for cli in codex gemini claude; do
        if command -v "$cli" &>/dev/null; then
            info "${cli} CLI available"
            has_any=true
        else
            warn "${cli} CLI not found (optional)"
        fi
    done

    if [ "$has_any" = false ]; then
        error "No model CLIs found. Install at least one: codex, gemini, or claude"
        ok=false
    fi

    if [ "$ok" = true ]; then
        info "All prerequisites met"
    else
        error "Some prerequisites missing"
    fi

    $ok
}

install_claude() {
    info "Installing modelmux for Claude Code..."
    if [ "$USE_LOCAL" = true ]; then
        claude mcp add modelmux -s user --transport stdio -- \
            uvx --from "${HUB_DIR}" modelmux
    else
        claude mcp add modelmux -s user --transport stdio -- \
            uvx modelmux
    fi
    info "Claude Code: modelmux registered (user scope)"
    echo ""
    echo "  Optional: auto-approve tool calls by adding to ~/.claude/settings.json:"
    echo '    "permissions": { "allow": ["mcp__modelmux__mux_dispatch"] }'
}

install_codex() {
    local config_dir="${HOME}/.codex"
    local config_file="${config_dir}/config.toml"

    info "Installing modelmux for Codex CLI..."

    mkdir -p "${config_dir}"

    # Check if config exists and already has modelmux
    if [ -f "${config_file}" ] && grep -q "mcp_servers.modelmux" "${config_file}" 2>/dev/null; then
        warn "modelmux already configured in ${config_file}"
        return
    fi

    # Append MCP server config
    if [ "$USE_LOCAL" = true ]; then
        local uvx_args='["--from", "'"${HUB_DIR}"'", "modelmux"]'
    else
        local uvx_args='["modelmux"]'
    fi
    cat >> "${config_file}" <<TOML

[mcp_servers.modelmux]
command = "uvx"
args = ${uvx_args}
required = false
enabled_tools = ["mux_dispatch", "mux_check"]
tool_timeout_sec = 600
startup_timeout_sec = 30
TOML

    info "Codex CLI: modelmux added to ${config_file}"
}

install_gemini() {
    local config_dir="${HOME}/.gemini"
    local config_file="${config_dir}/settings.json"

    info "Installing modelmux for Gemini CLI..."

    mkdir -p "${config_dir}"

    # Build args JSON based on local/PyPI mode
    local args_json
    if [ "$USE_LOCAL" = true ]; then
        args_json="[\"--from\", \"${HUB_DIR}\", \"modelmux\"]"
    else
        args_json="[\"modelmux\"]"
    fi

    COLLAB_ARGS_JSON="$args_json" python3 -c "
import json, os, sys

config_file = '${config_file}'
args = json.loads(os.environ['COLLAB_ARGS_JSON'])

config = {}
if os.path.isfile(config_file):
    with open(config_file, 'r') as f:
        config = json.load(f)
    if 'modelmux' in config.get('mcpServers', {}):
        print('[!] modelmux already configured in ' + config_file)
        sys.exit(0)

config.setdefault('mcpServers', {})
config['mcpServers']['modelmux'] = {
    'command': 'uvx',
    'args': args,
    'timeout': 30000
}
with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)
"

    info "Gemini CLI: modelmux added to ${config_file}"
}

uninstall() {
    echo "Uninstalling modelmux..."

    # Claude Code
    if command -v claude &>/dev/null; then
        claude mcp remove modelmux -s user 2>/dev/null && \
            info "Removed from Claude Code" || \
            warn "Not found in Claude Code"
    fi

    # Codex
    local codex_config="${HOME}/.codex/config.toml"
    if [ -f "${codex_config}" ] && grep -q "modelmux" "${codex_config}"; then
        warn "Please manually remove [mcp_servers.modelmux] from ${codex_config}"
    fi

    # Gemini
    local gemini_config="${HOME}/.gemini/settings.json"
    if [ -f "${gemini_config}" ] && grep -q "modelmux" "${gemini_config}"; then
        python3 -c "
import json
with open('${gemini_config}', 'r') as f:
    config = json.load(f)
config.get('mcpServers', {}).pop('modelmux', None)
with open('${gemini_config}', 'w') as f:
    json.dump(config, f, indent=2)
" && info "Removed from Gemini CLI" || warn "Failed to update Gemini config"
    fi
}

# Main
ACTION=""
PLATFORMS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --claude)    PLATFORMS+=("claude"); shift ;;
        --codex)     PLATFORMS+=("codex"); shift ;;
        --gemini)    PLATFORMS+=("gemini"); shift ;;
        --all)       PLATFORMS=("claude" "codex" "gemini"); shift ;;
        --local)     USE_LOCAL=true; shift ;;
        --check)     ACTION="check"; shift ;;
        --uninstall) ACTION="uninstall"; shift ;;
        -h|--help)
            echo "Usage: install.sh [--claude] [--codex] [--gemini] [--all] [--local] [--check] [--uninstall]"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Default: Claude only
if [ ${#PLATFORMS[@]} -eq 0 ] && [ -z "$ACTION" ]; then
    PLATFORMS=("claude")
fi

if [ "$ACTION" = "check" ]; then
    check_prerequisites
    exit $?
fi

if [ "$ACTION" = "uninstall" ]; then
    uninstall
    exit 0
fi

echo "=== modelmux MCP Server Installer ==="
echo ""

check_prerequisites || exit 1
echo ""

for platform in "${PLATFORMS[@]}"; do
    case $platform in
        claude) install_claude ;;
        codex)  install_codex ;;
        gemini) install_gemini ;;
    esac
    echo ""
done

echo "=== Installation complete ==="
echo ""
echo "Test it with:"
echo "  mux_dispatch(provider='codex', task='hello world', workdir='.')"
