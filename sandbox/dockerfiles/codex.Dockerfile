FROM local/agent-workcell-base

USER agent
WORKDIR /home/agent
ARG CODEX_VERSION=latest
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
        amd64) CODEX_ARCH="x86_64-unknown-linux-musl" ;; \
        arm64) CODEX_ARCH="aarch64-unknown-linux-musl" ;; \
        *) echo "Unsupported architecture for codex: $ARCH" >&2; exit 1 ;; \
    esac && \
    curl --http1.1 --retry 5 --retry-delay 5 --retry-all-errors -fsSL \
        "https://github.com/openai/codex/releases/latest/download/codex-${CODEX_ARCH}.tar.gz" \
        -o /tmp/codex.tar.gz && \
    tar -xzf /tmp/codex.tar.gz -C /tmp && \
    install -m 0755 "/tmp/codex-${CODEX_ARCH}" /home/agent/.local/bin/codex && \
    rm -f /tmp/codex.tar.gz "/tmp/codex-${CODEX_ARCH}"
RUN mkdir -p /home/agent/persist/.codex \
    && ln -sf /home/agent/persist/.codex /home/agent/.codex

USER root
COPY agent-init/codex.sh /opt/workcell-agent-init.sh
RUN chmod +x /opt/workcell-agent-init.sh
ENV WORKCELL_IMAGE_AGENT=codex
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
