#!/bin/bash
# PreToolUse hook: Validate Write/Edit tool calls use absolute paths
# Only active during a second-brain build (flag: .second-brain/config.md exists)
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
CONFIG_FILE="$PROJECT_DIR/.second-brain/config.md"

# Skip if no active build
if [ ! -f "$CONFIG_FILE" ]; then
  exit 0
fi

input=$(cat)
file_path=$(printf '%s\n' "$input" | jq -r '.tool_input.file_path // empty')

# Skip if no file_path (shouldn't happen for Write/Edit)
if [ -z "$file_path" ]; then
  exit 0
fi

# Check 1: Reject relative paths targeting second-brain directories
if echo "$file_path" | grep -qE '^\./?(\.second-brain|second-brain)/'; then
  echo "BLOCK: Relative path detected '$file_path'. Use absolute paths from config.md (WORK_DIR/OUTPUT_DIR)." >&2
  exit 2
fi

# Check 2: If writing to a scratchpad batch file, enforce REPO_ID in naming
if echo "$file_path" | grep -qE '/scratchpad/batch-'; then
  basename_file=$(basename "$file_path")
  # Valid pattern: batch-<REPO_ID>-NNN-commits-N-N.md
  # Invalid pattern: batch-NNN-commits-N-N.md (missing REPO_ID)
  if echo "$basename_file" | grep -qE '^batch-[0-9]{3}-'; then
    echo "BLOCK: Batch file '$basename_file' missing REPO_ID prefix. Expected: batch-<REPO_ID>-NNN-commits-N-N.md" >&2
    exit 2
  fi
fi

# Check 2b: If writing to a scratchpad artifact file, enforce REPO_ID in naming
if echo "$file_path" | grep -qE '/scratchpad/artifacts-'; then
  basename_file=$(basename "$file_path")
  # Valid pattern: artifacts-<REPO_ID>.md
  # Invalid pattern: artifacts.md (missing REPO_ID)
  if echo "$basename_file" | grep -qE '^artifacts\.md$'; then
    echo "BLOCK: Artifact file '$basename_file' missing REPO_ID. Expected: artifacts-<REPO_ID>.md" >&2
    exit 2
  fi
fi

# Check 3: If writing to categories dir, ensure file has proper slug name
if echo "$file_path" | grep -qE '/categories/'; then
  basename_file=$(basename "$file_path")
  valid_slugs="architecture|tech-stack|debugging|scaling|security|data-modeling|code-style|refactoring|integration|error-handling|product-thinking|workflow"
  if ! echo "$basename_file" | grep -qE "^($valid_slugs)\.md$"; then
    echo "WARN: Category file '$basename_file' doesn't match expected slug names." >&2
    # Don't block, just warn (exit 0 so it shows in transcript)
  fi
fi

exit 0
