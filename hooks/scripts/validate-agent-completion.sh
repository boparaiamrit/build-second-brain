#!/bin/bash
# SubagentStop hook: Verify subagent produced expected output files
# Checks scratchpad files (Phase 1) and category files (Phase 2) exist after agent stops
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
CONFIG_FILE="$PROJECT_DIR/.second-brain/config.md"

# Skip if no active build
if [ ! -f "$CONFIG_FILE" ]; then
  exit 0
fi

WORK_DIR="$PROJECT_DIR/.second-brain"

# Count current state (use find instead of ls for reliability)
scratchpad_count=0
artifact_count=0
category_count=0
if [ -d "$WORK_DIR/scratchpad" ]; then
  scratchpad_count=$(find "$WORK_DIR/scratchpad" -name 'batch-*.md' -type f 2>/dev/null | wc -l)
  artifact_count=$(find "$WORK_DIR/scratchpad" -name 'artifacts-*.md' -type f 2>/dev/null | wc -l)
fi
if [ -d "$WORK_DIR/categories" ]; then
  category_count=$(find "$WORK_DIR/categories" -name '*.md' -type f 2>/dev/null | wc -l)
fi

# Read expected totals from config
total_batches=$(grep -oE 'Total Batches:[[:space:]]*[0-9]+' "$WORK_DIR/config.md" 2>/dev/null | grep -oE '[0-9]+' || echo "0")

echo "Build progress: $scratchpad_count/$total_batches batch files, $artifact_count artifact files, $category_count/12 category files"

# Check if progress.md exists and report
if [ -f "$WORK_DIR/progress.md" ]; then
  p1_done=$(grep -c '\[x\]' "$WORK_DIR/progress.md" 2>/dev/null || echo "0")
  p1_total=$(grep -cE '\[(x| )\]' "$WORK_DIR/progress.md" 2>/dev/null || echo "0")
  echo "Progress checkmarks: $p1_done/$p1_total items complete"
fi

exit 0
