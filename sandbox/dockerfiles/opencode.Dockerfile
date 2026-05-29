FROM local/agent-workcell-base

USER root
RUN mkdir -p /opt/opencode-template && chown agent:agent /opt/opencode-template

USER agent
WORKDIR /home/agent
ARG OPENCODE_VERSION=1.15.0
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
        amd64) OPENCODE_ARCH="x64" ;; \
        arm64) OPENCODE_ARCH="arm64" ;; \
        *) echo "Unsupported architecture for opencode: $ARCH" >&2; exit 1 ;; \
    esac && \
    curl --http1.1 --retry 5 --retry-delay 5 --retry-all-errors -fsSL \
        "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${OPENCODE_ARCH}.tar.gz" \
        -o /tmp/opencode.tar.gz && \
    tar -xzf /tmp/opencode.tar.gz -C /tmp opencode && \
    mkdir -p /opt/opencode-template/bin && \
    install -m 0755 /tmp/opencode /opt/opencode-template/bin/opencode && \
    ln -sf /opt/opencode-template /home/agent/.opencode && \
    ln -sf /home/agent/.opencode/bin/opencode /home/agent/.local/bin/opencode && \
    rm -f /tmp/opencode.tar.gz /tmp/opencode

USER root
RUN ln -sfn /opt/opencode-template /opt/opencode \
    && ln -sfn /opt/opencode/bin/opencode /home/agent/.local/bin/opencode \
    && chown -h agent:agent /opt/opencode /home/agent/.local/bin/opencode
COPY agent-init/opencode.sh /opt/workcell-agent-init.sh
RUN chmod +x /opt/workcell-agent-init.sh
ENV WORKCELL_IMAGE_AGENT=opencode
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
