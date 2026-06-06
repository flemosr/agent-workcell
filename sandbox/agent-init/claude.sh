# Claude Code image-specific initialization.
mkdir -p /home/agent/persist/.claude
context_path=/home/agent/persist/.claude/CLAUDE.md
if [ ! -e "$context_path" ] && [ ! -L "$context_path" ]; then
  cp /opt/agent-context.md "$context_path"
fi
chown agent:agent /home/agent/persist/.claude 2>/dev/null || true
if [ -L "$context_path" ]; then
  chown -h agent:agent "$context_path" 2>/dev/null || true
else
  chown agent:agent "$context_path" 2>/dev/null || true
fi

mkdir -p /home/agent/persist/.claude/skills
seed_default_skill() {
  skill_name="$1"
  skill_path="/home/agent/persist/.claude/skills/$skill_name"
  skill_file="$skill_path/SKILL.md"
  mkdir -p "$skill_path"
  if [ ! -e "$skill_file" ] && [ ! -L "$skill_file" ]; then
    cp "/opt/agent-default-skills/$skill_name/SKILL.md" "$skill_file"
  fi
  chown agent:agent /home/agent/persist/.claude/skills "$skill_path" 2>/dev/null || true
  if [ -L "$skill_file" ]; then
    chown -h agent:agent "$skill_file" 2>/dev/null || true
  else
    chown agent:agent "$skill_file" 2>/dev/null || true
  fi
}
seed_default_skill chrome-integration
seed_default_skill flutter-integration


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
