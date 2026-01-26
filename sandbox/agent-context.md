# Sandboxed Environment

You are running inside a Docker container sandbox. Keep the following in mind:

## Host Services

Use `host.docker.internal` instead of `localhost` to connect to services running on the host machine.

## Firewall Status

To check if network restrictions are active:

```bash
iptables -L OUTPUT -n 2>/dev/null | grep -q "DROP" && echo "Firewall ACTIVE" || echo "Firewall INACTIVE"
```

## Allowed Domains (when firewalled)

If the firewall is active, only the following domains are accessible:

**Anthropic**
- api.anthropic.com
- claude.ai
- statsig.anthropic.com
- sentry.io

**JavaScript/TypeScript**
- registry.npmjs.org
- npmjs.com
- yarnpkg.com
- registry.yarnpkg.com
- nodejs.org

**Rust**
- crates.io
- static.crates.io
- index.crates.io
- doc.rust-lang.org
- docs.rs
- static.rust-lang.org

**GitHub**
- github.com
- api.github.com
- raw.githubusercontent.com
- objects.githubusercontent.com

**Other**
- storage.googleapis.com

All other external network access is blocked when firewalled.
