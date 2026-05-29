# Claude Code image-specific initialization.
mkdir -p /home/agent/persist/.claude
ln -sfn /opt/agent-context.md /home/agent/persist/.claude/CLAUDE.md
rm -f /home/agent/persist/.claude/agent-context-web.md \
      /home/agent/persist/.claude/agent-context-flutter.md
chown agent:agent /home/agent/persist/.claude 2>/dev/null || true
chown -h agent:agent /home/agent/persist/.claude/CLAUDE.md 2>/dev/null || true

[ -d /home/agent/.claude ] && [ ! -L /home/agent/.claude ] && rm -rf /home/agent/.claude
ln -sfn /home/agent/persist/.claude /home/agent/.claude
[ -e /home/agent/persist/.claude.json ] || printf '{}\n' > /home/agent/persist/.claude.json
chown agent:agent /home/agent/persist/.claude.json 2>/dev/null || true
ln -sfn /home/agent/persist/.claude.json /home/agent/.claude.json

claude_versions_root="/opt/claude-code"
if [ ! -d "$claude_versions_root/versions" ] && [ -d /opt/claude-versions-template/versions ]; then
  claude_versions_root="/opt/claude-versions-template"
fi
mkdir -p /home/agent/.local/share /home/agent/.local/bin
[ -d /home/agent/.local/share/claude ] && [ ! -L /home/agent/.local/share/claude ] && rm -rf /home/agent/.local/share/claude
if [ -d "$claude_versions_root/versions" ]; then
  ln -sfn "$claude_versions_root" /home/agent/.local/share/claude
  latest_claude=$(ls -1 "$claude_versions_root/versions" | sort -V | tail -1)
  [ -n "$latest_claude" ] && ln -sfn "$claude_versions_root/versions/$latest_claude" /home/agent/.local/bin/claude
fi
