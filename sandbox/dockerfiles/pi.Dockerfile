FROM local/agent-workcell-base

USER root
RUN mkdir -p /opt/pi-template && chown agent:agent /opt/pi-template

USER agent
WORKDIR /home/agent
ENV PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:/opt/flutter-sdk/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
RUN npm install -g --ignore-scripts --min-release-age=0 \
        --prefix /opt/pi-template \
        --no-fund --no-audit --loglevel=error --progress=false \
        @earendil-works/pi-coding-agent && \
    ln -sf /opt/pi-template/bin/pi /home/agent/.local/bin/pi

USER root
RUN ln -sfn /opt/pi-template /opt/pi \
    && ln -sfn /opt/pi/bin/pi /home/agent/.local/bin/pi \
    && chown -h agent:agent /opt/pi /home/agent/.local/bin/pi
COPY agent-init/pi.sh /opt/workcell-agent-init.sh
RUN chmod +x /opt/workcell-agent-init.sh
ENV WORKCELL_IMAGE_AGENT=pi
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
