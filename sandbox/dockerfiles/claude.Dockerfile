FROM local/agent-workcell-base

USER root
RUN mkdir -p /opt/claude-versions-template && chown agent:agent /opt/claude-versions-template

USER agent
WORKDIR /home/agent
ENV PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:/opt/flutter-sdk/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
RUN mkdir -p /home/agent/persist/.claude /home/agent/.local/share \
    && echo '{}' > /home/agent/persist/.claude.json \
    && ln -sf /opt/claude-versions-template /home/agent/.local/share/claude \
    && ln -sf /home/agent/persist/.claude /home/agent/.claude \
    && ln -sf /home/agent/persist/.claude.json /home/agent/.claude.json
RUN curl -fsSL https://claude.ai/install.sh | bash

USER root
RUN ln -sfn /opt/claude-versions-template /opt/claude-code \
    && chown -h agent:agent /opt/claude-code
COPY agent-init/claude.sh /opt/workcell-agent-init.sh
RUN chmod +x /opt/workcell-agent-init.sh
ENV WORKCELL_IMAGE_AGENT=claude
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
