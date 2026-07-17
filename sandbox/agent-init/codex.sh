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

codex_packages="/home/agent/persist/.codex/packages"
codex_standalone="$codex_packages/standalone"
codex_template="/opt/codex-template/packages/standalone"
codex_executable="$codex_standalone/current/bin/codex"
if [ ! -x "$codex_executable" ]; then
  codex_executable="$codex_standalone/current/codex"
fi
if [ ! -x "$codex_executable" ]; then
  if [ -e "$codex_standalone" ] || [ -L "$codex_standalone" ]; then
    echo "Error: persisted Codex standalone install exists but has no executable at its current release" >&2
    return 1
  fi
  if [ ! -x "$codex_template/current/bin/codex" ] && [ ! -x "$codex_template/current/codex" ]; then
    echo "Error: no Codex standalone template is available to initialize the persistent install" >&2
    return 1
  fi
  echo "Initializing Codex in persistent volume..."
  mkdir -p "$codex_packages"
  cp -a "$codex_template" "$codex_packages"/
  chown -R agent:agent "$codex_standalone"
  codex_executable="$codex_standalone/current/bin/codex"
  if [ ! -x "$codex_executable" ]; then
    codex_executable="$codex_standalone/current/codex"
  fi
fi

[ -d /home/agent/.codex ] && [ ! -L /home/agent/.codex ] && rm -rf /home/agent/.codex
ln -sfn /home/agent/persist/.codex /home/agent/.codex
[ -d /home/agent/.agents ] && [ ! -L /home/agent/.agents ] && rm -rf /home/agent/.agents
ln -sfn /home/agent/persist/.agents /home/agent/.agents
mkdir -p /home/agent/.local/bin
ln -sfn "$codex_executable" /home/agent/.local/bin/codex
