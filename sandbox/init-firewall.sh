#!/bin/bash
# Firewall initialization script for Agent Workcell

set -e

# Allowed domains for supported agent operation
ALLOWED_DOMAINS=(
    # Claude API
    "api.anthropic.com"
    "claude.ai"
    "statsig.anthropic.com"
    "sentry.io"

    # OpenAI / Codex
    "api.openai.com"
    "chatgpt.com"
    "auth.openai.com"

    # OpenCode, including Zen and Go
    "opencode.ai"

    # JavaScript/TypeScript
    "registry.npmjs.org"
    "npmjs.com"
    "yarnpkg.com"
    "registry.yarnpkg.com"
    "nodejs.org"

    # Rust
    "crates.io"
    "static.crates.io"
    "index.crates.io"
    "doc.rust-lang.org"
    "docs.rs"
    "static.rust-lang.org"

    # GitHub (for cloning repos, etc.)
    "github.com"
    "api.github.com"
    "raw.githubusercontent.com"
    "objects.githubusercontent.com"

    # Google Cloud Storage (Claude Code updates)
    "storage.googleapis.com"
)

echo "Setting up firewall rules..."

# Flush existing rules
iptables -F OUTPUT 2>/dev/null || true

# Allow loopback
iptables -A OUTPUT -o lo -j ACCEPT

# Allow established connections
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow DNS
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# Resolve and allow each domain
for domain in "${ALLOWED_DOMAINS[@]}"; do
    echo "Allowing: $domain"
    # Get IPs for domain and add rules
    ips=$(dig +short "$domain" 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || true)
    for ip in $ips; do
        iptables -A OUTPUT -d "$ip" -j ACCEPT 2>/dev/null || true
    done
done

# Allow Flutter bridge connections if configured
if [ -n "$FLUTTER_BRIDGE_URL" ]; then
    # Extract host and port from FLUTTER_BRIDGE_URL (e.g., http://host.docker.internal:8765)
    bridge_host=$(echo "$FLUTTER_BRIDGE_URL" | sed -n 's|http://\([^:/]*\).*|\1|p')
    bridge_port=$(echo "$FLUTTER_BRIDGE_URL" | sed -n 's|.*:\([0-9]*\)$|\1|p')
    if [ -n "$bridge_host" ] && [ -n "$bridge_port" ]; then
        bridge_ip=$(getent hosts "$bridge_host" 2>/dev/null | awk '{print $1}' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
        if [ -z "$bridge_ip" ]; then
            bridge_ip=$(dig +short "$bridge_host" 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
        fi
        if [ -n "$bridge_ip" ]; then
            echo "Allowing Flutter bridge: $bridge_ip:$bridge_port"
            iptables -A OUTPUT -d "$bridge_ip" -p tcp --dport "$bridge_port" -j ACCEPT
        fi
    fi
fi

# Default deny - block everything else
iptables -A OUTPUT -j DROP

echo "Firewall setup complete!"
