#!/usr/bin/env python3
"""
Second Brain Verifier — Post-Run Validation

Checks that a completed (or in-progress) second brain build
conforms to the v4 spec. Run from the project root where
.second-brain/ and second-brain/ live.

Usage:
    python3 verify.py <project_dir>
    python3 verify.py .                    # current directory
    python3 verify.py /path/to/project

Exit codes:
    0 = all checks passed
    1 = failures found
    2 = usage error
"""

from __future__ import annotations

import sys
import re
from pathlib import Path
from collections import defaultdict

CATEGORIES = [
    "architecture", "tech-stack", "debugging", "scaling", "security",
    "data-modeling", "code-style", "refactoring", "integration", "error-handling",
    "product-thinking", "workflow",
]

EXPECTED_OUTPUT_DIRS = [
    "patterns", "decisions", "conventions", "evolution",
    "playbooks", "philosophy", "raw", "profile",
]

EXPECTED_PATTERN_FILES = [
    "architecture-patterns.md", "scaling-patterns.md", "debugging-patterns.md",
    "security-patterns.md", "data-modeling-patterns.md", "integration-patterns.md",
    "error-handling-patterns.md", "refactoring-patterns.md",
]

REQUIRED_CONFIG_FIELDS = [
    "Brain Name", "Work Dir", "Batch Size", "Total Commits",
]

RECOMMENDED_CONFIG_FIELDS = [
    "Output Dir", "Memory Scope", "Python Command",
]

EXPECTED_PHILOSOPHY_FILES = [
    "product-thinking.md", "workflow.md",
]


