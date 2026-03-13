#!/usr/bin/env python3
"""
Second Brain Indexer — Phase 1.5

Reads all scratchpad batch files and splits commit findings by category tag
into per-category indexed files. This ensures each Phase 2 category agent
only reads its own relevant content (~1/10th of total), preventing context overflow.

Usage:
    python indexer.py <scratchpad_dir> <indexed_dir>

Example:
    python indexer.py .second-brain/scratchpad .second-brain/indexed
"""

import sys
import os
import re
from pathlib import Path
from collections import defaultdict

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


def parse_commits(content: str) -> list[dict]:
    """Parse a scratchpad file into individual commit sections."""
    commits = []
    # Split on ## Commit: headers
    sections = re.split(r"(?=^## Commit: )", content, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section.startswith("## Commit:"):
            continue

        # Extract category tags
        tags_match = re.search(
            r"### Category Tags\s*\n(.+?)(?=\n### |\n## Commit:|\Z)",
            section,
            re.DOTALL,
        )

        categories = []
        if tags_match:
            tags_text = tags_match.group(1).strip()
            # Tags can be comma-separated, or one per line
            for tag in re.split(r"[,\n]", tags_text):
                tag = tag.strip().lower().strip("-").strip("*").strip("`")
                if tag in CATEGORIES:
                    categories.append(tag)

        # If no categories detected, put in all categories (don't lose data)
        if not categories:
            categories = CATEGORIES.copy()

        commits.append({"content": section, "categories": categories})

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
    category_findings: dict[str, list[str]] = defaultdict(list)

    # Read all batch files in order
    batch_files = sorted(scratchpad_dir.glob("batch-*.md"))

    if not batch_files:
        print(f"Warning: No batch files found in {scratchpad_dir}")
        sys.exit(0)

    total_commits = 0
    for batch_file in batch_files:
        content = batch_file.read_text(encoding="utf-8", errors="replace")
        commits = parse_commits(content)
        total_commits += len(commits)

        for commit in commits:
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

    # Print summary
    print(f"Indexing complete:")
    print(f"  Batch files processed: {len(batch_files)}")
    print(f"  Total commits parsed: {total_commits}")
    print(f"  Category files created: {len(CATEGORIES)}")
    for category in CATEGORIES:
        count = len(category_findings.get(category, []))
        print(f"    {category}: {count} findings")


if __name__ == "__main__":
    main()
