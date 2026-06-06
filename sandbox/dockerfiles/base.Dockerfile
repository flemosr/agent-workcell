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

ARG YQ_VERSION=4.53.2
RUN ARCH=$(dpkg --print-architecture) && \
    curl --http1.1 --retry 5 --retry-delay 5 --retry-all-errors -fsSL \
        "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_${ARCH}" \
        -o /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq

RUN useradd -m -s /bin/bash agent \
    && mkdir -p /home/agent/.local/bin \
    && chown -R agent:agent /home/agent

# Download Flutter SDK into an image-owned SDK root.
# The late /opt/flutter-sdk alias gives runtime code a stable path without
# invalidating this expensive layer when the persistence wiring changes.
# amd64: official tarball; arm64: git clone (no prebuilt arm64 Linux tarball available).
ARG FLUTTER_VERSION=3.41.9
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
             /opt/pub-cache-template \
    && chown agent:agent /opt/nvm-template /opt/rustup-template /opt/cargo-template \
                          /opt/pub-cache-template

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
ARG NVM_VERSION=0.40.4
ENV NVM_DIR="/home/agent/.nvm"
RUN ln -sf /opt/nvm-template /home/agent/.nvm \
    && curl -o- "https://raw.githubusercontent.com/nvm-sh/nvm/v${NVM_VERSION}/install.sh" | bash \
    && . /opt/nvm-template/nvm.sh \
    && nvm install --lts \
    && nvm use --lts \
    && nvm alias default lts/* \
    && ln -sf "$NVM_DIR/versions/node/$(nvm current)" "$NVM_DIR/current"

# Prefer image-baked tools over volume-backed npm globals; activate Python venv globally.
# Keep ~/.local/bin ahead of the SDK so the workcell flutter/dart wrappers can
# repair package metadata before delegating to the real SDK binaries.
ENV PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:${PATH}"
ENV VIRTUAL_ENV="/home/agent/.local/python-venv"
# Temporary build-time Flutter path; a final runtime PATH is declared after the
# stable /opt aliases are created.
ENV PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:/home/agent/persist/.flutter-sdk/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:${PATH}"

# Install Python linters, data science libs, and Playwright.
RUN python3 -m venv ~/.local/python-venv && \
    ~/.local/python-venv/bin/pip install playwright pyright ruff matplotlib numpy

# Copy local wrapper tools after network-installed agents so wrapper edits do
# not invalidate the OpenCode or Codex install layers.
COPY --chown=agent:agent browser-tools/ /home/agent/.local/browser-tools/
RUN chmod +x /home/agent/.local/browser-tools/browser.sh && \
    ln -sf /home/agent/.local/browser-tools/browser.sh /home/agent/.local/bin/browser

COPY --chown=agent:agent flutter-tools/ /home/agent/.local/flutter-tools/
RUN chmod +x /home/agent/.local/flutter-tools/flutterctl.sh \
             /home/agent/.local/flutter-tools/flutter.sh \
             /home/agent/.local/flutter-tools/dart.sh \
             /home/agent/.local/flutter-tools/package_config_guard.py && \
    ln -sf /home/agent/.local/flutter-tools/flutterctl.sh /home/agent/.local/bin/flutterctl && \
    ln -sf /home/agent/.local/flutter-tools/flutter.sh /home/agent/.local/bin/flutter && \
    ln -sf /home/agent/.local/flutter-tools/dart.sh /home/agent/.local/bin/dart

# Copy scripts (after tool installs to preserve cache)
USER root
RUN mkdir -p /workspaces && chown agent:agent /workspaces

# Stable image-owned runtime paths. The underlying template directories remain
# as the build cache anchors for expensive installer layers.
RUN ln -sfn /opt/flutter-sdk-template /opt/flutter-sdk \
    && ln -sfn /opt/pub-cache-template/bin/protoc-gen-dart /home/agent/.local/bin/protoc-gen-dart \
    && chown -h agent:agent /opt/flutter-sdk /home/agent/.local/bin/protoc-gen-dart

# Install release-binary protobuf CLIs and generators late so version bumps do
# not invalidate expensive Flutter, Rust, Node, Python, or agent install layers.
ARG PROTOC_VERSION=34.1
ARG BUF_VERSION=1.69.0
ARG GRPCURL_VERSION=1.9.3
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
        amd64) PROTOC_ARCH="x86_64"; BUF_ARCH="x86_64"; GRPCURL_ARCH="x86_64" ;; \
        arm64) PROTOC_ARCH="aarch_64"; BUF_ARCH="aarch64"; GRPCURL_ARCH="arm64" ;; \
        *) echo "Unsupported architecture for protobuf tooling: $ARCH" >&2; exit 1 ;; \
    esac && \
    curl --http1.1 --retry 5 --retry-delay 5 --retry-all-errors -fsSL \
        "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/protoc-${PROTOC_VERSION}-linux-${PROTOC_ARCH}.zip" \
        -o /tmp/protoc.zip && \
    mkdir -p /tmp/protoc /usr/local/include && \
    unzip -q /tmp/protoc.zip -d /tmp/protoc && \
    install -m 0755 /tmp/protoc/bin/protoc /usr/local/bin/protoc && \
    cp -a /tmp/protoc/include/. /usr/local/include/ && \
    curl --http1.1 --retry 5 --retry-delay 5 --retry-all-errors -fsSL \
        "https://github.com/bufbuild/buf/releases/download/v${BUF_VERSION}/buf-Linux-${BUF_ARCH}" \
        -o /usr/local/bin/buf && \
    chmod +x /usr/local/bin/buf && \
    curl --http1.1 --retry 5 --retry-delay 5 --retry-all-errors -fsSL \
        "https://github.com/fullstorydev/grpcurl/releases/download/v${GRPCURL_VERSION}/grpcurl_${GRPCURL_VERSION}_linux_${GRPCURL_ARCH}.tar.gz" \
        -o /tmp/grpcurl.tar.gz && \
    tar -xzf /tmp/grpcurl.tar.gz -C /tmp grpcurl && \
    install -m 0755 /tmp/grpcurl /usr/local/bin/grpcurl && \
    rm -rf /tmp/protoc /tmp/protoc.zip /tmp/grpcurl.tar.gz /tmp/grpcurl

USER agent
ARG PROTOC_PLUGIN_VERSION=25.0.0
RUN PUB_CACHE=/opt/pub-cache-template \
    /opt/flutter-sdk-template/bin/dart pub global activate protoc_plugin "${PROTOC_PLUGIN_VERSION}" \
    && ln -sf /opt/pub-cache-template /home/agent/.pub-cache \
    && ln -sf /home/agent/.pub-cache/bin/protoc-gen-dart /home/agent/.local/bin/protoc-gen-dart

ARG PROTOC_GEN_PROST_VERSION=0.5.0
RUN PATH="/home/agent/.cargo/bin:${PATH}" \
    /home/agent/.cargo/bin/cargo install \
        --root /home/agent/.local \
        --version "${PROTOC_GEN_PROST_VERSION}" \
        protoc-gen-prost

USER root

# Make nvm available in non-interactive bash shells used by coding agents.
# ~/.bashrc only loads nvm for interactive shells; bash sources $BASH_ENV for
# non-interactive commands such as `bash -c "node --version"`.
RUN cat > /etc/profile.d/workcell-nvm.sh <<'EOF' && chmod 0644 /etc/profile.d/workcell-nvm.sh
export NVM_DIR="${NVM_DIR:-/home/agent/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  . "$NVM_DIR/nvm.sh"
fi
if [ -d "$NVM_DIR/current/bin" ]; then
  case ":$PATH:" in
    *":$NVM_DIR/current/bin:"*) ;;
    *) export PATH="$NVM_DIR/current/bin:$PATH" ;;
  esac
fi
EOF

# Final runtime PATH: wrappers first, image-owned Flutter SDK next, persisted
# nvm/cargo toolchains after that.
ENV PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:/opt/flutter-sdk/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENV BASH_ENV="/etc/profile.d/workcell-nvm.sh"

ENV WORKCELL_IMAGE_AGENT=""
COPY init-firewall.sh /opt/init-firewall.sh
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/init-firewall.sh /opt/entrypoint.sh

# Copy agent context files. Entrypoint seeds the main context and default skills
# into agent config only when absent.
COPY DEFAULT_AGENTS.md /opt/agent-context.md
COPY default-skills/ /opt/agent-default-skills/
RUN chmod 0644 /opt/agent-context.md \
    && find /opt/agent-default-skills -type d -exec chmod 0755 {} + \
    && find /opt/agent-default-skills -type f -exec chmod 0644 {} +

# Run as root so entrypoint can configure the firewall; drops to agent user after.
WORKDIR /workspaces
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
