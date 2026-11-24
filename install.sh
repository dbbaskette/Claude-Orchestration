#!/usr/bin/env bash
# Make orchestrator mode available in every project by symlinking it into ~/.claude.
# Edits to the files in this repo then apply everywhere. Re-run safely; existing
# non-symlink files are left alone and reported.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/.claude"
DEST="${HOME}/.claude"

link() {
  local from="$1" to="$2"
  mkdir -p "$(dirname "$to")"
  if [ -L "$to" ]; then
    ln -sfn "$from" "$to"
    echo "relinked  $to"
  elif [ -e "$to" ]; then
    echo "SKIPPED   $to (exists and is not a symlink; move it aside first)"
  else
    ln -s "$from" "$to"
    echo "linked    $to"
  fi
}

link "$SRC/orchestration.json"          "$DEST/orchestration.json"
link "$SRC/skills/orchestrate"          "$DEST/skills/orchestrate"
for agent in "$SRC"/agents/orch*.md; do
  link "$agent" "$DEST/agents/$(basename "$agent")"
done

echo
python3 "$SRC/skills/orchestrate/scripts/sync_models.py" --check
