# Claude Code Sandbox Environment
# Based on official devcontainer: https://github.com/anthropics/claude-code/tree/main/.devcontainer
FROM debian:bookworm

# Install development tools and security packages
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    vim \
    jq \
    ripgrep \
    fd-find \
    python3 \
    python3-pip \
    build-essential \
    zsh \
    fzf \
    iptables \
    iproute2 \
    dnsutils \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for safety
RUN useradd -m -s /bin/bash claude \
    && mkdir -p /home/claude/.local/bin \
    && chown -R claude:claude /home/claude

# Switch to claude user for Claude Code installation
USER claude
WORKDIR /home/claude

# Install Claude Code using the official native installer
RUN curl -fsSL https://claude.ai/install.sh | bash

# Add Claude to PATH
ENV PATH="/home/claude/.local/bin:${PATH}"

# Create workspace directory
RUN mkdir -p /home/claude/workspace

# Set up Claude Code config directory
RUN mkdir -p /home/claude/.claude

WORKDIR /home/claude/workspace

# Default command
CMD ["bash"]
