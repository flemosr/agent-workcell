# Pi image-specific initialization.
. /opt/workcell-context-lib.sh

mkdir -p /home/agent/persist/.pi/agent
WORKCELL_CONTEXT_NATIVE=/home/agent/persist/.pi/agent/AGENTS.md
WORKCELL_CONTEXT_SOURCE=/home/agent/persist/.pi/agent/workcell-context.md
WORKCELL_SKILLS_NATIVE=/home/agent/persist/.pi/agent/skills
WORKCELL_SKILLS_SOURCE=/home/agent/persist/.pi/agent/workcell-skills
WORKCELL_MERGED_SKILLS=/tmp/workcell-merged-skills/pi
wc_prepare_all
wc_chown_persisted_context
wc_chown_persisted_skills

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
