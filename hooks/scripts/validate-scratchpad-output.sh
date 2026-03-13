#!/bin/bash
# PostToolUse hook: After Write to scratchpad, validate structure
# Checks that scratchpad files contain proper ## Commit: or ## Artifact: headers
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
CONFIG_FILE="$PROJECT_DIR/.second-brain/config.md"

# Skip if no active build
if [ ! -f "$CONFIG_FILE" ]; then
  exit 0
fi

input=$(cat)
file_path=$(printf '%s\n' "$input" | jq -r '.tool_input.file_path // empty')

# Only check scratchpad files (batch-*.md or artifacts-*.md)
if ! echo "$file_path" | grep -qE '/scratchpad/(batch|artifacts)-.*\.md$'; then
  exit 0
fi

# Skip if file doesn't exist yet (write may have failed)
if [ ! -f "$file_path" ]; then
  exit 0
fi

# Count ## Commit: and ## Artifact: headers
entry_count=$(grep -cE '^## (Commit|Artifact):' "$file_path" 2>/dev/null || echo "0")

if [ "$entry_count" -eq 0 ]; then
  echo "WARNING: Scratchpad file '$file_path' has 0 '## Commit:' or '## Artifact:' headers. Expected at least 1." >&2
  exit 2
fi

# Check for category tags section in each entry
tag_count=$(grep -c '### Category Tags' "$file_path" 2>/dev/null || echo "0")
if [ "$tag_count" -lt "$entry_count" ]; then
  echo "WARNING: Scratchpad file has $entry_count entries but only $tag_count '### Category Tags' sections. Some entries may be missing tags." >&2
  exit 2
fi

echo "Scratchpad validated: $entry_count entries with $tag_count tag sections in $(basename "$file_path")"
exit 0
