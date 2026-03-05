#!/usr/bin/env bash
# install.sh — Install the collab-hub MCP server
#
# Usage:
#   ./install.sh                    # Install for Claude Code (user scope)
#   ./install.sh --claude           # Install for Claude Code
#   ./install.sh --codex            # Install for Codex CLI
#   ./install.sh --gemini           # Install for Gemini CLI
#   ./install.sh --all              # Install for all platforms
#   ./install.sh --check            # Check prerequisites only
#   ./install.sh --uninstall        # Remove MCP server registration

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUB_DIR="${SCRIPT_DIR}/mcp/collab-hub"

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
    info "Installing collab-hub for Claude Code..."
    claude mcp add collab-hub -s user --transport stdio -- \
        uvx --from "${HUB_DIR}" collab-hub
    info "Claude Code: collab-hub registered (user scope)"
    echo ""
    echo "  Optional: auto-approve tool calls by adding to ~/.claude/settings.json:"
    echo '    "permissions": { "allow": ["mcp__collab-hub__collab_dispatch"] }'
}

install_codex() {
    local config_dir="${HOME}/.codex"
    local config_file="${config_dir}/config.toml"

    info "Installing collab-hub for Codex CLI..."

    mkdir -p "${config_dir}"

    # Check if config exists and already has collab-hub
    if [ -f "${config_file}" ] && grep -q "mcp_servers.collab-hub" "${config_file}" 2>/dev/null; then
        warn "collab-hub already configured in ${config_file}"
        return
    fi

    # Append MCP server config
    cat >> "${config_file}" <<TOML

[mcp_servers.collab-hub]
command = "uvx"
args = ["--from", "${HUB_DIR}", "collab-hub"]
required = false
enabled_tools = ["collab_dispatch", "collab_check"]
tool_timeout_sec = 600
startup_timeout_sec = 30
TOML

    info "Codex CLI: collab-hub added to ${config_file}"
}

install_gemini() {
    local config_dir="${HOME}/.gemini"
    local config_file="${config_dir}/settings.json"

    info "Installing collab-hub for Gemini CLI..."

    mkdir -p "${config_dir}"

    if [ -f "${config_file}" ]; then
        # Check if already configured
        if python3 -c "
import json, sys
d = json.load(open('${config_file}'))
if 'collab-hub' in d.get('mcpServers', {}):
    sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
            warn "collab-hub already configured in ${config_file}"
            return
        fi

        # Merge into existing config
        python3 -c "
import json
with open('${config_file}', 'r') as f:
    config = json.load(f)
config.setdefault('mcpServers', {})
config['mcpServers']['collab-hub'] = {
    'command': 'uvx',
    'args': ['--from', '${HUB_DIR}', 'collab-hub'],
    'timeout': 30000
}
with open('${config_file}', 'w') as f:
    json.dump(config, f, indent=2)
"
    else
        # Create new config
        python3 -c "
import json
config = {
    'mcpServers': {
        'collab-hub': {
            'command': 'uvx',
            'args': ['--from', '${HUB_DIR}', 'collab-hub'],
            'timeout': 30000
        }
    }
}
with open('${config_file}', 'w') as f:
    json.dump(config, f, indent=2)
"
    fi

    info "Gemini CLI: collab-hub added to ${config_file}"
}

uninstall() {
    echo "Uninstalling collab-hub..."

    # Claude Code
    if command -v claude &>/dev/null; then
        claude mcp remove collab-hub -s user 2>/dev/null && \
            info "Removed from Claude Code" || \
            warn "Not found in Claude Code"
    fi

    # Codex
    local codex_config="${HOME}/.codex/config.toml"
    if [ -f "${codex_config}" ] && grep -q "collab-hub" "${codex_config}"; then
        warn "Please manually remove [mcp_servers.collab-hub] from ${codex_config}"
    fi

    # Gemini
    local gemini_config="${HOME}/.gemini/settings.json"
    if [ -f "${gemini_config}" ] && grep -q "collab-hub" "${gemini_config}"; then
        python3 -c "
import json
with open('${gemini_config}', 'r') as f:
    config = json.load(f)
config.get('mcpServers', {}).pop('collab-hub', None)
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
        --check)     ACTION="check"; shift ;;
        --uninstall) ACTION="uninstall"; shift ;;
        -h|--help)
            echo "Usage: install.sh [--claude] [--codex] [--gemini] [--all] [--check] [--uninstall]"
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

echo "=== collab-hub MCP Server Installer ==="
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
echo "  collab_dispatch(provider='codex', task='hello world', workdir='.')"
