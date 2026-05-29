# Codex image-specific initialization.
mkdir -p /home/agent/persist/.codex
chown agent:agent /home/agent/persist/.codex 2>/dev/null || true
ln -sfn /opt/agent-context.md /home/agent/persist/.codex/AGENTS.md
rm -f /home/agent/persist/.codex/agent-context-web.md \
      /home/agent/persist/.codex/agent-context-flutter.md
chown -h agent:agent /home/agent/persist/.codex/AGENTS.md 2>/dev/null || true
[ -d /home/agent/.codex ] && [ ! -L /home/agent/.codex ] && rm -rf /home/agent/.codex
ln -sfn /home/agent/persist/.codex /home/agent/.codex
