# Agent Workcell Environment
# Based on official devcontainer: https://github.com/anthropics/claude-code/tree/main/.devcontainer
FROM debian:bookworm

RUN apt-get update && apt-get install -y \
    bubblewrap \
    git \
    curl \
    wget \
    vim \
    jq \
    ripgrep \
    fd-find \
    build-essential \
    pkg-config \
    libssl-dev \
    zsh \
    fzf \
    iptables \
    iproute2 \
    dnsutils \
    ca-certificates \
    procps \
    psmisc \
    lsof \
    python3 \
    python3-pip \
    python3-venv \
    unzip \
    xz-utils \
    strace \
    gnupg \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install yq
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${ARCH}" -o /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq

RUN useradd -m -s /bin/bash agent \
    && mkdir -p /home/agent/.local/bin \
    && chown -R agent:agent /home/agent

# Download Flutter SDK to /opt/flutter-sdk-template/ for volume seeding (nvm/Rust pattern).
# amd64: official tarball; arm64: git clone (no prebuilt arm64 Linux tarball available).
# First in the file so only a FLUTTER_VERSION bump invalidates this layer.
ARG FLUTTER_VERSION=3.41.8
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
        mkdir -p /opt/flutter-sdk-template && \
        curl -fsSL \
            "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
            -o /tmp/flutter.tar.xz && \
        tar -xJf /tmp/flutter.tar.xz --strip-components=1 -C /opt/flutter-sdk-template && \
        rm -f /tmp/flutter.tar.xz; \
    elif [ "$ARCH" = "arm64" ]; then \
        git clone --depth 1 -b "${FLUTTER_VERSION}" \
            https://github.com/flutter/flutter.git /opt/flutter-sdk-template; \
    else \
        echo "Unsupported architecture for Flutter SDK: $ARCH" >&2; exit 1; \
    fi && \
    chown -R agent:agent /opt/flutter-sdk-template

# Switch to agent user; /opt/flutter-sdk-template/ is already chown'd to agent.
USER agent
WORKDIR /home/agent

# Precache Linux engine artifacts into the SDK's bin/cache/ for offline use.
ENV FLUTTER_CLI_ANALYTICS_DISABLED=1
RUN /opt/flutter-sdk-template/bin/flutter precache \
        --no-android --no-ios --no-fuchsia --no-macos --no-windows --no-web

# Install Rust stable
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable

