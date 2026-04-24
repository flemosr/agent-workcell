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

# Default deny - block everything else
iptables -A OUTPUT -j DROP

echo "Firewall setup complete!"
