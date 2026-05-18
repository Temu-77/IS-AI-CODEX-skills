#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SRC="$ROOT_DIR/skills"
SKILLS_DEST="${CODEX_HOME:-$HOME/.codex}/skills"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/acrc-codex-skills"

mkdir -p "$SKILLS_DEST" "$CONFIG_DIR"

for skill in banner-proposal banner-design-production banner-resizer; do
  if [ ! -d "$SKILLS_SRC/$skill" ]; then
    echo "Missing skill folder: $SKILLS_SRC/$skill" >&2
    exit 1
  fi
  ln -sfn "$SKILLS_SRC/$skill" "$SKILLS_DEST/$skill"
  echo "Installed $skill -> $SKILLS_DEST/$skill"
done

if [ ! -f "$CONFIG_DIR/.env" ]; then
  cp "$ROOT_DIR/.env.example" "$CONFIG_DIR/.env"
  chmod 600 "$CONFIG_DIR/.env"
  echo "Created config template: $CONFIG_DIR/.env"
else
  chmod 600 "$CONFIG_DIR/.env" || true
  echo "Config already exists: $CONFIG_DIR/.env"
fi

echo
echo "Restart VS Code/Codex, then invoke: \$banner-proposal, \$banner-design-production, or \$banner-resizer"
