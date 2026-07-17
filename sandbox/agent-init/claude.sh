# Claude Code image-specific initialization.
. /opt/workcell-context-lib.sh

mkdir -p /home/agent/persist/.claude
WORKCELL_CONTEXT_NATIVE=/home/agent/persist/.claude/CLAUDE.md
WORKCELL_CONTEXT_SOURCE=/home/agent/persist/.claude/workcell-context.md
WORKCELL_SKILLS_NATIVE=/home/agent/persist/.claude/skills
WORKCELL_SKILLS_SOURCE=/home/agent/persist/.claude/workcell-skills
WORKCELL_MERGED_SKILLS=/tmp/workcell-merged-skills/claude
wc_prepare_all
wc_chown_persisted_context
wc_chown_persisted_skills

[ -d /home/agent/.claude ] && [ ! -L /home/agent/.claude ] && rm -rf /home/agent/.claude
ln -sfn /home/agent/persist/.claude /home/agent/.claude
[ -e /home/agent/persist/.claude.json ] || printf '{}\n' > /home/agent/persist/.claude.json
chown agent:agent /home/agent/persist/.claude.json 2>/dev/null || true
ln -sfn /home/agent/persist/.claude.json /home/agent/.claude.json

claude_install="/home/agent/persist/.local/share/claude"
claude_template="/opt/claude-code"
claude_selector="$claude_install/.workcell-current-version"

claude_latest_version() {
  find "$1/versions" -mindepth 1 -maxdepth 1 -type f -perm -u+x -printf '%f\n' 2>/dev/null \
    | sort -V \
    | tail -1
}

persisted_claude_version=$(claude_latest_version "$claude_install")
if [ -z "$persisted_claude_version" ]; then
  template_claude_version=$(claude_latest_version "$claude_template")
  if [ -z "$template_claude_version" ]; then
    claude_template="/opt/claude-versions-template"
    template_claude_version=$(claude_latest_version "$claude_template")
  fi
  if [ -z "$template_claude_version" ]; then
    echo "Error: no Claude Code executable is available to initialize the persistent install" >&2
    return 1
  fi
  echo "Initializing Claude Code in persistent volume..."
  mkdir -p "$claude_install"
  cp -an "$claude_template"/. "$claude_install"/
  chown -R agent:agent "$claude_install"
  persisted_claude_version=$(claude_latest_version "$claude_install")
  if [ -z "$persisted_claude_version" ]; then
    echo "Error: persistent Claude Code install has no executable version after initialization" >&2
    return 1
  fi
fi

selected_claude_version=""
if [ -f "$claude_selector" ]; then
  IFS= read -r selected_claude_version < "$claude_selector" || true
  case "$selected_claude_version" in
    ""|*/*) selected_claude_version="" ;;
  esac
fi
if [ -z "$selected_claude_version" ] || [ ! -x "$claude_install/versions/$selected_claude_version" ]; then
  selected_claude_version="$persisted_claude_version"
  printf '%s\n' "$selected_claude_version" > "$claude_selector"
  chown agent:agent "$claude_selector" 2>/dev/null || true
fi
claude_executable="$claude_install/versions/$selected_claude_version"

mkdir -p /home/agent/.local/share /home/agent/.local/bin
[ -d /home/agent/.local/share/claude ] && [ ! -L /home/agent/.local/share/claude ] && rm -rf /home/agent/.local/share/claude
ln -sfn "$claude_install" /home/agent/.local/share/claude
ln -sfn "$claude_executable" /home/agent/.local/bin/claude
