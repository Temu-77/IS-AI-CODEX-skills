#!/usr/bin/env bash
set -euo pipefail

SKILLS_DEST="${CODEX_HOME:-$HOME/.codex}/skills"

for skill in banner-proposal banner-design-production banner-resizer; do
  if [ -L "$SKILLS_DEST/$skill" ]; then
    rm "$SKILLS_DEST/$skill"
    echo "Removed symlink: $SKILLS_DEST/$skill"
  else
    echo "Skipped $skill; not an installed symlink."
  fi
done

echo "User config is left intact at: ${XDG_CONFIG_HOME:-$HOME/.config}/acrc-codex-skills/.env"
