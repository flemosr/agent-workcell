#!/bin/bash
# Common entrypoint script for Agent Workcell images.
set -e

expected_agents="pi, opencode, codex, or claude"

if [ -z "${AGENT_CLI:-}" ]; then
  echo "Error: AGENT_CLI is required (expected 'pi', 'opencode', 'codex', or 'claude')" >&2
  exit 1
fi
case "$AGENT_CLI" in
  pi|opencode|codex|claude) ;;
  *)
    echo "Error: unknown AGENT_CLI '$AGENT_CLI' (expected 'pi', 'opencode', 'codex', or 'claude')" >&2
    exit 1
    ;;
esac

if [ -z "${WORKCELL_IMAGE_AGENT:-}" ]; then
  echo "Error: WORKCELL_IMAGE_AGENT is not set in this image" >&2
  exit 1
fi
if [ "$WORKCELL_IMAGE_AGENT" != "$AGENT_CLI" ]; then
  echo "Error: image/agent mismatch: image is '$WORKCELL_IMAGE_AGENT' but AGENT_CLI is '$AGENT_CLI'" >&2
  exit 1
fi

# Seed nvm on first run.
if [ ! -d /home/agent/persist/.nvm/versions ]; then
  echo "Initializing nvm in persistent volume..."
  cp -a --no-target-directory /opt/nvm-template /home/agent/persist/.nvm
  chown -R agent:agent /home/agent/persist/.nvm
