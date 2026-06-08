# OpenCode image-specific initialization.
. /opt/workcell-context-lib.sh

mkdir -p /home/agent/persist/.config/opencode
WORKCELL_CONTEXT_NATIVE=/home/agent/persist/.config/opencode/AGENTS.md
WORKCELL_CONTEXT_SOURCE=/home/agent/persist/.config/opencode/workcell-context.md
WORKCELL_SKILLS_NATIVE=/home/agent/persist/.config/opencode/skills
WORKCELL_SKILLS_SOURCE=/home/agent/persist/.config/opencode/workcell-skills
WORKCELL_MERGED_SKILLS=/tmp/workcell-merged-skills/opencode
wc_prepare_all
wc_chown_persisted_context
wc_chown_persisted_skills

opencode_root="/opt/opencode"
if [ ! -x "$opencode_root/bin/opencode" ] && [ -x /opt/opencode-template/bin/opencode ]; then
  opencode_root="/opt/opencode-template"
fi
mkdir -p /home/agent/.local/share /home/agent/.local/state /home/agent/.config /home/agent/.local/bin
for opencode_dir in \
    /home/agent/persist/.local/share/opencode \
    /home/agent/persist/.local/state/opencode \
    /home/agent/persist/.config/opencode; do
  mkdir -p "$opencode_dir"
  chown agent:agent "$opencode_dir" 2>/dev/null || true
done
[ -d /home/agent/.opencode ] && [ ! -L /home/agent/.opencode ] && rm -rf /home/agent/.opencode
if [ -x "$opencode_root/bin/opencode" ]; then
  ln -sfn "$opencode_root" /home/agent/.opencode
  ln -sfn "$opencode_root/bin/opencode" /home/agent/.local/bin/opencode
fi
for pair in \
  ".local/share/opencode" \
  ".local/state/opencode" \
  ".config/opencode"; do
  [ -d "/home/agent/$pair" ] && [ ! -L "/home/agent/$pair" ] && rm -rf "/home/agent/$pair"
  ln -sfn "/home/agent/persist/$pair" "/home/agent/$pair"
done
