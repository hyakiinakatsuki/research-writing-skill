#!/usr/bin/env python3
"""Python replacement for research_quality_gate.ps1 — 100% functional parity.

Usage:
    python3 research_quality_gate.py --self-test
    python3 research_quality_gate.py --project-path <dir> [--submission]

Backward-compatible CLI flags: -SelfTest, -ProjectPath, -Submission are also accepted.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────
# Gate result accumulator
# ──────────────────────────────────────────────────────────
from gate_kit import GateResult, is_review_framework  # noqa: E402

# ──────────────────────────────────────────────────────────
# Pattern constants (ported from .ps1 L151-155)
# ──────────────────────────────────────────────────────────

CITATION_PATTERN = (
    r"\uff08[^\uff09]*(?:19|20)\d{2}[^\uff09]*\uff09"   # fullwidth parens with year
    r"|\([A-Z][^)]*(?:19|20)\d{2}[^)]*\)"                # ASCII parens with year
    r"|\[[A-Za-z]+-?\d+\]"                                # bracket refs like [Smith-42]
)

LIST_PATTERN = r"(?m)^\s*(?:[-*+]\s+|\d+\.\s+)"

PROCESS_PATTERN = (
    r"说明：|实验目的|表位|图位|回填模板|讨论提示|请用户|用户替换"
    r"|写作要求|修改要求|this section is a template|discussion prompt|fill later"
)

PLACEHOLDER_PATTERN = r"待回填|待实验回填|待真实实验替换|公式占位|算法占位|TODO|TBD"

RESULT_OVERCLAIM_PATTERN = r"实验结果表明|results show|verified"

INTRO_FILES = [
    "chapters/01_Introduction.md",
    "chapters/01-introduction.md",
    "chapters/02_Introduction.md",
    "chapters/02-introduction.md",
]

RELATED_FILES = [
    "chapters/02-related-work.md",
    "chapters/03_Related_Work.md",
    "chapters/03-related-work.md",
]


# ──────────────────────────────────────────────────────────
# Helper functions (ported from .ps1)
# ──────────────────────────────────────────────────────────

def read_text(path: Path) -> str | None:
    """Port of Get-TextIfExists. Returns file content or None."""
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return None


def count_regex(text: str, pattern: str) -> int:
    """Port of Count-Regex."""
    if not text or not text.strip():
        return 0
    return len(re.findall(pattern, text))


def get_chapter_architecture_specs(root: Path) -> list[dict]:
    """Port of Get-ChapterArchitectureSpecs. Parses plan/chapter-architecture.md."""
    arch_path = root / "plan" / "chapter-architecture.md"
    specs: list[dict] = []
    if not arch_path.exists():
        return specs

    for line in arch_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*-\s*(chapters/[^\s|]+\.md)(.*)", line)
        if not m:
            continue
        rel = m.group(1)
        rest = m.group(2)
        min_chars = 0
        mc = re.search(r"min_chars=(\d+)", rest)
        if mc:
            min_chars = int(mc.group(1))
        specs.append({
            "rel": rel,
            "min_chars": min_chars,
            "agent_required": bool(re.search(r"agent=required", rest)),
            "placeholders_allowed": bool(re.search(r"placeholders=yes", rest)),
        })
    return specs


def get_prose_paragraph_count(text: str) -> int:
    """Port of Get-ProseParagraphCount.
    Split on 2+ newlines, filter: >=150 chars, not heading/list/table/code."""
    if not text or not text.strip():
        return 0
    paragraphs = re.split(r"(?:\r?\n\s*){2,}", text)
    count = 0
    for para in paragraphs:
        p = para.strip()
        if len(p) < 150:
            continue
        if re.match(r"^\s*#", p):
            continue
        if re.match(r"^\s*[-*+]\s+", p):
            continue
        if re.match(r"^\s*\|", p):
            continue
        if re.match(r"^```", p):
            continue
        count += 1
    return count




def count_markdown_tables(text: str) -> int:
    """Port of Count-MarkdownTables. Count table-start transitions."""
    if not text or not text.strip():
        return 0
    count = 0
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        is_table_line = stripped.startswith("|") and stripped.endswith("|")
        if is_table_line and not in_table:
            count += 1
        in_table = is_table_line
    return count


# ──────────────────────────────────────────────────────────
# SelfTest (ported from .ps1 L157-183)
# ──────────────────────────────────────────────────────────

def self_test() -> bool:
    """Validate regex patterns against known sample. Port of -SelfTest."""
    sample = "实验目的\n回填模板\n[待回填-F1]"
    process_hits = count_regex(sample, PROCESS_PATTERN)
    placeholder_hits = count_regex(sample, PLACEHOLDER_PATTERN)

    ok = True
    if process_hits != 2:
        print(f"SelfTest expected 2 process hits, got {process_hits}.")
        ok = False
    if placeholder_hits != 1:
        print(f"SelfTest expected 1 placeholder hit, got {placeholder_hits}.")
        ok = False

    if ok:
        print("Research quality gate self-test passed.")
    else:
        print("Research quality gate self-test failed.")
    return ok


# ──────────────────────────────────────────────────────────
# Main check runner
# ──────────────────────────────────────────────────────────

def run_checks(root: Path, submission: bool) -> GateResult:
    """Run all 13 check categories. Port of .ps1 L185-430."""
    gate = GateResult()

    # ── 1. Chapters directory existence ──
    chapters_path = root / "chapters"
    if not chapters_path.exists():
        gate.fail(f"Missing chapters directory: {chapters_path}")

    # ── 2. Chapter architecture specs ──
    chapter_specs = get_chapter_architecture_specs(root)
    if chapter_specs and chapters_path.exists():
        expected_rels = {spec["rel"] for spec in chapter_specs}
        actual_rels = {
            f"chapters/{p.name}"
            for p in chapters_path.iterdir()
            if p.suffix == ".md" and p.is_file()
        }

        for rel in sorted(expected_rels - actual_rels):
            gate.fail(f"Chapter architecture requires missing file: {rel}")
        for rel in sorted(actual_rels - expected_rels):
            gate.fail(f"Unexpected chapter file not listed in plan/chapter-architecture.md: {rel}")

        # Per-chapter validation
        provenance_text = read_text(root / "plan" / "chapter-agent-provenance.md") or ""
        for spec in chapter_specs:
            file_path = root / spec["rel"]
            if not file_path.exists():
                continue

            text = file_path.read_text(encoding="utf-8", errors="replace")
            char_count = len(re.sub(r"\s", "", text))

            # min_chars
            if spec["min_chars"] > 0 and char_count < spec["min_chars"]:
                gate.fail(
                    f"{spec['rel']} has {char_count} non-whitespace characters; "
                    f"required min_chars={spec['min_chars']}."
                )

            # provenance
            if spec["agent_required"]:
                prov_pattern = re.compile(
                    r"(?m)^.*" + re.escape(spec["rel"]) + r".*status=ACCEPTED.*$"
                )
                if not prov_pattern.search(provenance_text):
                    gate.fail(f"{spec['rel']} requires an accepted chapter agent provenance entry.")

            # list lines
            is_reference_like = bool(re.search(r"References|Bibliography", spec["rel"]))
            is_abstract_like = bool(re.search(r"Abstract", spec["rel"]))
            list_lines = count_regex(text, LIST_PATTERN)
            if not is_reference_like and list_lines > 3:
                gate.fail(
                    f"{spec['rel']} has {list_lines} list-like line/s; "
                    f"full-paper chapters must be prose-led."
                )

            # prose paragraph count
            paragraph_count = get_prose_paragraph_count(text)
            if not is_reference_like and not is_abstract_like and paragraph_count < 6:
                gate.fail(
                    f"{spec['rel']} has only {paragraph_count} substantial prose paragraph/s."
                )

            # placeholders
            placeholder_hits = count_regex(text, PLACEHOLDER_PATTERN)
            if not spec["placeholders_allowed"] and placeholder_hits > 0:
                gate.fail(
                    f"{spec['rel']} contains unresolved placeholder/s but chapter "
                    f"architecture sets placeholders=no."
                )

    # ── 3. Aggregate chapter text + process language per file ──
    all_chapter_text = ""
    all_project_text = ""
    all_non_chapter_text = ""

    if chapters_path.exists():
        for fpath in sorted(chapters_path.glob("*.md")):
            text = fpath.read_text(encoding="utf-8", errors="replace")
            all_chapter_text += "\n" + text
            all_project_text += "\n" + text

            process_hits = count_regex(text, PROCESS_PATTERN)
            if process_hits > 0:
                gate.fail(
                    f"{fpath.name} contains process/user-instruction language "
                    f"({process_hits} hit/s)."
                )

            list_lines = count_regex(text, LIST_PATTERN)
            if list_lines > 12:
                gate.warn(
                    f"{fpath.name} has many list lines ({list_lines}); "
                    f"verify this is not report-style prose."
                )

    # ── 4. Aggregate non-chapter text (tables, figures, plan) ──
    for subdir in ("tables", "figures", "plan"):
        dir_path = root / subdir
        if not dir_path.exists():
            continue
        for fpath in dir_path.rglob("*.md"):
            text = fpath.read_text(encoding="utf-8", errors="replace")
            all_project_text += "\n" + text
            all_non_chapter_text += "\n" + text
        for fpath in dir_path.rglob("*.csv"):
            text = fpath.read_text(encoding="utf-8", errors="replace")
            all_project_text += "\n" + text
            all_non_chapter_text += "\n" + text
        for fpath in dir_path.rglob("*.json"):
            text = fpath.read_text(encoding="utf-8", errors="replace")
            all_project_text += "\n" + text
            all_non_chapter_text += "\n" + text

    # ── 5. Citation density: Introduction >= 5 ──
    for rel in INTRO_FILES:
        text = read_text(root / rel)
        if text is not None:
            count = count_regex(text, CITATION_PATTERN)
            if count < 5:
                gate.fail(
                    f"{rel} has only {count} citation-like marker/s; "
                    f"Introduction requires literature-grounded claims."
                )

    # ── 6. Citation density: Related Work >= 8 ──
    for rel in RELATED_FILES:
        text = read_text(root / rel)
        if text is not None:
            count = count_regex(text, CITATION_PATTERN)
            if count < 8:
                gate.fail(
                    f"{rel} has only {count} citation-like marker/s; "
                    f"Related Work requires evidence synthesis."
                )

    # ── 7. Evidence map existence ──
    evidence_map_exists = (
        (root / "refs" / "evidence-map.md").exists()
        or (root / "plan" / "evidence-map.md").exists()
    )
    if not evidence_map_exists:
        gate.fail("Missing evidence map: expected refs/evidence-map.md or plan/evidence-map.md.")

    # ── 8. Review/framework submission checks ──
    full_paper_text = read_text(root / "full-paper.md")
    if is_review_framework(root) and submission:
        if not full_paper_text or not full_paper_text.strip():
            gate.fail("Review/framework submission is missing full-paper.md.")
        else:
            # figure refs >= 1
            figure_refs = count_regex(full_paper_text, r"!\[[^\]]+\]\([^)]+\)")
            if figure_refs < 1:
                gate.fail(
                    "Review/framework submission has no referenced figure; "
                    "expected at least one source-backed framework or evidence figure."
                )

            # tables >= 2
            table_count = count_markdown_tables(full_paper_text)
            if table_count < 2:
                gate.fail(
                    f"Review/framework submission has too few markdown tables: "
                    f"{table_count}; expected at least 2 evidence/industry tables."
                )

        # review-framework-asset-plan.md
        review_asset_plan = root / "plan" / "review-framework-asset-plan.md"
        if not review_asset_plan.exists():
            gate.fail("Review/framework submission missing plan/review-framework-asset-plan.md.")

        # data-manifest.md
        data_manifest = root / "figures" / "data-manifest.md"
        if not data_manifest.exists():
            gate.fail("Review/framework submission missing figures/data-manifest.md.")
        else:
            manifest_text = data_manifest.read_text(encoding="utf-8", errors="replace")
            if re.search(r"mock_|synthetic_|PLANNING DATA", manifest_text):
                gate.fail(
                    "Review/framework figures/data-manifest.md contains "
                    "mock/synthetic planning data."
                )

        # data files (CSV/JSON)
        data_files: list[Path] = []
        for data_dir_rel in ("data", "figures/data"):
            data_dir = root / data_dir_rel
            if data_dir.exists():
                data_files.extend(data_dir.rglob("*.csv"))
                data_files.extend(data_dir.rglob("*.json"))
        if len(data_files) < 1:
            gate.fail(
                "Review/framework submission has no source-backed CSV/JSON data files "
                "under data/ or figures/data/."
            )
        else:
            for df in data_files:
                if re.match(r"^(?:mock_|synthetic_)", df.name):
                    gate.fail(f"Review/framework data file is mock/synthetic: {df}")
                    continue
                lines = [
                    line for line in df.read_text(encoding="utf-8", errors="replace").splitlines()
                    if line.strip()
                ]
                if len(lines) < 4:
                    gate.fail(
                        f"Review/framework data file has fewer than 3 substantive "
                        f"data rows: {df}"
                    )

        # figure scripts
        figures_dir = root / "figures"
        if not figures_dir.exists():
            gate.fail("Review/framework submission missing figures directory.")
        else:
            figure_scripts = list(figures_dir.rglob("*.py"))
            if len(figure_scripts) < 1:
                gate.fail(
                    "Review/framework submission has no figure-generation script "
                    "under figures/."
                )

        # final capability-use audit
        final_summary = root / "plan" / "final-gate-summary.md"
        if final_summary.exists():
            summary_text = final_summary.read_text(encoding="utf-8", errors="replace")
            if re.search(r"figures-python\s*未使用|figures-diagram\s*未使用", summary_text):
                gate.fail(
                    "Final capability-use audit says visual-asset skills were not used "
                    "for a review/framework final paper."
                )

    # ── 9. Results artifact requirements ──
    has_results = False
    if chapters_path.exists():
        has_results = any(
            re.search(r"Results|results|06_", p.name)
            for p in chapters_path.glob("*.md")
        )

    if has_results:
        required_result_artifacts = [
            "plan/experiment-protocol.md",
            "plan/review/method-experiment-traceability.md",
            "tables/table-schema.md",
            "figures/data-manifest.md",
        ]
        for artifact in required_result_artifacts:
            if not (root / artifact).exists():
                gate.fail(f"Results section exists but {artifact} is missing.")

        overclaim_hits = count_regex(all_chapter_text, RESULT_OVERCLAIM_PATTERN)
        mock_hits = count_regex(all_project_text, r"mock_|synthetic_|PLANNING DATA")
        if overclaim_hits > 0 and mock_hits > 0:
            gate.fail(
                "Results text contains real-result language while mock/synthetic "
                "planning data is present."
            )

    # ── 10. Mock/synthetic file scan ──
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            if re.match(r"^(?:mock_|synthetic_)", fname):
                mock_path = Path(dirpath) / fname
                mock_text = mock_path.read_text(encoding="utf-8", errors="replace")
                if not re.search(r"PLANNING DATA - replace before submission", mock_text):
                    gate.fail(
                        f"Mock/synthetic file lacks required planning-data marker: "
                        f"{mock_path}"
                    )

    # ── 11. Global placeholder summary ──
    chapter_placeholders = count_regex(all_chapter_text, PLACEHOLDER_PATTERN)
    non_chapter_placeholders = count_regex(all_non_chapter_text, PLACEHOLDER_PATTERN)
    total_placeholders = chapter_placeholders + non_chapter_placeholders

    if total_placeholders > 0:
        if submission:
            gate.fail(
                f"Submission mode forbids unresolved placeholders; "
                f"found {total_placeholders}."
            )
        else:
            if chapter_placeholders > 0:
                gate.warn(
                    f"Chapter drafts contain {chapter_placeholders} unresolved placeholder/s."
                )
            if non_chapter_placeholders > 0:
                gate.warn(
                    f"Planning artifacts contain {non_chapter_placeholders} placeholder/s."
                )

    return gate


# ──────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────

def main() -> int:
    # Support both --self-test and -SelfTest, etc.
    # argparse doesn't natively handle -CamelCase well, so we do a manual pre-pass
    args_list = sys.argv[1:]
    normalized: list[str] = []
    for arg in args_list:
        if arg == "-SelfTest":
            normalized.append("--self-test")
        elif arg == "-Submission":
            normalized.append("--submission")
        elif arg == "-ProjectPath":
            normalized.append("--project-path")
        else:
            normalized.append(arg)

    parser = argparse.ArgumentParser(
        description="Research quality gate (Python replacement for .ps1)"
    )
    parser.add_argument(
        "--project-path",
        help="Project root directory to validate",
    )
    parser.add_argument(
        "--submission",
        action="store_true",
        help="Enable submission-mode checks (stricter)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-test to validate regex patterns",
    )
    args = parser.parse_args(normalized)

    if args.self_test:
        return 0 if self_test() else 1

    if not args.project_path:
        print("Error: --project-path is required unless --self-test is used.")
        sys.exit(1)

    root = Path(args.project_path).resolve()
    if not root.exists():
        print(f"Error: project path does not exist: {root}")
        sys.exit(1)

    gate = run_checks(root, args.submission)

    if gate.warnings:
        print("Warnings:")
        for w in gate.warnings:
            print(f" - {w}")

    if gate.failures:
        print("Research quality gate failed:")
        for f in gate.failures:
            print(f" - {f}")
        return 1

    print("Research quality gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
