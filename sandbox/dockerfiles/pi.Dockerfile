FROM local/agent-workcell-base

USER root
RUN mkdir -p /opt/pi-template && chown agent:agent /opt/pi-template

USER agent
WORKDIR /home/agent
ENV PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:/opt/flutter-sdk/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Fresh managed template; Node/npm stay owned by the base image.
RUN ! command -v pi >/dev/null 2>&1 && \
    node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 19)) throw new Error("The base image must supply Node >=22.19");' && \
    command -v npm >/dev/null && \
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL \
        --connect-timeout 15 --max-time 120 --retry 3 --retry-all-errors \
        https://pi.dev/install.sh -o /tmp/pi-install.sh && \
    PI_CODING_AGENT_DIR=/opt/pi-template NPM_CONFIG_CACHE=/tmp/pi-npm-cache \
        PI_TELEMETRY=0 PI_OFFLINE=1 TERM=dumb sh /tmp/pi-install.sh && \
    node -e '\
        const fs = require("node:fs"), assert = require("node:assert/strict"); \
        const root = "/opt/pi-template"; \
        const marker = JSON.parse(fs.readFileSync(root + "/install/managed-install.json", "utf8")); \
        assert.equal(marker.kind, "pi-managed-install"); \
        assert.equal(marker.schemaVersion, 1); \
        assert.equal(marker.layout, "releases-v1"); \
        assert.equal(marker.entrypoint?.type, "symlink"); \
        assert.equal(marker.entrypoint.path, "/home/agent/.local/bin/pi"); \
        const version = fs.readFileSync(root + "/install/current-version", "utf8").trim(); \
        const actual = require("node:child_process").execFileSync(root + "/bin/pi", ["--version"], \
            {env: {...process.env, PI_CODING_AGENT_DIR: root, PI_TELEMETRY: "0", PI_OFFLINE: "1"}, encoding: "utf8"}).trim(); \
        assert.equal(actual, version); \
        console.log("Verified managed Pi " + version);' && \
    rm -f /tmp/pi-install.sh && rm -rf /tmp/pi-npm-cache

USER root
RUN ln -sfn /opt/pi-template /opt/pi \
    && ln -sfn /opt/pi/bin/pi /home/agent/.local/bin/pi \
    && chown -h agent:agent /opt/pi /home/agent/.local/bin/pi
COPY agent-init/pi.sh /opt/workcell-agent-init.sh
COPY pi-extensions/compact-session.ts /opt/workcell/pi-extensions/compact-session.ts
COPY pi-extensions/compact-session-runtime.ts /opt/workcell/pi-extensions/compact-session-runtime.ts
COPY pi-extensions/terminal-notify.ts /opt/workcell/pi-extensions/terminal-notify.ts
RUN chmod +x /opt/workcell-agent-init.sh
ENV WORKCELL_IMAGE_AGENT=pi
ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
