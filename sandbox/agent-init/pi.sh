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

pi_agent_root="/home/agent/persist/.pi/agent"
pi_install="$pi_agent_root/install"
pi_image_root="/opt/pi"

pi_validate_install() {
  node - "$1" /home/agent/.local/bin/pi <<'JS'
const fs = require("node:fs"), path = require("node:path");
const [root, entrypoint] = process.argv.slice(2);
try {
  const stat = fs.lstatSync(root);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error("install root must be a directory, not a symlink");
  const marker = JSON.parse(fs.readFileSync(path.join(root, "managed-install.json"), "utf8"));
  if (marker?.kind !== "pi-managed-install" || marker.schemaVersion !== 1 || marker.layout !== "releases-v1"
      || marker.entrypoint?.type !== "symlink" || marker.entrypoint.path !== entrypoint) {
    throw new Error("managed-install.json has an unsupported schema/layout or entrypoint");
  }
  const selector = fs.readFileSync(path.join(root, "current-version"), "utf8");
  const version = selector.endsWith("\n") ? selector.slice(0, -1) : "";
  if (!version || /[^0-9A-Za-z._+-]/.test(version) || version === "." || version === "..") {
    throw new Error("current-version must contain one safe release name followed by a newline");
  }
  const releases = path.join(fs.realpathSync(root), "releases");
  const release = fs.realpathSync(path.join(releases, version));
  const executable = fs.realpathSync(path.join(release, "node_modules", ".bin", "pi"));
  if (!release.startsWith(releases + path.sep) || !executable.startsWith(release + path.sep)) {
    throw new Error("selected executable must stay inside its managed release");
  }
  if (!fs.statSync(executable).isFile()) throw new Error("selected executable must be a file");
  fs.accessSync(executable, fs.constants.X_OK);
} catch (error) {
  console.error(`Error: invalid managed Pi install at ${root}: ${error.message}`);
  process.exit(1);
}
JS
}

if [ ! -e "$pi_install" ] && [ ! -L "$pi_install" ]; then
  if [ ! -d "$pi_image_root/install" ] || [ ! -f "$pi_image_root/bin/pi" ] || [ ! -x "$pi_image_root/bin/pi" ]; then
    echo "Error: no complete managed Pi template is available to initialize the persistent install" >&2
    return 1
  fi
  echo "Initializing managed Pi in persistent volume..."
  (
    pi_seed=$(mktemp -d "$pi_agent_root/.pi-install.XXXXXX") || exit 1
    trap 'rm -rf "$pi_seed"' 0
    trap 'exit 1' HUP INT TERM
    cp -a "$pi_image_root/install" "$pi_seed/install" || exit 1
    pi_validate_install "$pi_seed/install" || exit 1
    chown -R agent:agent "$pi_seed/install" || exit 1
    # GNU mv's no-clobber/no-target-directory flags prevent competing seeds
    # from overwriting an install or nesting the copy inside an existing root.
    mv -Tn "$pi_seed/install" "$pi_install" || exit 1
    if [ -e "$pi_seed/install" ]; then
      echo "Error: another initializer published the managed Pi install; retry startup" >&2
      exit 1
    fi
  ) || return 1
fi
pi_validate_install "$pi_install" || return 1

if [ -L "$pi_agent_root/bin" ]; then
  echo "Error: persisted Pi bin directory must not be a symlink" >&2
  return 1
fi
mkdir -p "$pi_agent_root/bin" /home/agent/.local/bin || return 1
chown agent:agent "$pi_agent_root" "$pi_agent_root/bin" || return 1
if [ ! -f "$pi_agent_root/bin/pi" ] || [ ! -x "$pi_agent_root/bin/pi" ]; then
  if [ ! -f "$pi_image_root/bin/pi" ] || [ ! -x "$pi_image_root/bin/pi" ]; then
    echo "Error: no managed Pi template launcher is available to restore bin/pi" >&2
    return 1
  fi
  (
    pi_launcher=$(mktemp "$pi_agent_root/bin/.pi-launcher.XXXXXX") || exit 1
    trap 'rm -f "$pi_launcher"' 0
    trap 'exit 1' HUP INT TERM
    cp "$pi_image_root/bin/pi" "$pi_launcher" || exit 1
    chmod 0755 "$pi_launcher" || exit 1
    chown agent:agent "$pi_launcher" || exit 1
    mv -Tf "$pi_launcher" "$pi_agent_root/bin/pi" || exit 1
  ) || return 1
fi
ln -sfnT "$pi_agent_root/bin/pi" /home/agent/.local/bin/pi