class Checker:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.work_dir = project_dir / ".second-brain"
        self.output_dir = project_dir / "second-brain"
        self.passes = 0
        self.failures = []
        self.warnings = []
        self.config = {}

    def check(self, condition: bool, description: str, severity: str = "FAIL"):
        if condition:
            self.passes += 1
            print(f"  PASS  {description}")
        elif severity == "WARN":
            self.warnings.append(description)
            print(f"  WARN  {description}")
        else:
            self.failures.append(description)
            print(f"  FAIL  {description}")

    def run_all(self):
        print(f"\n{'='*60}")
        print(f"  SECOND BRAIN VERIFIER")
        print(f"  Project: {self.project_dir}")
        print(f"{'='*60}\n")

        self.check_work_dir_exists()
        self.check_config()
        self.check_commits_file()
        self.check_progress()
        self.check_scratchpad()
        self.check_indexed()
        self.check_categories()
        self.check_output_structure()
        self.check_profile()
        self.check_raw_files()
        self.check_batch_naming()
        self.check_commit_coverage()

        self.print_summary()
        return len(self.failures) == 0

    def check_work_dir_exists(self):
        print("[1/12] Work Directory")
        self.check(self.work_dir.exists(), ".second-brain/ directory exists")
        self.check(self.output_dir.exists(), "second-brain/ output directory exists")

    def check_config(self):
        print("\n[2/12] Config File")
        config_path = self.work_dir / "config.md"
        self.check(config_path.exists(), "config.md exists")
        if not config_path.exists():
            return

        content = config_path.read_text(encoding="utf-8", errors="replace")
        self.config = {}
        for line in content.splitlines():
            if ":" in line and not line.startswith("#") and not line.startswith("|"):
                key, _, val = line.partition(":")
                clean_key = key.strip().lstrip("- ").strip("*").strip()
                if clean_key:
                    self.config[clean_key] = val.strip()

        for field in REQUIRED_CONFIG_FIELDS:
            self.check(field in self.config, f"Config has required field: {field}")

        for field in RECOMMENDED_CONFIG_FIELDS:
            self.check(field in self.config, f"Config has recommended field: {field}", severity="WARN")

        # Check paths are absolute
        work_dir_val = self.config.get("Work Dir", "")
        if work_dir_val:
            is_abs = work_dir_val.startswith("/") or (len(work_dir_val) > 2 and work_dir_val[1] == ":")
            self.check(is_abs, f"Work Dir is absolute path: {work_dir_val}")

        output_dir_val = self.config.get("Output Dir", "")
        if output_dir_val:
            clean = output_dir_val.split("(")[0].strip()
            is_abs = clean.startswith("/") or (len(clean) > 2 and clean[1] == ":")
            self.check(is_abs, f"Output Dir is absolute path: {clean}")

    def check_commits_file(self):
        print("\n[3/12] Commits File")
        # Look for any commits file (with or without repo ID prefix)
        commit_files = list(self.work_dir.glob("*commits.txt"))
        self.check(len(commit_files) > 0, f"Commits file(s) found: {len(commit_files)}")

        self.total_commits = 0
        self.repo_ids_from_commits = []
        for cf in commit_files:
            lines = cf.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            self.total_commits += len(lines)
            # Check format: hash|message|date
            if lines:
                first = lines[0]
                parts = first.split("|")
                self.check(
                    len(parts) >= 3,
                    f"{cf.name}: correct format (hash|message|date)",
                )
            # Extract repo ID from filename
            name = cf.stem  # e.g., "my-backend-commits" or "commits"
            if name.endswith("-commits"):
                repo_id = name[:-len("-commits")]
                if repo_id:
                    self.repo_ids_from_commits.append(repo_id)

        try:
            expected = int(self.config.get("Total Commits", "0"))
        except ValueError:
            expected = 0
        if expected > 0:
            self.check(
                self.total_commits == expected,
                f"Commit count matches config ({self.total_commits} found, {expected} expected)",
            )

    def check_progress(self):
        print("\n[4/12] Progress Tracking")
        progress_path = self.work_dir / "progress.md"
        self.check(progress_path.exists(), "progress.md exists")
        if not progress_path.exists():
            return

        content = progress_path.read_text(encoding="utf-8", errors="replace")
        checked = content.count("[x]")
        unchecked = content.count("[ ]")
        total = checked + unchecked

        self.check(total > 0, f"Progress has {total} tracked items")
        self.check(unchecked == 0, f"All items complete ({checked}/{total} checked)", severity="WARN")

        # Check all phases present
        for phase in ["Phase 1", "Phase 2", "Phase 3"]:
            self.check(phase in content, f"Progress tracks {phase}")

    def check_scratchpad(self):
        print("\n[5/12] Scratchpad (Phase 1 Output)")
        scratchpad_dir = self.work_dir / "scratchpad"
        self.check(scratchpad_dir.exists(), "scratchpad/ directory exists")
        if not scratchpad_dir.exists():
            return

        batch_files = sorted(scratchpad_dir.glob("batch-*.md"))
        self.check(len(batch_files) > 0, f"Batch files found: {len(batch_files)}")

        total_commit_headers = 0
        batches_with_repo_id = 0
        batches_without_repo_id = 0

        for bf in batch_files:
            content = bf.read_text(encoding="utf-8", errors="replace")
            headers = content.count("## Commit:")
            total_commit_headers += headers
            self.check(headers > 0, f"{bf.name}: has {headers} commit entries")

            # Check for REPO_ID in filename
            match = re.match(r"batch-(.+)-\d{3}-commits-", bf.name)
            if match:
                batches_with_repo_id += 1
            else:
                batches_without_repo_id += 1

            # Check for category tags
            tag_count = content.count("### Category Tags")
            self.check(
                tag_count == headers,
                f"{bf.name}: all {headers} commits have category tags ({tag_count} found)",
                severity="WARN",
            )

        # Check for artifact harvest files (Phase 1A)
        artifact_files = sorted(scratchpad_dir.glob("artifacts-*.md"))
        self.check(
            len(artifact_files) > 0,
            f"Artifact harvest files found: {len(artifact_files)}",
            severity="WARN",
        )
        for af in artifact_files:
            content = af.read_text(encoding="utf-8", errors="replace")
            artifact_headers = content.count("## Artifact:")
            self.check(
                artifact_headers > 0,
                f"{af.name}: has {artifact_headers} artifact entries",
                severity="WARN",
            )

        if batches_without_repo_id > 0 and self.repo_ids_from_commits:
            self.check(
                False,
                f"Batch filenames missing REPO_ID prefix ({batches_without_repo_id} files)",
                severity="WARN",
            )

        # Compare with total commits from config
        try:
            expected = int(self.config.get("Total Commits", "0"))
        except ValueError:
            expected = 0
        if expected > 0:
            self.check(
                total_commit_headers == expected,
                f"Scratchpad covers all commits ({total_commit_headers}/{expected})",
            )

    def check_indexed(self):
        print("\n[6/12] Indexed Files (Phase 1.5 Output)")
        indexed_dir = self.work_dir / "indexed"
        self.check(indexed_dir.exists(), "indexed/ directory exists")
        if not indexed_dir.exists():
            return

        for cat in CATEGORIES:
            f = indexed_dir / f"{cat}-raw.md"
            self.check(f.exists(), f"{cat}-raw.md exists")

        stats = indexed_dir / "statistics-raw.md"
        self.check(stats.exists(), "statistics-raw.md exists")

        if stats.exists():
            content = stats.read_text(encoding="utf-8", errors="replace")
            self.check(
                "Total commits parsed" in content,
                "Statistics has total commits count",
            )
            self.check(
                "Commits Per Category" in content,
                "Statistics has per-category breakdown",
            )

    def check_categories(self):
        print("\n[7/12] Category Files (Phase 2 Output)")
        cat_dir = self.work_dir / "categories"
        self.check(cat_dir.exists(), "categories/ directory exists")
        if not cat_dir.exists():
            return

        for cat in CATEGORIES:
            f = cat_dir / f"{cat}.md"
            exists = f.exists()
            self.check(exists, f"{cat}.md exists")
            if exists:
                content = f.read_text(encoding="utf-8", errors="replace")
                lines = len(content.strip().splitlines())
                self.check(
                    lines >= 5,
                    f"{cat}.md has content ({lines} lines)",
                    severity="WARN",
                )

    def check_output_structure(self):
        print("\n[8/12] Output Directory Structure")
        if not self.output_dir.exists():
            self.check(False, "second-brain/ output directory exists")
            return

        for d in EXPECTED_OUTPUT_DIRS:
            self.check(
                (self.output_dir / d).exists(),
                f"second-brain/{d}/ exists",
            )

        readme = self.output_dir / "README.md"
        self.check(readme.exists(), "second-brain/README.md exists")

        for pf in EXPECTED_PATTERN_FILES:
            path = self.output_dir / "patterns" / pf
            self.check(path.exists(), f"patterns/{pf} exists")

        self.check(
            (self.output_dir / "decisions" / "tech-decisions.md").exists(),
            "decisions/tech-decisions.md exists",
        )
        self.check(
            (self.output_dir / "conventions" / "code-style.md").exists(),
            "conventions/code-style.md exists",
        )
        self.check(
            (self.output_dir / "playbooks" / "debugging-playbook.md").exists(),
            "playbooks/debugging-playbook.md exists",
        )
        self.check(
            (self.output_dir / "playbooks" / "scaling-playbook.md").exists(),
            "playbooks/scaling-playbook.md exists",
        )
        self.check(
            (self.output_dir / "evolution" / "architecture-evolution.md").exists(),
            "evolution/architecture-evolution.md exists",
        )

        for pf in EXPECTED_PHILOSOPHY_FILES:
            path = self.output_dir / "philosophy" / pf
            self.check(path.exists(), f"philosophy/{pf} exists")

    def check_profile(self):
        print("\n[9/12] Engineer Profile")
        profile = self.output_dir / "profile" / "engineer-profile.md"
        self.check(profile.exists(), "engineer-profile.md exists")
        if not profile.exists():
            return

        content = profile.read_text(encoding="utf-8", errors="replace")
        lines = len(content.strip().splitlines())

        self.check(lines >= 100, f"Profile is substantial ({lines} lines, need 100+)")
        self.check(lines <= 600, f"Profile is not bloated ({lines} lines, max 600)", severity="WARN")

        # Check for key sections
        for section in [
            "Core Philosophy", "Tech Stack", "Architecture",
            "Debugging Style", "Non-Negotiables",
            "Product Thinking", "Workflow",
        ]:
            self.check(
                section in content,
                f"Profile has '{section}' section",
            )

        # Check for specificity (no generic fluff)
        generic_phrases = ["best practices", "clean code", "follows conventions"]
        for phrase in generic_phrases:
            self.check(
                phrase.lower() not in content.lower(),
                f"Profile avoids generic phrase: '{phrase}'",
                severity="WARN",
            )

    def check_raw_files(self):
        print("\n[10/12] Raw Files")
        commit_log = self.output_dir / "raw" / "commit-log.md"
        stats = self.output_dir / "raw" / "statistics.md"

        self.check(commit_log.exists(), "raw/commit-log.md exists")
        self.check(stats.exists(), "raw/statistics.md exists")

        if commit_log.exists():
            content = commit_log.read_text(encoding="utf-8", errors="replace")
            lines = len(content.strip().splitlines())
            self.check(lines > 0, f"commit-log.md has content ({lines} lines)")

    def check_batch_naming(self):
        print("\n[11/12] Batch Naming Convention (v3 Spec)")
        scratchpad_dir = self.work_dir / "scratchpad"
        if not scratchpad_dir.exists():
            return

        batch_files = sorted(scratchpad_dir.glob("batch-*.md"))
        v3_pattern = re.compile(r"^batch-.+-\d{3}-commits-\d+-\d+\.md$")
        legacy_pattern = re.compile(r"^batch-\d{3}-commits-\d+-\d+\.md$")

        v3_count = 0
        legacy_count = 0
        unknown_count = 0

        for bf in batch_files:
            if v3_pattern.match(bf.name):
                v3_count += 1
            elif legacy_pattern.match(bf.name):
                legacy_count += 1
            else:
                unknown_count += 1

        if v3_count > 0:
            self.check(True, f"Uses v3 batch naming (REPO_ID prefix): {v3_count} files")
        if legacy_count > 0:
            self.check(
                False,
                f"Uses legacy batch naming (no REPO_ID): {legacy_count} files — should be batch-<REPO_ID>-NNN-commits-X-Y.md",
                severity="WARN",
            )
        if unknown_count > 0:
            self.check(
                False,
                f"Unknown batch naming format: {unknown_count} files",
                severity="WARN",
            )

    def check_commit_coverage(self):
        print("\n[12/12] Commit Coverage")
        scratchpad_dir = self.work_dir / "scratchpad"
        if not scratchpad_dir.exists():
            return

        # Count unique commit hashes in scratchpad
        commit_hashes = set()
        for bf in scratchpad_dir.glob("batch-*.md"):
            content = bf.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r"## Commit:\s*([a-fA-F0-9]{7,})", content):
                commit_hashes.add(match.group(1))

        try:
            expected = int(self.config.get("Total Commits", "0"))
        except ValueError:
            expected = 0
        if expected > 0:
            coverage = len(commit_hashes) / expected * 100
            self.check(
                len(commit_hashes) == expected,
                f"Unique commits analyzed: {len(commit_hashes)}/{expected} ({coverage:.0f}%)",
            )
        else:
            print(f"  INFO  Found {len(commit_hashes)} unique commit hashes")

        # Check for duplicate commits (reuse data from above)
        all_hashes = []
        for bf in scratchpad_dir.glob("batch-*.md"):
            content = bf.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r"## Commit:\s*([a-fA-F0-9]{7,})", content):
                all_hashes.append(match.group(1))

        dupes = len(all_hashes) - len(set(all_hashes))
        self.check(
            dupes == 0,
            f"No duplicate commit analyses (duplicates: {dupes})",
            severity="WARN",
        )

    def print_summary(self):
        print(f"\n{'='*60}")
        total = self.passes + len(self.failures) + len(self.warnings)
        print(f"  RESULTS: {self.passes} passed, {len(self.failures)} failed, {len(self.warnings)} warnings")
        print(f"  Total checks: {total}")
        print(f"{'='*60}")

        if self.failures:
            print(f"\n  FAILURES:")
            for f in self.failures:
                print(f"    - {f}")

        if self.warnings:
            print(f"\n  WARNINGS:")
            for w in self.warnings:
                print(f"    - {w}")

        if not self.failures and not self.warnings:
            print(f"\n  ALL CHECKS PASSED")
        elif not self.failures:
            print(f"\n  PASSED (with {len(self.warnings)} warnings)")
        else:
            print(f"\n  FAILED ({len(self.failures)} issues to fix)")

        print()


def main():
    if len(sys.argv) == 2:
        # Single arg: project_dir (derives work_dir and output_dir)
        project_dir = Path(sys.argv[1]).resolve()
        if not project_dir.exists():
            print(f"Error: Directory not found: {project_dir}")
            sys.exit(2)
        checker = Checker(project_dir)
    elif len(sys.argv) == 3:
        # Two args: work_dir and output_dir (explicit paths)
        work_dir = Path(sys.argv[1]).resolve()
        output_dir = Path(sys.argv[2]).resolve()
        # Derive project_dir from work_dir parent
        project_dir = work_dir.parent
        checker = Checker(project_dir)
        # Override derived paths with explicit ones
        checker.work_dir = work_dir
        checker.output_dir = output_dir
    else:
        print(f"Usage: {sys.argv[0]} <project_dir>")
        print(f"       {sys.argv[0]} <work_dir> <output_dir>")
        print(f"  Verifies a second brain build.")
        sys.exit(2)

    success = checker.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
