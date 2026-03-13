#!/usr/bin/env python3
"""
Second Brain Indexer — Phase 1.5

Reads all scratchpad batch files and splits commit findings by category tag
into per-category indexed files. This ensures each Phase 2 category agent
only reads its own relevant content (~1/10th of total), preventing context overflow.

Also produces statistics-raw.md with pre-computed counts for Phase 3.

Usage:
    python3 indexer.py <scratchpad_dir> <indexed_dir>

Example:
    python3 indexer.py .second-brain/scratchpad .second-brain/indexed
"""

from __future__ import annotations

import sys
import os
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

CATEGORIES = [
    "architecture",
    "tech-stack",
    "debugging",
    "scaling",
    "security",
    "data-modeling",
    "code-style",
    "refactoring",
    "integration",
    "error-handling",
]

# Normalized lookup: remove hyphens/underscores/spaces for fuzzy matching
NORMALIZED_CATEGORIES = {}
for cat in CATEGORIES:
    NORMALIZED_CATEGORIES[re.sub(r"[\s_-]", "", cat).lower()] = cat


def normalize_tag(tag: str) -> str:
    """Normalize a category tag for fuzzy matching."""
    return re.sub(r"[\s_-]", "", tag).lower()


def parse_commits(content: str) -> list:
    """Parse a scratchpad file into individual commit sections."""
    commits = []
    # Split on ## Commit: headers
    sections = re.split(r"(?=^## Commit: )", content, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section.startswith("## Commit:"):
            continue

        # Extract date for timeline statistics
        date_match = re.search(r"^Date:\s*(.+)$", section, re.MULTILINE)
        commit_date = date_match.group(1).strip() if date_match else ""

        # Extract category tags — handle multiple formats:
        # 1. Tags on next line after header: ### Category Tags\n<tags>
        # 2. Tags inline: ### Category Tags: <tags>
        tags_match = re.search(
            r"### Category Tags[:\s]*\n?(.+?)(?=\n### |\n## Commit:|\Z)",
            section,
            re.DOTALL,
        )

        categories = []
        unrecognized = []
        if tags_match:
            tags_text = tags_match.group(1).strip()
            # Tags can be comma-separated, one per line, or markdown list items
            for tag in re.split(r"[,\n]", tags_text):
                tag = tag.strip().lower().strip("-").strip("*").strip("`").strip()
                if not tag or tag in ("none", "none detected", "n/a"):
                    continue
                # Try exact match first
                if tag in CATEGORIES:
                    categories.append(tag)
                else:
                    # Try fuzzy match (ignore hyphens/underscores/spaces)
                    normalized = normalize_tag(tag)
                    if normalized in NORMALIZED_CATEGORIES:
                        categories.append(NORMALIZED_CATEGORIES[normalized])
                    else:
                        unrecognized.append(tag)

        if unrecognized:
            print(
                f"  Warning: Unrecognized tags in commit section: {unrecognized}"
            )

        commits.append({
            "content": section,
            "categories": categories,
            "date": commit_date,
            "untagged": len(categories) == 0,
        })

    return commits


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <scratchpad_dir> <indexed_dir>")
        sys.exit(1)

    scratchpad_dir = Path(sys.argv[1])
    indexed_dir = Path(sys.argv[2])

    if not scratchpad_dir.exists():
        print(f"Error: Scratchpad directory not found: {scratchpad_dir}")
        sys.exit(1)

    # Create indexed directory
    indexed_dir.mkdir(parents=True, exist_ok=True)

    # Collect all findings by category
    category_findings = defaultdict(list)
    uncategorized = []
    total_commits = 0
    untagged_count = 0
    dates = []

    # Read all batch files in order
    batch_files = sorted(scratchpad_dir.glob("batch-*.md"))

    if not batch_files:
        print(f"Warning: No batch files found in {scratchpad_dir}")
        sys.exit(0)

    for batch_file in batch_files:
        try:
            content = batch_file.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError) as e:
            print(f"Warning: Could not read {batch_file}: {e}, skipping")
            continue

        commits = parse_commits(content)

        if not commits:
            print(
                f"Warning: No commits parsed from {batch_file.name} — file may be empty or malformed"
            )

        total_commits += len(commits)

        for commit in commits:
            if commit["date"]:
                dates.append(commit["date"])

            if commit["untagged"]:
                untagged_count += 1
                uncategorized.append(commit["content"])
                continue

            for category in commit["categories"]:
                category_findings[category].append(commit["content"])

    # Write indexed files
    for category in CATEGORIES:
        output_file = indexed_dir / f"{category}-raw.md"
        findings = category_findings.get(category, [])

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# {category.replace('-', ' ').title()} — Raw Findings\n\n")
            f.write(f"Total commits with {category} findings: {len(findings)}\n\n")
            f.write("---\n\n")

            for finding in findings:
                f.write(finding)
                f.write("\n\n---\n\n")

    # Write uncategorized file
    if uncategorized:
        output_file = indexed_dir / "uncategorized-raw.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# Uncategorized — Raw Findings\n\n")
            f.write(f"Total uncategorized commits: {len(uncategorized)}\n\n")
            f.write("---\n\n")
            for finding in uncategorized:
                f.write(finding)
                f.write("\n\n---\n\n")

    # Write statistics file for Phase 3
    stats_file = indexed_dir / "statistics-raw.md"
    with open(stats_file, "w", encoding="utf-8") as f:
        f.write("# Pre-Computed Statistics\n\n")
        f.write(f"## Totals\n")
        f.write(f"- Total commits parsed: {total_commits}\n")
        f.write(f"- Batch files processed: {len(batch_files)}\n")
        f.write(f"- Uncategorized commits: {untagged_count}\n\n")
        f.write(f"## Commits Per Category\n")
        for category in CATEGORIES:
            count = len(category_findings.get(category, []))
            f.write(f"- {category}: {count}\n")
        f.write(f"\n## Timeline\n")
        # Parse dates and group by month
        monthly = defaultdict(int)
        for d in dates:
            try:
                # Handle various date formats from git
                dt = d.split(" ")[0]  # Take just the date part
                month_key = dt[:7]  # YYYY-MM
                monthly[month_key] += 1
            except (ValueError, IndexError):
                pass
        for month in sorted(monthly.keys()):
            f.write(f"- {month}: {monthly[month]} commits\n")

    # Print summary
    print(f"Indexing complete:")
    print(f"  Batch files processed: {len(batch_files)}")
    print(f"  Total commits parsed: {total_commits}")
    print(f"  Uncategorized commits: {untagged_count}")
    print(f"  Category files created: {len(CATEGORIES)}")
    for category in CATEGORIES:
        count = len(category_findings.get(category, []))
        print(f"    {category}: {count} findings")


if __name__ == "__main__":
    main()
