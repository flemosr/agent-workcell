# Pi image-specific initialization.
mkdir -p /home/agent/persist/.pi/agent
context_path=/home/agent/persist/.pi/agent/AGENTS.md
if [ ! -e "$context_path" ] && [ ! -L "$context_path" ]; then
  cp /opt/agent-context.md "$context_path"
fi
chown agent:agent /home/agent/persist/.pi /home/agent/persist/.pi/agent 2>/dev/null || true
if [ -L "$context_path" ]; then
  chown -h agent:agent "$context_path" 2>/dev/null || true
else
  chown agent:agent "$context_path" 2>/dev/null || true
fi

mkdir -p /home/agent/persist/.pi/agent/skills
seed_default_skill() {
  skill_name="$1"
  skill_path="/home/agent/persist/.pi/agent/skills/$skill_name"
  skill_file="$skill_path/SKILL.md"
  mkdir -p "$skill_path"
  if [ ! -e "$skill_file" ] && [ ! -L "$skill_file" ]; then
    cp "/opt/agent-default-skills/$skill_name/SKILL.md" "$skill_file"
  fi
  chown agent:agent /home/agent/persist/.pi/agent/skills "$skill_path" 2>/dev/null || true
  if [ -L "$skill_file" ]; then
    chown -h agent:agent "$skill_file" 2>/dev/null || true
  else
    chown agent:agent "$skill_file" 2>/dev/null || true
  fi
}
seed_default_skill web
seed_default_skill flutter

[ -d /home/agent/.pi ] && [ ! -L /home/agent/.pi ] && rm -rf /home/agent/.pi
ln -sfn /home/agent/persist/.pi /home/agent/.pi
export PI_CODING_AGENT_DIR="${PI_CODING_AGENT_DIR:-/home/agent/persist/.pi/agent}"

pi_self_prefix="/home/agent/persist/.pi/agent/self"
pi_image_prefix="/opt/pi"
if [ ! -x "$pi_self_prefix/bin/pi" ] && [ -d "$pi_image_prefix" ]; then
  rm -rf "$pi_self_prefix"
  mkdir -p "$pi_self_prefix"
  cp -a "$pi_image_prefix"/. "$pi_self_prefix"/
  chown -R agent:agent "$pi_self_prefix" 2>/dev/null || true
fi
[ -x "$pi_self_prefix/bin/pi" ] && ln -sfn "$pi_self_prefix/bin/pi" /home/agent/.local/bin/pi
