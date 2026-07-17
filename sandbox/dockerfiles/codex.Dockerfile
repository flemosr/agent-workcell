FROM local/agent-workcell-base

USER root
RUN mkdir -p /opt/codex-template/packages/standalone/releases \
    && chown -R agent:agent /opt/codex-template

USER agent
WORKDIR /home/agent
ARG CODEX_VERSION=latest
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
        amd64) CODEX_ARCH="x86_64-unknown-linux-musl" ;; \
        arm64) CODEX_ARCH="aarch64-unknown-linux-musl" ;; \
        *) echo "Unsupported architecture for codex: $ARCH" >&2; exit 1 ;; \
    esac && \
    case "$CODEX_VERSION" in \
        latest) CODEX_RELEASE_PATH="latest/download" ;; \
        *) CODEX_RELEASE_PATH="download/rust-v${CODEX_VERSION}" ;; \
    esac && \
    curl --http1.1 --retry 5 --retry-delay 5 --retry-all-errors -fsSL \
        "https://github.com/openai/codex/releases/${CODEX_RELEASE_PATH}/codex-${CODEX_ARCH}.tar.gz" \
        -o /tmp/codex.tar.gz && \
    tar -xzf /tmp/codex.tar.gz -C /tmp && \
    CODEX_RESOLVED_VERSION=$("/tmp/codex-${CODEX_ARCH}" --version | awk '{print $NF}') && \
    [ -n "$CODEX_RESOLVED_VERSION" ] && \
    codex_release_name="${CODEX_RESOLVED_VERSION}-${CODEX_ARCH}" && \
    codex_release_dir="/opt/codex-template/packages/standalone/releases/${codex_release_name}" && \
    mkdir -p "$codex_release_dir" && \
    install -m 0755 "/tmp/codex-${CODEX_ARCH}" "$codex_release_dir/codex" && \
    ln -s "releases/$codex_release_name" /opt/codex-template/packages/standalone/current && \
    rm -f /tmp/codex.tar.gz "/tmp/codex-${CODEX_ARCH}"

USER root
COPY agent-init/codex.sh /opt/workcell-agent-init.sh
RUN chmod +x /opt/workcell-agent-init.sh
ENV WORKCELL_IMAGE_AGENT=codex
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
