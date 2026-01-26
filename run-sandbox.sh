#!/bin/bash
# Run Claude Code in sandboxed Docker environment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create workspace directory if it doesn't exist
mkdir -p workspace

# Build the image if needed
echo "Building Claude Code sandbox..."
docker compose build

# Run the container
echo "Starting Claude Code sandbox..."
echo "Use 'claude --dangerously-skip-permissions' for YOLO mode"
echo ""

docker compose run --rm claude-sandbox
