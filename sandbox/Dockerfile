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

# Pre-create /opt/ template dirs owned by agent so each installer writes directly
# there via home symlinks — eliminating the end-of-build cp -a that doubled storage.
RUN mkdir -p /opt/nvm-template /opt/rustup-template /opt/cargo-template \
             /opt/claude-versions-template /opt/opencode-template \
    && chown agent:agent /opt/nvm-template /opt/rustup-template /opt/cargo-template \
                          /opt/claude-versions-template /opt/opencode-template

# Switch to agent user; /opt/ template dirs are already chown'd to agent.
USER agent
WORKDIR /home/agent

# Precache Linux engine artifacts into the SDK's bin/cache/ for offline use.
ENV FLUTTER_CLI_ANALYTICS_DISABLED=1
RUN /opt/flutter-sdk-template/bin/flutter precache \
        --no-android --no-ios --no-fuchsia --no-macos --no-windows --no-web

# Install Rust stable directly into /opt/ templates; symlink home dirs so the
# build-time PATH (/home/agent/.cargo/bin) resolves correctly.
ENV RUSTUP_HOME=/opt/rustup-template
ENV CARGO_HOME=/opt/cargo-template
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable \
    && ln -sf /opt/rustup-template /home/agent/.rustup \
    && ln -sf /opt/cargo-template /home/agent/.cargo

# Install nvm and Node.js LTS directly into /opt/nvm-template; symlink home dir so
# $NVM_DIR (/home/agent/.nvm) resolves correctly during the build.
ENV NVM_DIR="/home/agent/.nvm"
RUN ln -sf /opt/nvm-template /home/agent/.nvm \
    && curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash \
    && . /opt/nvm-template/nvm.sh \
    && nvm install --lts \
    && nvm use --lts \
    && nvm alias default lts/* \
    && ln -sf "$NVM_DIR/versions/node/$(nvm current)" "$NVM_DIR/current"

# Set up home→persist/ symlinks for Claude config and home→/opt/ for Claude binaries
# before running the installer so it writes directly to the final locations.
RUN mkdir -p /home/agent/persist/.claude /home/agent/.local/share \
    && echo '{}' > /home/agent/persist/.claude.json \
    && ln -sf /opt/claude-versions-template /home/agent/.local/share/claude \
    && ln -sf /home/agent/persist/.claude /home/agent/.claude \
    && ln -sf /home/agent/persist/.claude.json /home/agent/.claude.json

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

# Set up home→/opt/ symlink for opencode before running the installer.
RUN ln -sf /opt/opencode-template /home/agent/.opencode

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

# Persist Codex data. Codex creates ~/.codex on first use; bake in the symlink
# so it points to the volume before the entrypoint runs.
RUN mkdir -p /home/agent/persist/.codex \
    && ln -sf /home/agent/persist/.codex /home/agent/.codex

# Persist opencode data directories so config/state written at runtime lands on the volume.
RUN mkdir -p /home/agent/persist/.local/share/opencode \
             /home/agent/persist/.local/state/opencode \
             /home/agent/persist/.config/opencode \
             /home/agent/.local/share /home/agent/.local/state /home/agent/.config \
    && ln -sf /home/agent/persist/.local/share/opencode /home/agent/.local/share/opencode \
    && ln -sf /home/agent/persist/.local/state/opencode /home/agent/.local/state/opencode \
    && ln -sf /home/agent/persist/.config/opencode /home/agent/.config/opencode

# Copy scripts (after tool installs to preserve cache)
USER root
RUN mkdir -p /workspaces && chown agent:agent /workspaces
COPY init-firewall.sh /opt/init-firewall.sh
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/init-firewall.sh /opt/entrypoint.sh

# Copy agent context files. Entrypoint symlinks the main context into each
# agent config; focused context files stay available at their canonical /opt paths.
COPY agent-context.md /opt/agent-context.md
COPY agent-context-web.md /opt/agent-context-web.md
COPY agent-context-flutter.md /opt/agent-context-flutter.md
RUN chmod 0644 /opt/agent-context.md /opt/agent-context-web.md /opt/agent-context-flutter.md

# Run as root so entrypoint can configure the firewall; drops to agent user after.
WORKDIR /workspaces
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
