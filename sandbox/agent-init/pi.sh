# Pi image-specific initialization.
mkdir -p /home/agent/persist/.pi/agent
ln -sfn /opt/agent-context.md /home/agent/persist/.pi/agent/AGENTS.md
rm -f /home/agent/persist/.pi/agent/agent-context-web.md \
      /home/agent/persist/.pi/agent/agent-context-flutter.md
chown -R agent:agent /home/agent/persist/.pi 2>/dev/null || true
chown -h agent:agent /home/agent/persist/.pi/agent/AGENTS.md 2>/dev/null || true
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
