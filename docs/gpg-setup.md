# GPG Setup

The workcell can generate and persist a sandbox-specific GPG key so commits made inside the
container can show as verified on GitHub.

## Setup

Create your local config file if it does not exist:

```bash
cp config.template.sh config.sh
```

Set the Git identity and enable signing in `config.sh`:

```bash
GIT_AUTHOR_NAME="Workcell Agent Name"
GIT_AUTHOR_EMAIL="agent@example.local"
GPG_SIGNING=true
```

On first launch, the workcell generates a passphrase-less ed25519 GPG key and prints the public
key. Add that public key to GitHub at **Settings > SSH and GPG keys > New GPG key** if you want
commits from the workcell to show as verified.

The key is persisted in the Docker volume under `~/.gnupg`, so it survives container restarts and
image rebuilds.

## Generate a Key Explicitly

You can generate the key without launching an agent:

```bash
workcell gpg-new
```

This reads `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` from `config.sh`.

## Manage Keys

```bash
# Export the workcell GPG key
workcell gpg-export --file my-key-backup.asc

# Import a previously exported key
workcell gpg-import --file my-key-backup.asc

# Generate a revocation certificate
workcell gpg-revoke --file revoke.asc

# Erase all GPG keys from the workcell
workcell gpg-erase
```

`gpg-erase` permanently deletes all GPG keys from the sandbox volume. If `GPG_SIGNING=true` remains
enabled, a new key is generated on the next launch.

## Backup Guidance

Back up the key if you want verified commits to continue using the same GPG identity after moving
to a new machine or recreating the Docker volume:

```bash
workcell gpg-export --file workcell-gpg-backup.asc
```

Treat exported keys and volume backups as sensitive. The key is passphrase-less so agents can sign
commits non-interactively.

## Troubleshooting

- `GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL must be set`: add both values to `config.sh`.
- Commits are not verified on GitHub: confirm the public key printed by `workcell gpg-new` or first
  launch was added to the same GitHub account associated with the commit email.
- A new key was generated unexpectedly: check whether the `agent-workcell` Docker volume was
  removed or replaced.
- Need to rotate the key: run `workcell gpg-revoke --file revoke.asc`, add the revocation
  certificate where needed, run `workcell gpg-erase`, and generate a new key with
  `workcell gpg-new`.