# Install nvm and Node.js LTS
ENV NVM_DIR="/home/agent/.nvm"
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install --lts \
    && nvm use --lts \
    && nvm alias default lts/* \
    && ln -sf "$NVM_DIR/versions/node/$(nvm current)" "$NVM_DIR/current"

# Install Claude Code using the official native installer
RUN curl -fsSL https://claude.ai/install.sh | bash

# Prefer image-baked tools over volume-backed npm globals; activate Python venv globally.
ENV PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:${PATH}"
ENV VIRTUAL_ENV="/home/agent/.local/python-venv"
# Flutter SDK is volume-backed; add to PATH for runtime use.
ENV PATH="/home/agent/persist/.flutter-sdk/bin:${PATH}"

# Install Python linters, data science libs, and Playwright.
RUN python3 -m venv ~/.local/python-venv && \
    ~/.local/python-venv/bin/pip install playwright pyright ruff matplotlib numpy

# Copy browser tools
COPY --chown=agent:agent browser-tools/ /home/agent/.local/browser-tools/
RUN chmod +x /home/agent/.local/browser-tools/browser.sh && \
    ln -sf /home/agent/.local/browser-tools/browser.sh /home/agent/.local/bin/browser

# Copy flutter tools
COPY --chown=agent:agent flutter-tools/ /home/agent/.local/flutter-tools/
RUN chmod +x /home/agent/.local/flutter-tools/flutterctl.sh && \
    ln -sf /home/agent/.local/flutter-tools/flutterctl.sh /home/agent/.local/bin/flutterctl

# Install opencode. Placed after the Python venv to preserve that heavier layer's cache.
# The installer drops the binary at ~/.opencode/bin/opencode; symlink into ~/.local/bin.
RUN curl -fsSL https://opencode.ai/install | bash \
    && ln -sf /home/agent/.opencode/bin/opencode /home/agent/.local/bin/opencode

# Install Codex. ADD fetches the releases API as the layer cache key so docker
# compose build picks up new releases automatically without --no-cache.
ADD --chown=agent:agent https://api.github.com/repos/openai/codex/releases/latest /tmp/codex-release.json
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
        amd64) CODEX_ARCH="x86_64-unknown-linux-musl" ;; \
        arm64) CODEX_ARCH="aarch64-unknown-linux-musl" ;; \
        *) echo "Unsupported architecture for codex: $ARCH" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/openai/codex/releases/latest/download/codex-${CODEX_ARCH}.tar.gz" \
        -o /tmp/codex.tar.gz && \
    tar -xzf /tmp/codex.tar.gz -C /tmp && \
    install -m 0755 "/tmp/codex-${CODEX_ARCH}" /home/agent/.local/bin/codex && \
    rm -f /tmp/codex.tar.gz /tmp/codex-release.json "/tmp/codex-${CODEX_ARCH}"

# Persistent volume structure: all user data lives under ~/persist/.
RUN mkdir -p /home/agent/persist/.claude

# Move installer-created files to volume location
RUN mv /home/agent/.claude.json /home/agent/persist/.claude.json 2>/dev/null || true \
    && mv /home/agent/.claude/* /home/agent/persist/.claude/ 2>/dev/null || true

# Remove original directory and create symlinks to volume
RUN rm -rf /home/agent/.claude \
    && ln -sf /home/agent/persist/.claude /home/agent/.claude \
    && ln -sf /home/agent/persist/.claude.json /home/agent/.claude.json

# Persist Claude Code binaries to avoid re-downloading on every container restart.
RUN mv /home/agent/.local/share/claude /home/agent/persist/.claude-versions 2>/dev/null || true \
    && ln -sf /home/agent/persist/.claude-versions /home/agent/.local/share/claude

# Persist opencode data, config, and UI state; mirrors the claude pattern.
RUN mkdir -p /home/agent/persist/.local/share /home/agent/persist/.local/state /home/agent/persist/.config \
    && mv /home/agent/.local/share/opencode /home/agent/persist/.local/share/opencode 2>/dev/null || true \
    && mv /home/agent/.config/opencode /home/agent/persist/.config/opencode 2>/dev/null || true \
    && mv /home/agent/.local/state/opencode /home/agent/persist/.local/state/opencode 2>/dev/null || true \
    && mkdir -p /home/agent/persist/.local/share/opencode /home/agent/persist/.local/state/opencode /home/agent/persist/.config/opencode \
    && mkdir -p /home/agent/.local/share /home/agent/.local/state /home/agent/.config \
    && rm -rf /home/agent/.local/share/opencode /home/agent/.local/state/opencode /home/agent/.config/opencode \
    && ln -sf /home/agent/persist/.local/share/opencode /home/agent/.local/share/opencode \
    && ln -sf /home/agent/persist/.local/state/opencode /home/agent/.local/state/opencode \
    && ln -sf /home/agent/persist/.config/opencode /home/agent/.config/opencode

# Persist Codex data. Codex creates ~/.codex on first use; bake in the symlink
# so it points to the volume before the entrypoint runs.
RUN mkdir -p /home/agent/persist/.codex \
    && ln -sf /home/agent/persist/.codex /home/agent/.codex

# Copy toolchain installs to /opt/ templates for volume seeding on first run.
USER root
RUN cp -a /home/agent/.nvm /opt/nvm-template \
    && cp -a /home/agent/.rustup /opt/rustup-template \
    && cp -a /home/agent/.cargo /opt/cargo-template \
    && cp -a /home/agent/persist/.claude-versions /opt/claude-versions-template \
    && cp -a /home/agent/.opencode /opt/opencode-template

# Copy scripts (after tool installs to preserve cache)
RUN mkdir -p /workspaces && chown agent:agent /workspaces
COPY init-firewall.sh /opt/init-firewall.sh
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/init-firewall.sh /opt/entrypoint.sh

# Copy agent context files; entrypoint syncs these to the volume on each start.
COPY agent-context.md /opt/agent-context.md
COPY agent-context-web.md /opt/agent-context-web.md
COPY agent-context-flutter.md /opt/agent-context-flutter.md

# Run as root so entrypoint can configure the firewall; drops to agent user after.
WORKDIR /workspaces
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