elif [ -d /opt/nvm-template/versions/node ]; then
  for version_path in /opt/nvm-template/versions/node/*; do
    [ -e "$version_path" ] || continue
    version=$(basename "$version_path")
    dest_path="/home/agent/persist/.nvm/versions/node/$version"
    if [ ! -d "$dest_path" ]; then
      echo "Installing Node version $version into persistent volume..."
      mkdir -p "$dest_path"
      cp -a "$version_path"/. "$dest_path"/
      chown -R agent:agent "$dest_path"
    fi
  done
fi
if [ -d /home/agent/persist/.nvm ] && [ -d /opt/nvm-template ]; then
  for nvm_file in nvm.sh nvm-exec bash_completion install.sh package.json; do
    [ -e "/opt/nvm-template/$nvm_file" ] && cp -a "/opt/nvm-template/$nvm_file" "/home/agent/persist/.nvm/$nvm_file"
  done
  if [ -d /opt/nvm-template/alias/lts ]; then
    mkdir -p /home/agent/persist/.nvm/alias
    rm -rf /home/agent/persist/.nvm/alias/lts
    cp -a /opt/nvm-template/alias/lts /home/agent/persist/.nvm/alias/lts
    chown -R agent:agent /home/agent/persist/.nvm/alias/lts
  fi
fi
[ -d /home/agent/.nvm ] && [ ! -L /home/agent/.nvm ] && rm -rf /home/agent/.nvm
ln -sfn /home/agent/persist/.nvm /home/agent/.nvm
if [ -d /home/agent/.nvm/versions/node ]; then
  latest_node=$(ls -1 /home/agent/.nvm/versions/node | sort -V | tail -1)
  [ -n "$latest_node" ] && ln -sfn "/home/agent/.nvm/versions/node/$latest_node" /home/agent/.nvm/current
fi

# Seed Rust toolchains on first run.
if [ ! -d /home/agent/persist/.rustup/toolchains ]; then
  echo "Initializing Rust toolchain in persistent volume..."
  cp -a --no-target-directory /opt/rustup-template /home/agent/persist/.rustup
  cp -a --no-target-directory /opt/cargo-template /home/agent/persist/.cargo
  chown -R agent:agent /home/agent/persist/.rustup /home/agent/persist/.cargo
fi
for d in .rustup .cargo; do
  [ -d "/home/agent/$d" ] && [ ! -L "/home/agent/$d" ] && rm -rf "/home/agent/$d"
  ln -sfn "/home/agent/persist/$d" "/home/agent/$d"
done

# Use image-baked Flutter SDK.
flutter_sdk_root="/opt/flutter-sdk"
if [ ! -x "$flutter_sdk_root/bin/flutter" ] && [ -x /opt/flutter-sdk-template/bin/flutter ]; then
  flutter_sdk_root="/opt/flutter-sdk-template"
fi
[ -d /home/agent/.flutter-sdk ] && [ ! -L /home/agent/.flutter-sdk ] && rm -rf /home/agent/.flutter-sdk
if [ -x "$flutter_sdk_root/bin/flutter" ]; then
  ln -sfn "$flutter_sdk_root" /home/agent/.flutter-sdk
  export WORKCELL_REAL_FLUTTER="$flutter_sdk_root/bin/flutter"
  export WORKCELL_REAL_DART="$flutter_sdk_root/bin/dart"
fi

mkdir -p /home/agent/persist/.pub-cache
if [ -d /opt/pub-cache-template ]; then
  cp -an /opt/pub-cache-template/. /home/agent/persist/.pub-cache/ 2>/dev/null || true
fi
chown agent:agent /home/agent/persist/.pub-cache 2>/dev/null || true
[ -d /home/agent/.pub-cache ] && [ ! -L /home/agent/.pub-cache ] && rm -rf /home/agent/.pub-cache
ln -sfn /home/agent/persist/.pub-cache /home/agent/.pub-cache
if [ -x /opt/pub-cache-template/bin/protoc-gen-dart ]; then
  ln -sfn /opt/pub-cache-template/bin/protoc-gen-dart /home/agent/.local/bin/protoc-gen-dart
elif [ -x /home/agent/.pub-cache/bin/protoc-gen-dart ]; then
  ln -sfn /home/agent/.pub-cache/bin/protoc-gen-dart /home/agent/.local/bin/protoc-gen-dart
fi

mkdir -p /home/agent/persist/.flutter-config
chown agent:agent /home/agent/persist/.flutter-config 2>/dev/null || true
[ -d /home/agent/.flutter ] && [ ! -L /home/agent/.flutter ] && rm -rf /home/agent/.flutter
ln -sfn /home/agent/persist/.flutter-config /home/agent/.flutter

# Shared GPG volume is mounted at /home/agent/persist/.gnupg by the host runner.
mkdir -p /home/agent/persist/.gnupg
chmod 700 /home/agent/persist/.gnupg 2>/dev/null || true
chown agent:agent /home/agent/persist/.gnupg 2>/dev/null || true
[ -d /home/agent/.gnupg ] && [ ! -L /home/agent/.gnupg ] && rm -rf /home/agent/.gnupg
ln -sfn /home/agent/persist/.gnupg /home/agent/.gnupg

export PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:$flutter_sdk_root/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:${PATH}"

# Run agent-specific persistence and binary setup.
if [ ! -x /opt/workcell-agent-init.sh ]; then
  echo "Error: missing agent init script for '$WORKCELL_IMAGE_AGENT'" >&2
  exit 1
fi
. /opt/workcell-agent-init.sh

# GPG commit signing setup.
if [ "$GPG_SIGNING" = "true" ] && [ -n "$GIT_AUTHOR_NAME" ] && [ -n "$GIT_AUTHOR_EMAIL" ]; then
  existing_email=$(runuser -u agent -- gpg --list-keys --with-colons 2>/dev/null | grep '^uid' | head -1 | cut -d: -f10 | grep -oP '<\K[^>]+' || true)
  if [ -n "$existing_email" ] && [ "$existing_email" != "$GIT_AUTHOR_EMAIL" ]; then
    echo "ERROR: GPG key identity mismatch!" >&2
    echo "  Existing key: $existing_email" >&2
    echo "  Config email:  $GIT_AUTHOR_EMAIL" >&2
    exit 1
  fi
  if ! runuser -u agent -- gpg --list-keys "$GIT_AUTHOR_EMAIL" &>/dev/null; then
    echo "GPG_SIGNING is enabled but no key was found for $GIT_AUTHOR_NAME <$GIT_AUTHOR_EMAIL>." >&2
    echo "Run 'workcell gpg-new' on the host to create one." >&2
    exit 1
  fi
  key_id=$(runuser -u agent -- gpg --list-keys --keyid-format long "$GIT_AUTHOR_EMAIL" 2>/dev/null | grep -oP '(?<=ed25519/)[A-F0-9]+' | head -1 || true)
  if [ -n "$key_id" ]; then
    runuser -u agent -- git config --global user.signingKey "$key_id"
    runuser -u agent -- git config --global commit.gpgSign true
    runuser -u agent -- git config --global tag.gpgSign true
  fi
fi

if [[ "$ENABLE_FIREWALL" == "1" ]]; then
  if [[ "$(id -u)" != "0" ]]; then
    echo "Error: Firewall requested but not running as root. Container must run as root to configure iptables." >&2
    exit 1
  fi
  echo "Configuring firewall..."
  /opt/init-firewall.sh
fi

echo

if [[ "$(id -u)" == "0" ]]; then
  exec runuser -m -u agent -- \
    env HOME=/home/agent USER=agent LOGNAME=agent PATH="$PATH" "$AGENT_CLI" "$@"
else
  exec "$AGENT_CLI" "$@"
fi
