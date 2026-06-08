# Codex image-specific initialization.
. /opt/workcell-context-lib.sh

mkdir -p /home/agent/persist/.codex /home/agent/persist/.agents
chown agent:agent /home/agent/persist/.codex /home/agent/persist/.agents 2>/dev/null || true
WORKCELL_CONTEXT_NATIVE=/home/agent/persist/.codex/AGENTS.md
WORKCELL_CONTEXT_SOURCE=/home/agent/persist/.codex/workcell-context.md
WORKCELL_SKILLS_NATIVE=/home/agent/persist/.agents/skills
WORKCELL_SKILLS_SOURCE=/home/agent/persist/.agents/workcell-skills
WORKCELL_MERGED_SKILLS=/tmp/workcell-merged-skills/codex
wc_prepare_all
wc_chown_persisted_context
wc_chown_persisted_skills

[ -d /home/agent/.codex ] && [ ! -L /home/agent/.codex ] && rm -rf /home/agent/.codex
ln -sfn /home/agent/persist/.codex /home/agent/.codex
[ -d /home/agent/.agents ] && [ ! -L /home/agent/.agents ] && rm -rf /home/agent/.agents
ln -sfn /home/agent/persist/.agents /home/agent/.agents
