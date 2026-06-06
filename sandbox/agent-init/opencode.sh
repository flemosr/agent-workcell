# OpenCode image-specific initialization.
mkdir -p /home/agent/persist/.config/opencode
context_path=/home/agent/persist/.config/opencode/AGENTS.md
if [ ! -e "$context_path" ] && [ ! -L "$context_path" ]; then
  cp /opt/agent-context.md "$context_path"
fi
rm -f /home/agent/persist/.config/opencode/agent-context-web.md \
      /home/agent/persist/.config/opencode/agent-context-flutter.md
chown agent:agent /home/agent/persist/.config/opencode 2>/dev/null || true
if [ -L "$context_path" ]; then
  chown -h agent:agent "$context_path" 2>/dev/null || true
else
  chown agent:agent "$context_path" 2>/dev/null || true
fi

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
