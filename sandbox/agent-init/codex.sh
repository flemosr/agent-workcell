# Codex image-specific initialization.
mkdir -p /home/agent/persist/.codex
chown agent:agent /home/agent/persist/.codex 2>/dev/null || true
context_path=/home/agent/persist/.codex/AGENTS.md
if [ ! -e "$context_path" ] && [ ! -L "$context_path" ]; then
  cp /opt/agent-context.md "$context_path"
fi
if [ -L "$context_path" ]; then
  chown -h agent:agent "$context_path" 2>/dev/null || true
else
  chown agent:agent "$context_path" 2>/dev/null || true
fi

mkdir -p /home/agent/persist/.codex/skills
seed_default_skill() {
  skill_name="$1"
  skill_path="/home/agent/persist/.codex/skills/$skill_name"
  skill_file="$skill_path/SKILL.md"
  mkdir -p "$skill_path"
  if [ ! -e "$skill_file" ] && [ ! -L "$skill_file" ]; then
    cp "/opt/agent-default-skills/$skill_name/SKILL.md" "$skill_file"
  fi
  chown agent:agent /home/agent/persist/.codex/skills "$skill_path" 2>/dev/null || true
  if [ -L "$skill_file" ]; then
    chown -h agent:agent "$skill_file" 2>/dev/null || true
  else
    chown agent:agent "$skill_file" 2>/dev/null || true
  fi
}
seed_default_skill web
seed_default_skill flutter

[ -d /home/agent/.codex ] && [ ! -L /home/agent/.codex ] && rm -rf /home/agent/.codex
ln -sfn /home/agent/persist/.codex /home/agent/.codex
