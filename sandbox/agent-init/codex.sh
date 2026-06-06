# Codex image-specific initialization.
mkdir -p /home/agent/persist/.codex
chown agent:agent /home/agent/persist/.codex 2>/dev/null || true
context_path=/home/agent/persist/.codex/AGENTS.md
if [ ! -e "$context_path" ] && [ ! -L "$context_path" ]; then
  cp /opt/agent-context.md "$context_path"
fi
rm -f /home/agent/persist/.codex/agent-context-web.md \
      /home/agent/persist/.codex/agent-context-flutter.md
if [ -L "$context_path" ]; then
  chown -h agent:agent "$context_path" 2>/dev/null || true
else
  chown agent:agent "$context_path" 2>/dev/null || true
fi
[ -d /home/agent/.codex ] && [ ! -L /home/agent/.codex ] && rm -rf /home/agent/.codex
ln -sfn /home/agent/persist/.codex /home/agent/.codex
