#!/usr/bin/env python3
"""Strict quality gate for generated paper workspaces.

This gate is intentionally conservative: a paper is not complete when quality
cannot be proven from the current source files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REQUIRED_CHAPTERS = [
    "00-abstract.md",
    "01-introduction.md",
    "02-literature-review.md",
    "03-methodology.md",
    "04-experiments.md",
    "05-results.md",
    "06-discussion.md",
    "07-conclusion.md",
    "08-references.md",
]

REVIEW_FRAMEWORK_CHAPTERS = [
    "00-abstract.md",
    "01-introduction.md",
    "02-literature-framework.md",
    "03-value-creation.md",
    "04-constraints.md",
    "05-pathways-governance.md",
    "06-conclusion.md",
    "08-references.md",
]

# DEAI word lists: import from shared authoritative source
from deai_constants import ABSOLUTE_PATTERNS, LIMITED_PATTERNS, PARAGRAPH_MAX_CHARS, PARAGRAPH_WARN_CHARS

STRONG_EXPERIMENT_CLAIMS = [
    "实验结果表明",
    "全面实验",
    "显著优于",
    "验证了",
    "取得了",
    "达到",
    "优于所有方法",
    "超过SOTA",
    "state-of-the-art",
    "outperforms",
    r"p\s*[<＝=]\s*0\.\d+",
]

REQUIRED_EXPERIMENT_ARTIFACTS = [
    ("plan/experiment-run-manifest.json", "json"),
    ("plan/dataset-verify.json", "json"),
    ("plan/baseline-verify.json", "json"),
    ("plan/literature-search-manifest.jsonl", "jsonl"),
    ("results/raw-metrics.csv", "csv"),
    ("results/statistical-tests.json", "json"),
]

REQUIRED_REVIEW_METHOD_ARTIFACTS = [
    "plan/systematic-review-protocol.md",
    "plan/source-screening-report.md",
    "data/screening-decisions.csv",
    "data/extraction-table.csv",
    "plan/risk-of-bias.md",
    "plan/evidence-grade.md",
    "plan/meta-analysis-decision.md",
]

REVIEW_METHOD_KEYWORDS = {
    "plan/systematic-review-protocol.md": [
        "review question",
        "eligibility",
        "search strategy",
        "outcome",
        "protocol",
    ],
    "plan/source-screening-report.md": [
        "SOURCE_SCREENING_STATUS:",
        "identified",
        "screened",
        "included",
        "excluded",
    ],
    "plan/risk-of-bias.md": [
        "risk of bias",
        "bias",
        "quality assessment",
    ],
    "plan/evidence-grade.md": [
        "grade",
        "certainty",
        "evidence",
    ],
    "plan/meta-analysis-decision.md": [
        "meta-analysis",
        "effect",
        "heterogeneity",
    ],
}

REPORTS_REQUIRING_HASH = [
    "plan/final-quality-gate.md",
    "plan/final-gate-summary.md",
    "plan/quality-gate-final.md",
    "plan/final-review-report.md",
    "plan/review-anti-fabrication.md",
    "plan/post-mandatory-fix-review.md",
]

REQUIRED_FINAL_REPORTS = [
    "plan/final-quality-gate.md",
    "plan/final-gate-summary.md",
    "plan/quality-gate-final.md",
    "plan/final-review-report.md",
    "plan/post-mandatory-fix-review.md",
    "plan/review-anti-fabrication.md",
]

REVIEW_REPORTS = [
    "plan/review-1-academic.md",
    "plan/review-2-technical.md",
    "plan/review-3-writing.md",
    "plan/review-4-journal.md",
    "plan/review-5-advisor.md",
    "plan/review-6-reader.md",
    "plan/review-7-deai.md",
    "plan/review-8-consistency.md",
    "plan/review-9-novelty.md",
    "plan/review-10-reproducibility.md",
]

BLOCKING_FINAL_PATTERNS = [
    ("draft pass marker", r"\bDRAFT\s+PASS\b|STATUS:\s*DRAFT_ONLY|DRAFT[- ]ONLY"),
    ("draft/non-final wording", r"初稿|草稿|不是投稿|不是.*终稿|not\s+(?:a\s+)?(?:final|submission)"),
    ("submission gate failed wording", r"SUBMISSION\s+GATE\s+NOT\s+PASSED|投稿.*未通过|终稿.*未通过"),
    ("skipped verification", r"\bSKIPPED\b|未运行|未执行|跳过"),
    (
        "failed verification table row",
        r"(?m)^\|[^|\n]+\|[^|\n]*(?:FAIL|FAILED|未通过|失败|SKIPPED)[^|\n]*\|",
    ),
    (
        "missing terminal artifact",
        r"(?:missing|缺少|未生成|不存在|not generated|not produced).{0,40}"
        r"(?:main\.tex|main\.pdf|review|评审|quality gate|质量门|LaTeX|PowerShell|pwsh)",
    ),
    (
        "blocked terminal command",
        r"(?:PowerShell|pwsh|strict_quality_gate|research_quality_gate|质量门).{0,80}"
        r"(?:unavailable|missing|not installed|not run|FAIL|FAILED|未安装|不可用|缺少|未运行|失败|未通过)",
    ),
]


from gate_kit import GateResult as Gate  # noqa: E402
from gate_kit import is_review_framework


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def strip_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def markdown_title(text: str) -> str:
    # Prefer the first real paper-title heading over front-matter labels.
    front_matter = {"摘要", "中文摘要", "Abstract", "关键词 Keywords", "关键词", "Keywords"}
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match and match.group(1).strip() not in front_matter:
            return match.group(1).strip()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            candidate = stripped.lstrip("#").strip()
            if candidate not in front_matter:
                return candidate
    return ""


def config_title(root: Path) -> str:
    config = root / "plan" / "auto-config.json"
    if not config.exists():
        return ""
    try:
        data = json.loads(read_text(config))
    except json.JSONDecodeError:
        return ""
    paper_meta = data.get("paper_meta") if isinstance(data, dict) else None
    if isinstance(paper_meta, dict):
        meta_title = paper_meta.get("title_cn") or paper_meta.get("TITLE_CN")
        if isinstance(meta_title, str) and meta_title.strip():
            return meta_title.strip()
    candidates = [
        data.get("TITLE_CN"),
        data.get("title_cn"),
        data.get("title"),
        data.get("PAPER_TITLE"),
        data.get("paper_title"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def paper_meta(root: Path) -> dict:
    config = root / "plan" / "auto-config.json"
    if not config.exists():
        return {}
    try:
        data = json.loads(read_text(config))
    except json.JSONDecodeError:
        return {}
    meta = data.get("paper_meta") if isinstance(data, dict) else None
    return meta if isinstance(meta, dict) else {}




def required_chapters_for(root: Path) -> list[str]:
    architecture = root / "plan" / "chapter-architecture.md"
    if architecture.exists():
        chapters = re.findall(r"`?chapters/([^`\s|]+\.md)`?", read_text(architecture))
        if chapters:
            return chapters
    if is_review_framework(root):
        return REVIEW_FRAMEWORK_CHAPTERS
    return REQUIRED_CHAPTERS


def paper_title(root: Path, text: str) -> str:
    return config_title(root) or markdown_title(text)


def strip_heading_number(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\d+(?:\.\d+)*\s+", "", text)
    text = re.sub(r"^第[一二三四五六七八九十]+章\s*", "", text)
    text = re.sub(r"^[（(]?[一二三四五六七八九十]+[）)]?[、.．]?\s*", "", text)
    return text.strip()


def rendered_heading_candidates(heading: str) -> set[str]:
    stripped = heading.strip()
    clean = strip_heading_number(stripped)
    candidates = {stripped, clean}
    front_map = {
        "摘要": "awardabstracttitle",
        "中文摘要": "awardabstracttitle",
        "Abstract": "Abstract",
        "关键词 Keywords": "关键词",
        "关键词": "关键词",
    }
    if clean in front_map:
        candidates.add(front_map[clean])
    return {candidate for candidate in candidates if candidate}


def is_bilingual_caption(caption: str) -> bool:
    parts = re.split(r"\\\\|\\n|\n", caption)
    has_cjk = any(len(re.findall(r"[\u4e00-\u9fff]", part)) >= 4 for part in parts)
    english_parts = [part for part in parts if re.search(r"[A-Za-z]{3,}", part)]
    has_english = any(len(re.findall(r"[A-Za-z]{3,}", part)) >= 3 for part in english_parts)
    return has_cjk and has_english


def final_report_status(text: str) -> str:
    matches = re.findall(r"STATUS:\s*(PASS|FAIL|NEED_RETRY|MANUAL_REQUIRED)", text, flags=re.I)
    if matches:
        return matches[-1].upper()
    if re.search(r"(?:TECHNICAL_GATE_STATUS|QUALITY_GATE_STATUS):\s*RECORDED", text, re.I) and re.search(
        r"全部PASS|整体[：:]\s*PASS|是否达标[：:]\s*(是|PASS)",
        text,
        re.I,
    ):
        return "PASS"
    return ""


def report_has_failure_status(text: str) -> bool:
    return bool(
        re.search(
            r"STATUS:\s*(FAIL|NEED_RETRY|MANUAL_REQUIRED)|整体[：:]\s*FAIL|是否达标[：:]\s*(否|FAIL)",
            text,
            re.I,
        )
    )


def blocking_final_findings(text: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in BLOCKING_FINAL_PATTERNS:
        if re.search(pattern, text, re.I | re.M):
            findings.append(label)
    return findings


def extract_quoted_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    for match in re.finditer(r'"([^"\n]{20,})"', text):
        fragments.append(match.group(1).strip())
    for match in re.finditer(r"“([^”\n]{20,})”", text):
        fragments.append(match.group(1).strip())
    return fragments


def fragment_in_text(fragment: str, text: str) -> bool:
    normalized_fragment = normalize_text(fragment)
    if not normalized_fragment:
        return False
    return normalized_fragment in normalize_text(text)


def compact_number(value: str) -> str:
    return re.sub(r"\.0+$", "", value.strip())


def csv_metric_values(path: Path) -> list[str]:
    values: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw = (row.get("value") or "").strip()
            if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
                values.append(raw)
    return values


def read_json(path: Path) -> object:
    return json.loads(read_text(path))


def non_empty_list(value: object) -> bool:
    return isinstance(value, list) and bool(value)


def non_empty_dict(value: object) -> bool:
    return isinstance(value, dict) and bool(value)


def valid_url(value: str) -> bool:
    return bool(re.match(r"https?://[^\s]+", value))


def count_markdown_tables(text: str) -> int:
    table_count = 0
    in_table = False
    for line in text.splitlines():
        is_table_line = line.strip().startswith("|") and line.strip().endswith("|")
        if is_table_line and not in_table:
            table_count += 1
        in_table = is_table_line
    return table_count


def markdown_figures(text: str) -> list[tuple[str, str]]:
    return re.findall(r"!\[(.*?)\]\((.*?)\)", text)


def count_data_rows(path: Path) -> int:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.reader(handle))
        return max(0, len([row for row in rows if any(cell.strip() for cell in row)]) - 1)
    if path.suffix.lower() == ".json":
        data = read_json(path)
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ["records", "data", "items", "sources", "rows"]:
                value = data.get(key)
                if isinstance(value, list):
                    return len(value)
            return len(data)
    return 0


def check_review_framework_assets(root: Path, text: str, gate: Gate) -> None:
    """Review/framework papers still need source-backed data and visual assets.

    This is not an experiment gate. It prevents a literature/framework paper from
    passing as final when it has only prose plus references and no inspectable
    evidence tables, derived data files, or figures.
    """

    if not is_review_framework(root):
        return

    figures = markdown_figures(text)
    if len(figures) < 1:
        gate.fail("review/framework paper has no referenced figure; expected at least one source-backed framework or evidence figure")
    else:
        gate.pass_(f"review/framework referenced figures: {len(figures)}")

    table_count = count_markdown_tables(text)
    if table_count < 2:
        gate.fail(f"review/framework paper has too few markdown tables: {table_count}; expected at least 2 evidence/industry tables")
    else:
        gate.pass_(f"review/framework markdown tables: {table_count}")

    asset_plan = root / "plan" / "review-framework-asset-plan.md"
    if not asset_plan.exists():
        gate.fail("missing plan/review-framework-asset-plan.md for review/framework paper")
    else:
        asset_text = read_text(asset_plan)
        if "Figure" not in asset_text and "图" not in asset_text:
            gate.fail("plan/review-framework-asset-plan.md does not list any figure asset")
        elif "Table" not in asset_text and "表" not in asset_text:
            gate.fail("plan/review-framework-asset-plan.md does not list any table asset")
        else:
            gate.pass_("review/framework asset plan lists figure and table assets")

    manifest = root / "figures" / "data-manifest.md"
    if not manifest.exists():
        gate.fail("missing figures/data-manifest.md for review/framework visual assets")
    else:
        manifest_text = read_text(manifest)
        if "mock_" in manifest_text or "synthetic_" in manifest_text or "PLANNING DATA" in manifest_text:
            gate.fail("review/framework figures/data-manifest.md contains mock/synthetic planning data")
        elif len([line for line in manifest_text.splitlines() if line.strip().startswith("|")]) < 3:
            gate.fail("figures/data-manifest.md has no substantive manifest rows")
        else:
            gate.pass_("figures/data-manifest.md contains non-mock manifest rows")

    data_roots = [root / "data", root / "figures" / "data"]
    data_files = [
        path
        for data_root in data_roots
        if data_root.exists()
        for path in data_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".csv", ".json"}
    ]
    if not data_files:
        gate.fail("review/framework paper has no source-backed CSV/JSON data files under data/ or figures/data/")
    else:
        row_failures = []
        for path in data_files:
            if re.match(r"^(mock_|synthetic_)", path.name):
                row_failures.append(f"{path.relative_to(root)} is mock/synthetic")
                continue
            try:
                rows = count_data_rows(path)
            except (json.JSONDecodeError, csv.Error) as exc:
                row_failures.append(f"{path.relative_to(root)} cannot be parsed: {exc}")
                continue
            if rows < 3:
                row_failures.append(f"{path.relative_to(root)} has fewer than 3 data rows")
        if row_failures:
            gate.fail("review/framework data assets are not substantive: " + "; ".join(row_failures[:5]))
        else:
            gate.pass_(f"review/framework data asset files: {len(data_files)}")

    figure_scripts = list((root / "figures").rglob("*.py")) if (root / "figures").exists() else []
    if not figure_scripts:
        gate.fail("review/framework paper has no figure-generation script under figures/")
    else:
        gate.pass_(f"review/framework figure-generation scripts: {len(figure_scripts)}")

    for _, target in figures:
        figure_path = root / target
        svg_path = figure_path.with_suffix(".svg")
        if figure_path.suffix.lower() == ".png" and not svg_path.exists():
            gate.fail(f"referenced figure lacks companion SVG: {svg_path.relative_to(root)}")
        elif figure_path.suffix.lower() == ".png":
            gate.pass_(f"referenced figure companion SVG exists: {svg_path.relative_to(root)}")

    final_summary = root / "plan" / "final-gate-summary.md"
    if final_summary.exists():
        summary_text = read_text(final_summary)
        if re.search(r"figures-python\s*未使用|figures-diagram\s*未使用", summary_text):
            gate.fail("final capability-use audit says visual-asset skills were not used for a review/framework final paper")


def csv_columns(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return set()
    return {cell.strip().lower() for cell in header if cell.strip()}


def csv_non_empty_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    return max(0, len([row for row in rows[1:] if any(cell.strip() for cell in row)]))


def contains_all_keywords(path: Path, keywords: list[str]) -> list[str]:
    text = read_text(path).lower()
    return [keyword for keyword in keywords if keyword.lower() not in text]


def check_review_methodology_gate(root: Path, text: str, gate: Gate) -> None:
    """Require top-tier review traceability for review/framework finals.

    The existing asset gate proves that a manuscript has references, tables and
    figures. That is not enough for a final review paper. A top-tier review must
    expose how sources were searched, screened, extracted, judged for bias and
    synthesized, or it is only a narrative draft.
    """

    if not is_review_framework(root):
        return

    missing_artifacts = [rel for rel in REQUIRED_REVIEW_METHOD_ARTIFACTS if not (root / rel).exists()]
    if missing_artifacts:
        gate.fail("review/framework final lacks top-tier methodology artifact(s): " + ", ".join(missing_artifacts))
    else:
        gate.pass_("review/framework top-tier methodology artifacts exist")

    for rel, keywords in REVIEW_METHOD_KEYWORDS.items():
        path = root / rel
        if not path.exists():
            continue
        missing_keywords = contains_all_keywords(path, keywords)
        if missing_keywords:
            gate.fail(f"{rel} lacks methodology marker(s): {missing_keywords}")
        else:
            gate.pass_(f"{rel} contains required methodology markers")

    screening = root / "data" / "screening-decisions.csv"
    if screening.exists():
        columns = csv_columns(screening)
        required = {"source_id", "title", "decision", "reason"}
        missing = sorted(required - columns)
        rows = csv_non_empty_rows(screening)
        if missing:
            gate.fail(f"data/screening-decisions.csv missing required column(s): {missing}")
        elif rows < 20:
            gate.fail(f"data/screening-decisions.csv has too few screened records for a final review: {rows}")
        else:
            gate.pass_(f"screening decisions are machine-readable: {rows} rows")

    extraction = root / "data" / "extraction-table.csv"
    if extraction.exists():
        columns = csv_columns(extraction)
        required = {"source_id", "study_design", "population", "exposure", "outcome"}
        missing = sorted(required - columns)
        rows = csv_non_empty_rows(extraction)
        has_synthesis_column = bool({"effect_size", "effect", "estimate", "finding"} & columns)
        if missing:
            gate.fail(f"data/extraction-table.csv missing required column(s): {missing}")
        elif not has_synthesis_column:
            gate.fail("data/extraction-table.csv lacks effect_size/effect/estimate/finding column")
        elif rows < 10:
            gate.fail(f"data/extraction-table.csv has too few extracted studies for a final review: {rows}")
        else:
            gate.pass_(f"extraction table is machine-readable: {rows} rows")

    prisma_png = root / "figures" / "prisma_flow.png"
    prisma_svg = root / "figures" / "prisma_flow.svg"
    if not prisma_png.exists() or not prisma_svg.exists():
        gate.fail("review/framework final lacks paired PRISMA flow figure: figures/prisma_flow.png and figures/prisma_flow.svg")
    elif "prisma_flow" not in text and "PRISMA" not in text:
        gate.fail("PRISMA flow figure exists but is not referenced in full-paper.md")
    else:
        gate.pass_("paired PRISMA flow figure exists and is referenced")

    evidence_map = root / "plan" / "evidence-map.md"
    if evidence_map.exists():
        evidence_text = read_text(evidence_map)
        metadata_hits = len(re.findall(r"\bmetadata-only\b", evidence_text, flags=re.I))
        if metadata_hits:
            gate.fail(
                "review/framework final still relies on metadata-only evidence-map row(s): "
                f"{metadata_hits}; final reviews require abstract/full-text verification"
            )
        else:
            gate.pass_("evidence map has no metadata-only rows")

    method_terms = [
        ("纳入标准|inclusion criteria", "inclusion criteria"),
        ("排除标准|exclusion criteria", "exclusion criteria"),
        ("筛选|screening", "screening"),
        ("提取|extraction", "extraction"),
        ("偏倚|risk of bias", "risk-of-bias assessment"),
        ("GRADE|证据等级|certainty", "evidence grading"),
        ("PRISMA", "PRISMA reporting"),
    ]
    missing_terms = [label for pattern, label in method_terms if not re.search(pattern, text, re.I)]
    if missing_terms:
        gate.fail("full-paper.md lacks top-tier review method term(s): " + ", ".join(missing_terms))
    else:
        gate.pass_("full-paper.md includes top-tier review methodology terms")


def png_dpi(path: Path) -> tuple[float, float] | None:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos = 8
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"pHYs" and len(chunk_data) == 9:
            x_ppu = int.from_bytes(chunk_data[0:4], "big")
            y_ppu = int.from_bytes(chunk_data[4:8], "big")
            unit = chunk_data[8]
            if unit == 1:
                return (x_ppu * 0.0254, y_ppu * 0.0254)
            return None
        if chunk_type == b"IEND":
            break
    return None


def png_dimensions(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
        return None
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


def prose_paragraphs(text: str) -> list[tuple[int, str]]:
    text = strip_code_blocks(text)
    paragraphs: list[tuple[int, str]] = []
    current: list[str] = []
    start = 1
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            if current:
                paragraphs.append((start, "\n".join(current)))
                current = []
            start = lineno + 1
            continue
        if not current:
            start = lineno
        current.append(line)
    if current:
        paragraphs.append((start, "\n".join(current)))
    filtered: list[tuple[int, str]] = []
    for lineno, para in paragraphs:
        stripped = para.strip()
        if (
            stripped.startswith("#")
            or stripped.startswith("|")
            or stripped.startswith("![")
            or stripped.startswith("- ")
            or stripped.startswith("* ")
            or re.match(r"^\d+\.", stripped)
        ):
            continue
        filtered.append((lineno, para))
    return filtered


def check_structure(root: Path, gate: Gate) -> str:
    full = root / "full-paper.md"
    if not full.exists():
        gate.fail("missing full-paper.md")
        return ""
    text = read_text(full)
    gate.pass_("full-paper.md exists")

    chapters_dir = root / "chapters"
    required_chapters = required_chapters_for(root)
    for chapter in required_chapters:
        chapter_path = chapters_dir / chapter
        if chapter_path.exists():
            gate.pass_(f"chapter exists: {chapter}")
        else:
            gate.fail(f"missing chapter: chapters/{chapter}")
    if chapters_dir.exists():
        actual = sorted(path.name for path in chapters_dir.glob("*.md"))
        extra = sorted(set(actual) - set(required_chapters))
        if extra:
            gate.fail(f"unexpected chapter file(s) not in architecture: {extra}")
        elif actual:
            gate.pass_("chapter files match required architecture")

    headings = re.findall(r"^#{1,6}\s+", text, flags=re.M)
    if len(headings) >= 8:
        gate.pass_(f"full-paper heading count: {len(headings)}")
    else:
        gate.fail(f"full-paper has too few top-level headings: {len(headings)}")
    return text


def check_project_identity(root: Path, text: str, full_hash: str, gate: Gate) -> None:
    title = paper_title(root, text)
    if title:
        gate.pass_(f"full-paper title detected: {title}")
    else:
        gate.fail("full-paper title could not be detected")

    expected_title = config_title(root)
    if expected_title:
        if normalize_text(expected_title) in normalize_text(title):
            gate.pass_("plan/auto-config.json title matches full-paper title")
        else:
            gate.fail(
                "plan/auto-config.json title does not match full-paper title: "
                f"config='{expected_title}' full-paper='{title}'"
            )
    else:
        gate.warn("plan/auto-config.json title not available; title identity check skipped")

    identity_reports = [
        "plan/final-quality-gate.md",
        "plan/final-review-report.md",
        "plan/review-anti-fabrication.md",
    ]
    output_aliases = {str(root)}
    root_text = str(root)
    if root_text.startswith("/private/var/"):
        output_aliases.add(root_text.replace("/private/var/", "/var/", 1))
    elif root_text.startswith("/var/"):
        output_aliases.add(root_text.replace("/var/", "/private/var/", 1))
    for rel in identity_reports:
        path = root / rel
        if not path.exists():
            continue
        report = read_text(path)
        if full_hash not in report:
            gate.fail(f"{rel} is not bound to current full-paper hash")
        elif title and normalize_text(title) not in normalize_text(report):
            gate.fail(f"{rel} is not bound to current full-paper title")
        elif not any(alias in report for alias in output_aliases):
            gate.fail(f"{rel} is not bound to current OUTPUT path")
        else:
            gate.pass_(f"{rel} identity matches current paper")


def check_style(text: str, gate: Gate) -> None:
    for pattern in ABSOLUTE_PATTERNS:
        hits = re.findall(pattern, text)
        if hits:
            gate.fail(f"absolute banned pattern '{pattern}' hit {len(hits)} time(s)")
        else:
            gate.pass_(f"absolute banned pattern '{pattern}': 0")

    for pattern, limit in LIMITED_PATTERNS:
        hits = re.findall(pattern, text)
        if len(hits) > limit:
            gate.fail(f"limited pattern '{pattern}' hit {len(hits)} time(s), limit {limit}")
        else:
            gate.pass_(f"limited pattern '{pattern}': {len(hits)} <= {limit}")

    long_paragraphs = []
    warn_paragraphs = []
    for lineno, para in prose_paragraphs(text):
        char_count = len(re.sub(r"\s+", "", para))
        if char_count > PARAGRAPH_MAX_CHARS:
            long_paragraphs.append((lineno, char_count))
        elif char_count > PARAGRAPH_WARN_CHARS:
            warn_paragraphs.append((lineno, char_count))
    if long_paragraphs:
        preview = ", ".join(f"line {line}: {count}" for line, count in long_paragraphs[:10])
        gate.fail(f"paragraphs over {PARAGRAPH_MAX_CHARS} chars: {len(long_paragraphs)} ({preview})")
    else:
        gate.pass_(f"all prose paragraphs <= {PARAGRAPH_MAX_CHARS} chars")
    if warn_paragraphs:
        preview = ", ".join(f"line {line}: {count}" for line, count in warn_paragraphs[:10])
        gate.warn(f"paragraphs over {PARAGRAPH_WARN_CHARS} chars (auto-fixable): {len(warn_paragraphs)} ({preview})")

    prose_bold = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if ("**" in line or "__" in line) and not stripped.startswith("|"):
            prose_bold.append(lineno)
    if prose_bold:
        gate.fail(f"prose bold markers found on line(s): {prose_bold[:20]}")
    else:
        gate.pass_("no prose bold markers outside tables")

    paragraphs = [
        normalize_text(para)
        for _, para in prose_paragraphs(text)
        if len(normalize_text(para)) >= 60
    ]
    repeated: dict[str, int] = {}
    for para in paragraphs:
        repeated[para] = repeated.get(para, 0) + 1
    duplicates = [(para, count) for para, count in repeated.items() if count > 1]
    if duplicates:
        preview = [para[:40] for para, _ in duplicates[:5]]
        gate.fail(f"repeated prose paragraphs found: {len(duplicates)} ({preview})")
    else:
        gate.pass_("no repeated prose paragraphs")

    repeated_phrase = "该章节还需要把证据边界落实到可操作对象"
    phrase_hits = text.count(repeated_phrase)
    if phrase_hits > 1:
        gate.fail(f"mechanical filler phrase repeated {phrase_hits} times: {repeated_phrase}")
    else:
        gate.pass_("mechanical filler phrase repetition check passed")


def check_references(root: Path, text: str, gate: Gate) -> None:
    refs_bib = root / "references.bib"
    if not refs_bib.exists():
        gate.fail("missing references.bib")
    else:
        bib_text = read_text(refs_bib)
        count = len(re.findall(r"^@", bib_text, flags=re.M))
        if count >= 30:
            gate.pass_(f"references.bib entries: {count}")
        else:
            gate.fail(f"references.bib entries below 30: {count}")

        # DOI coverage check: at least 70% of entries should have a DOI
        doi_count = len(re.findall(r"(?m)^\s*doi\s*=", bib_text, re.IGNORECASE))
        if count > 0:
            doi_ratio = doi_count / count
            if doi_ratio < 0.7:
                gate.fail(f"DOI coverage too low: {doi_count}/{count} ({doi_ratio:.0%}), minimum 70%")
            else:
                gate.pass_(f"DOI coverage: {doi_count}/{count} ({doi_ratio:.0%})")

        # DOI format validation: check that DOI values match valid format
        doi_values = re.findall(r"(?m)^\s*doi\s*=\s*\{?\s*(10\.\S+?)[\s\},]?$", bib_text, re.IGNORECASE)
        doi_pattern = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")
        invalid_dois = [d for d in doi_values if not doi_pattern.match(d.strip())]
        if invalid_dois:
            gate.warn(f"DOI format issues ({len(invalid_dois)}): {invalid_dois[:3]}")
        elif doi_values:
            gate.pass_(f"DOI format validation: {len(doi_values)} DOIs checked, all valid")

    ref_heading = re.search(r"^#\s*(参考文献|References)\s*$", text, flags=re.M)
    body = text[: ref_heading.start()] if ref_heading else text
    refs = text[ref_heading.start() :] if ref_heading else ""
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", body)}
    listed = {int(n) for n in re.findall(r"(?m)^\[(\d+)\]", refs)}
    if not cited:
        gate.fail("no numeric citations found before references")
    elif cited - listed:
        gate.fail(f"citations without listed references: {sorted(cited - listed)}")
    elif listed - cited:
        gate.fail(f"listed references not cited in body: {sorted(listed - cited)}")
    else:
        gate.pass_(f"numeric citations and listed references match: {len(cited)}")

    chapter_refs = root / "chapters" / "08-references.md"
    if chapter_refs.exists() and refs:
        chapter_text = read_text(chapter_refs)
        chapter_numbers = {int(n) for n in re.findall(r"(?m)^\[(\d+)\]", chapter_text)}
        if chapter_numbers != listed:
            gate.fail("chapters/08-references.md numbering differs from full-paper references")
        else:
            gate.pass_("chapter references numbering matches full-paper")
        full_ref_lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in refs.splitlines()
            if re.match(r"^\[\d+\]", line.strip())
        ]
        chapter_ref_lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in chapter_text.splitlines()
            if re.match(r"^\[\d+\]", line.strip())
        ]
        if full_ref_lines != chapter_ref_lines:
            gate.fail("chapters/08-references.md reference entries differ from full-paper references")
        else:
            gate.pass_("chapter reference entries match full-paper")


def check_single_source(root: Path, full_hash: str, gate: Gate) -> None:
    main_tex = root / "main.tex"
    if not main_tex.exists():
        gate.fail("missing main.tex")
        return
    tex = read_text(main_tex)
    script_path = Path(__file__).resolve().parent / "render_latex.py"
    if script_path.exists():
        with tempfile.TemporaryDirectory(prefix="strict-render-") as tmp:
            expected_tex = Path(tmp) / "main.tex"
            expected_manifest = Path(tmp) / "latex-render-manifest.json"
            try:
                subprocess.run(
                    [sys.executable, str(script_path), str(root), "--tex-out", str(expected_tex), "--manifest-out", str(expected_manifest)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                expected = read_text(expected_tex)
                if expected == tex:
                    gate.pass_("main.tex exactly matches deterministic render output")
                else:
                    gate.fail("main.tex differs from deterministic render output")
            except subprocess.CalledProcessError as exc:
                gate.fail(f"deterministic LaTeX render check failed: {exc.stderr.strip()}")
    else:
        gate.fail(f"missing deterministic renderer: {script_path}")
    hash_patterns = [
        f"Source full-paper sha256: {full_hash}",
        f"full-paper-sha256: {full_hash}",
        f"source_hash: {full_hash}",
    ]
    if any(pattern in tex for pattern in hash_patterns):
        gate.pass_("main.tex carries current full-paper source hash")
    else:
        gate.fail("main.tex lacks current full-paper source hash; single-source regeneration is unproven")

    manifest_path = root / "plan" / "latex-render-manifest.json"
    if not manifest_path.exists():
        gate.fail("missing plan/latex-render-manifest.json")
    else:
        try:
            manifest = json.loads(read_text(manifest_path))
        except json.JSONDecodeError:
            gate.fail("plan/latex-render-manifest.json is not valid JSON")
        else:
            if manifest.get("source_hash") == full_hash:
                gate.pass_("latex render manifest source hash matches full-paper")
            else:
                gate.fail("latex render manifest source hash does not match full-paper")
            if manifest.get("template") == "cn-award-paper-v1":
                gate.pass_("latex render manifest uses cn-award-paper-v1 template")
            else:
                gate.fail("latex render manifest does not use cn-award-paper-v1 template")

    required_layout_tokens = [
        r"\begin{titlepage}",
        r"\tableofcontents",
        r"\pagenumbering{Roman}",
        r"\pagenumbering{arabic}",
        r"\ctexset{section=",
        r"\fancyhead[C]",
        r"\awardabstracttitle",
    ]
    missing_layout_tokens = [token for token in required_layout_tokens if token not in tex]
    if missing_layout_tokens:
        gate.fail(f"main.tex missing required award-layout token(s): {missing_layout_tokens}")
    else:
        gate.pass_("main.tex contains required award-paper layout structure")

    log_path = root / "main.log"
    if log_path.exists():
        log_text = read_text(log_path)
        bad_log_patterns = [
            r"^!",
            r"Undefined control sequence",
            r"Missing \$ inserted",
            r"undefined citations",
            r"Overfull \\hbox",
            r"Missing character:",
        ]
        hits = [pattern for pattern in bad_log_patterns if re.search(pattern, log_text, re.I | re.M)]
        if hits:
            gate.fail(f"main.log contains LaTeX layout/compile warning pattern(s): {hits}")
        else:
            gate.pass_("main.log has no hard LaTeX layout warning patterns")
    else:
        gate.fail("missing main.log for LaTeX layout verification")

    blg_path = root / "main.blg"
    if blg_path.exists():
        blg_text = read_text(blg_path)
        if re.search(r"(error message|I found no \\bibdata|I found no \\bibstyle)", blg_text, re.I):
            gate.fail("main.blg contains BibTeX error messages")
        else:
            gate.pass_("main.blg has no BibTeX error messages")

    for rel in ["main.tex", "main.log", "main.pdf"]:
        path = root / rel
        if path.exists() and path.stat().st_mtime + 1 < (root / "full-paper.md").stat().st_mtime:
            gate.fail(f"{rel} is older than full-paper.md; output may be stale")
    tex_mtime = (root / "main.tex").stat().st_mtime if (root / "main.tex").exists() else 0
    if log_path.exists() and log_path.stat().st_mtime + 1 < tex_mtime:
        gate.fail("main.log is older than main.tex; compile evidence is stale")

    full_text = read_text(root / "full-paper.md")
    md_headings = [
        re.sub(r"\s+", " ", heading).strip()
        for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", full_text, flags=re.M)
    ]
    tex_body = tex.split(r"\begin{document}", 1)[1] if r"\begin{document}" in tex else tex
    tex_normalized = normalize_text(tex_body)
    missing_headings = [
        heading for heading in md_headings
        if normalize_text(heading)
        and not any(normalize_text(candidate) in tex_normalized for candidate in rendered_heading_candidates(heading))
    ]
    if missing_headings:
        gate.fail(f"main.tex missing full-paper heading(s): {missing_headings[:10]}")
    else:
        gate.pass_("main.tex contains all markdown headings")

    md_figures = markdown_figures(full_text)
    tex_graphics = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
    if len(tex_graphics) < len(md_figures):
        gate.fail(f"main.tex has fewer graphics than full-paper: {len(tex_graphics)} < {len(md_figures)}")
    else:
        gate.pass_(f"main.tex graphics count covers full-paper figures: {len(tex_graphics)} >= {len(md_figures)}")

    for caption, target in md_figures:
        figure_path = root / target
        if not figure_path.exists():
            gate.fail(f"referenced figure missing: {target}")
            continue
        dims = png_dimensions(figure_path)
        dpi = png_dpi(figure_path)
        if dims is None:
            gate.fail(f"referenced figure is not a valid PNG: {target}")
        elif dims[0] < 1000 or dims[1] < 700:
            gate.fail(f"figure resolution too low: {target} {dims[0]}x{dims[1]}")
        else:
            gate.pass_(f"figure pixel resolution ok: {target} {dims[0]}x{dims[1]}")
        if dpi is None:
            gate.fail(f"figure missing physical DPI metadata: {target}")
        elif dpi[0] < 450 or dpi[1] < 450:
            gate.fail(f"figure DPI below 450: {target} {dpi[0]:.1f}x{dpi[1]:.1f}")
        else:
            gate.pass_(f"figure DPI ok: {target} {dpi[0]:.1f}x{dpi[1]:.1f}")
        if not is_bilingual_caption(caption):
            gate.fail(f"figure caption is not bilingual: {target}")

    figure_targets = {target for _, target in md_figures}
    for figure_file in (root / "figures").glob("*.png") if (root / "figures").exists() else []:
        rel = str(figure_file.relative_to(root))
        if rel not in figure_targets and rel not in tex_graphics:
            gate.fail(f"unreferenced figure asset: {rel}")

    md_tables = count_markdown_tables(full_text)
    tex_tables = len(re.findall(r"\\begin\{tabular\}", tex))
    table_envs = re.findall(r"\\begin\{table\}\[H\](.*?)\\end\{table\}", tex, flags=re.S)
    tables_without_caption = [idx + 1 for idx, block in enumerate(table_envs) if r"\caption{" not in block]
    weak_table_captions = []
    for idx, block in enumerate(table_envs, start=1):
        caption_match = re.search(r"\\caption\{(.+?)\}", block, flags=re.S)
        if not caption_match:
            continue
        caption = caption_match.group(1)
        if not is_bilingual_caption(caption) or re.fullmatch(r"\s*表\s*\d+\s*\\\\\s*Table\s*\d+\s*", caption, re.I):
            weak_table_captions.append(idx)
    if tables_without_caption:
        gate.fail(f"table environment(s) without captions: {tables_without_caption}")
    elif weak_table_captions:
        gate.fail(f"table caption(s) are not informative bilingual captions: {weak_table_captions}")
    elif table_envs:
        gate.pass_("all table environments have informative bilingual captions")
    if md_tables > 0 and tex_tables == 0:
        gate.fail("full-paper contains markdown tables but main.tex has no tabular blocks")
    elif tex_tables < md_tables and md_tables > 0:
        gate.fail(f"main.tex table count looks too low for markdown tables: tabular={tex_tables}, markdown_tables={md_tables}")
    else:
        gate.pass_("main.tex table rendering is present when markdown tables exist")

    pdf = root / "main.pdf"
    if not pdf.exists():
        gate.fail("missing main.pdf")
    elif pdf.stat().st_size <= 102400:
        gate.fail(f"main.pdf too small: {pdf.stat().st_size} bytes")
    else:
        gate.pass_(f"main.pdf exists and is >100KB: {pdf.stat().st_size} bytes")
        if tex_mtime and pdf.stat().st_mtime + 1 < tex_mtime:
            gate.fail("main.pdf is older than main.tex; PDF is stale")
        if log_path.exists():
            if pdf.stat().st_mtime + 1 < log_path.stat().st_mtime:
                gate.fail("main.pdf is older than main.log; PDF compile artifact is stale")
            log_text = read_text(log_path)
            pdf_compile_evidence = (
                "Output written on main.pdf" in log_text
                or (
                    "Output written on main.xdv" in log_text
                    and pdf.exists()
                    and pdf.stat().st_mtime + 1 >= log_path.stat().st_mtime
                )
                or re.search(r"main\.xdv\s*->\s*main\.pdf", log_text)
                or re.search(r"All targets \(.*main\.pdf.*\) are up-to-date", log_text)
            )
            if not pdf_compile_evidence:
                gate.fail("main.log lacks successful main.pdf compile evidence")
        try:
            pdf_text = subprocess.run(
                ["pdftotext", str(pdf), "-"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            if "�" in pdf_text:
                gate.fail("main.pdf text contains replacement character(s)")
            else:
                gate.pass_("main.pdf text has no replacement characters")
            title = paper_title(root, full_text)
            required_pdf_terms = [term for term in [title, "摘要", "引言", "参考文献"] if term]
            missing_pdf_terms = [term for term in required_pdf_terms if normalize_text(term) not in normalize_text(pdf_text)]
            if missing_pdf_terms:
                gate.fail(f"main.pdf text missing required paper terms: {missing_pdf_terms}")
            else:
                gate.pass_("main.pdf text contains title and core sections")
            prose_anchors = []
            for _, para in prose_paragraphs(full_text):
                clean = normalize_text(re.sub(r"\[[0-9]+\]", "", para))
                if len(clean) >= 80:
                    prose_anchors.append(clean[:45])
                if len(prose_anchors) >= 8:
                    break
            matched_anchors = [anchor for anchor in prose_anchors if anchor in normalize_text(pdf_text)]
            if len(matched_anchors) < min(5, len(prose_anchors)):
                gate.fail("main.pdf text does not match enough full-paper prose anchors")
            else:
                gate.pass_("main.pdf text matches full-paper prose anchors")
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            gate.fail(f"pdftotext verification failed in strict mode: {exc}")

    final_pdf = root / "main.final.pdf"
    if final_pdf.exists():
        final_status = root / "plan" / "final-gate-summary.md"
        final_text = read_text(final_status) if final_status.exists() else ""
        state_ready = False
        status_path = root / "plan" / "status.json"
        if status_path.exists():
            try:
                status_payload = json.loads(read_text(status_path))
            except json.JSONDecodeError:
                status_payload = {}
            if isinstance(status_payload, dict) and status_payload.get("status") == "SUBMISSION_PACKAGE_READY":
                hashes = status_payload.get("last_artifact_hashes", {})
                signoff_hashes = status_payload.get("human_signoff_hashes", {})
                current_hash = sha256(final_pdf)
                state_ready = (
                    isinstance(hashes, dict)
                    and isinstance(signoff_hashes, dict)
                    and hashes.get("main.final.pdf") == current_hash
                    and signoff_hashes.get("main.final.pdf") == current_hash
                )
        if state_ready:
            gate.pass_("main.final.pdf is present with SUBMISSION_PACKAGE_READY hash evidence")
        elif (
            not final_status.exists()
            or final_report_status(final_text) != "PASS"
            or re.search(r"STATUS:\s*(FAIL|NEED_RETRY|MANUAL_REQUIRED)", final_text, re.I)
        ):
            gate.fail("main.final.pdf exists without final PASS evidence")
        else:
            gate.pass_("main.final.pdf is present only with final PASS evidence")


def check_report_hashes(root: Path, full_hash: str, gate: Gate) -> None:
    review_mode = is_review_framework(root)
    required_final_reports = [
        "plan/final-quality-gate.md",
        "plan/final-gate-summary.md",
        "plan/quality-gate-final.md",
        "plan/final-review-report.md",
        "plan/post-mandatory-fix-review.md",
        "plan/review-anti-fabrication.md",
    ]
    if review_mode:
        required_final_reports = [
            "plan/final-quality-gate.md",
            "plan/final-gate-summary.md",
            "plan/quality-gate-final.md",
            "plan/final-review-report.md",
            "plan/review-anti-fabrication.md",
        ]
    for rel in required_final_reports:
        if not (root / rel).exists():
            gate.fail(f"missing required final report: {rel}")
    for rel in REPORTS_REQUIRING_HASH:
        path = root / rel
        if not path.exists():
            continue
        text = read_text(path)
        if full_hash in text:
            gate.pass_(f"report hash matches: {rel}")
        else:
            gate.fail(f"report missing current source hash: {rel}")
        blocking_findings = blocking_final_findings(text)
        if final_report_status(text) == "PASS" and blocking_findings:
            gate.fail(
                f"{rel} uses STATUS: PASS while recording blocking/non-final evidence: "
                + ", ".join(blocking_findings[:5])
            )

    final_gate = root / "plan" / "final-quality-gate.md"
    anti_fab = root / "plan" / "review-anti-fabrication.md"
    pass_pattern = re.compile(
        r"TECHNICAL_GATE_STATUS:\s*RECORDED|QUALITY_GATE_STATUS:\s*RECORDED|"
        r"整体[：:]\s*PASS|是否达标[：:]\s*(是|PASS)|全部PASS",
        re.I,
    )
    fail_pattern = re.compile(
        r"STATUS:\s*(FAIL|NEED_RETRY|MANUAL_REQUIRED)|整体[：:]\s*FAIL|是否达标[：:]\s*(否|FAIL)",
        re.I,
    )
    required_dependency_reports = [
        "plan/deai-quantitative-report.md",
        "plan/consistency-verify.md",
    ]
    if not review_mode:
        required_dependency_reports.append("plan/experiment-design-validation.md")
    for rel in required_dependency_reports:
        path = root / rel
        if not path.exists():
            gate.fail(f"missing required dependency report: {rel}")
            continue
        text = read_text(path)
        if full_hash not in text:
            gate.fail(f"{rel} missing current source hash")
        elif fail_pattern.search(text):
            gate.fail(f"{rel} contains failure status")
        elif re.search(r"STATUS:\s*PASS|全部PASS|无FAIL项|评分[：:]\s*(8[5-9]|9\d|100)", text, re.I):
            gate.pass_(f"{rel} has current-hash PASS evidence")
        else:
            gate.fail(f"{rel} lacks current-hash PASS evidence")

    if final_gate.exists():
        text = read_text(final_gate)
        score_match = re.search(r"(?:综合评分|总分|Overall)[：:\s]+([0-9]+(?:\.[0-9]+)?)", text, re.I)
        if not score_match:
            gate.fail("plan/final-quality-gate.md lacks machine-readable score")
        elif float(score_match.group(1)) >= 85:
            gate.pass_(f"final quality score >=85: {score_match.group(1)}")
        else:
            gate.fail(f"final quality score below 85: {score_match.group(1)}")
        dimension_scores = [
            float(match.group(1))
            for match in re.finditer(
                r"(?:核心维度|维度|dimension)[^\n：:]*[：:]\s*([0-9]+(?:\.[0-9]+)?)(?:\s*/\s*100|分)",
                text,
                re.I,
            )
        ]
        low_scores = [score for score in dimension_scores if score < 80]
        if low_scores:
            gate.fail(f"plan/final-quality-gate.md contains dimension score(s) below 80: {low_scores}")
        elif dimension_scores:
            gate.pass_("all machine-readable dimension scores are >=80")
    for path in [final_gate]:
        if not path.exists():
            continue
        text = read_text(path)
        blocking_findings = blocking_final_findings(text)
        if fail_pattern.search(text):
            gate.fail(f"{path.relative_to(root)} contains failure status")
        elif blocking_findings:
            gate.fail(
                f"{path.relative_to(root)} contains blocking/non-final evidence: "
                + ", ".join(blocking_findings[:5])
            )
        elif pass_pattern.search(text):
            gate.pass_(f"{path.relative_to(root)} has explicit technical gate evidence")
        else:
            gate.fail(f"{path.relative_to(root)} lacks explicit technical gate evidence")

    if anti_fab.exists():
        text = read_text(anti_fab)
        blocking_findings = blocking_final_findings(text)
        if fail_pattern.search(text):
            gate.fail("plan/review-anti-fabrication.md contains failure or manual-required status")
        elif re.search(r"标记为[\"“]?不可信|编造成立|存在编造", text):
            gate.fail("plan/review-anti-fabrication.md contains unreliable-review or fabrication finding")
        elif final_report_status(text) == "PASS" and blocking_findings:
            gate.fail(
                "plan/review-anti-fabrication.md uses STATUS: PASS while recording blocking/non-final evidence: "
                + ", ".join(blocking_findings[:5])
            )
        elif pass_pattern.search(text) or re.search(r"无不可信报告|未发现编造|全部可信", text):
            gate.pass_("anti-fabrication report has trusted technical evidence")
        else:
            gate.fail("plan/review-anti-fabrication.md lacks explicit trusted technical evidence")


def check_review_and_fix_reports(root: Path, text: str, full_hash: str, gate: Gate) -> None:
    normalized_paper = normalize_text(text)
    review_mode = is_review_framework(root)
    required_review_reports = REVIEW_REPORTS if not review_mode else [
        "plan/review-1-academic.md",
        "plan/review-2-writing.md",
        "plan/review-3-evidence.md",
        "plan/review-4-workflow.md",
        "plan/review-5-reader.md",
    ]

    for rel in required_review_reports:
        path = root / rel
        if not path.exists():
            gate.fail(f"missing review report: {rel}")
            continue
        report = read_text(path)
        for required in ["## 事实提取", "## 评分", "## 证据清单", "## 评分依据"]:
            if required not in report:
                gate.fail(f"{rel} missing required section: {required}")
        evidence_rows = re.findall(r"(?m)^\|\s*\d+\s*\|", report)
        if len(evidence_rows) < 5:
            gate.fail(f"{rel} has fewer than 5 evidence rows")
        fragments = extract_quoted_fragments(report)
        if len(fragments) < 5:
            gate.fail(f"{rel} has fewer than 5 quoted evidence fragments")
        else:
            exact_missing = [
                fragment[:40]
                for fragment in fragments[:10]
                if fragment not in text
            ]
            missing = [
                fragment[:40]
                for fragment in fragments[:10]
                if normalize_text(fragment) not in normalized_paper
            ]
            if exact_missing:
                gate.fail(f"{rel} quotes are not exact full-paper substrings: {exact_missing[:3]}")
            elif missing:
                gate.fail(f"{rel} quotes not found in full-paper: {missing[:3]}")
            else:
                gate.pass_(f"{rel} quoted evidence is exact full-paper text")
        score_match = re.search(r"##\s*评分[：:]\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*100", report)
        if not score_match:
            gate.fail(f"{rel} lacks machine-readable review score")

    anti_fab = root / "plan" / "review-anti-fabrication.md"
    if anti_fab.exists():
        anti_text = read_text(anti_fab)
        for rel in required_review_reports:
            if rel.split("/")[-1] not in anti_text:
                gate.fail(f"anti-fabrication report does not mention {rel}")

    fix_log = root / "plan" / "mandatory-fix-log.md"
    post_fix = root / "plan" / "post-mandatory-fix-review.md"
    if not fix_log.exists():
        gate.fail("missing plan/mandatory-fix-log.md")
    else:
        fix_text = read_text(fix_log)
        problem_count = len(re.findall(r"(?m)^###\s*问题\d+", fix_text))
        if problem_count < 1:
            gate.fail("mandatory fix log has no structured issue entries")
        before_after_count = min(fix_text.count("**修复前**"), fix_text.count("**修复后**"))
        if before_after_count < problem_count:
            gate.fail("mandatory fix log missing before/after blocks")
        after_blocks = re.findall(r"\*\*修复后\*\*[：:]?\s*\n(.+?)(?=\n###|\Z)", fix_text, flags=re.S)
        missing_after = [
            normalize_text(block)[:40]
            for block in after_blocks[:10]
            if normalize_text(block) and normalize_text(block) not in normalized_paper
        ]
        if missing_after:
            gate.fail(f"mandatory fix log after-text not found in full-paper: {missing_after[:3]}")
        elif after_blocks:
            gate.pass_("mandatory fix log after-text is present in full-paper")

    if post_fix.exists():
        post_text = read_text(post_fix)
        if full_hash not in post_text:
            gate.fail("post-mandatory-fix-review.md missing current source hash")
        if final_report_status(post_text) != "PASS" or report_has_failure_status(post_text):
            gate.fail("post-mandatory-fix-review.md does not end in trusted PASS")
    elif not review_mode:
        gate.fail("missing plan/post-mandatory-fix-review.md")


def check_literature_manifest(root: Path, text: str, gate: Gate) -> None:
    manifest = root / "plan" / "literature-search-manifest.jsonl"
    evidence = root / "plan" / "evidence-map.md"
    refs_bib = root / "references.bib"
    failures: list[str] = []

    if not manifest.exists():
        gate.fail("missing plan/literature-search-manifest.jsonl")
        return
    if not evidence.exists():
        gate.fail("missing plan/evidence-map.md")
    if not refs_bib.exists():
        gate.fail("missing references.bib")

    records: list[dict] = []
    for idx, line in enumerate(read_text(manifest).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            failures.append(f"line {idx} is invalid JSON")
            continue
        if not isinstance(record, dict):
            failures.append(f"line {idx} is not a JSON object")
            continue
        records.append(record)
        for key in ["query", "source", "title", "retrieved_at"]:
            if not str(record.get(key, "")).strip():
                failures.append(f"line {idx} missing {key}")
        if not (record.get("doi") or record.get("url") or record.get("arxiv_id") or record.get("pmid")):
            failures.append(f"line {idx} missing doi/url/arxiv_id/pmid")
        if "raw_response_sha256" not in record and "normalized_record_sha256" not in record:
            failures.append(f"line {idx} missing response/record hash")
        url = str(record.get("url", "")).strip()
        if url and not valid_url(url):
            failures.append(f"line {idx} has invalid url")

    if len(records) < 20:
        failures.append(f"literature manifest has fewer than 20 records: {len(records)}")

    joined_titles = normalize_text("\n".join(str(r.get("title", "")) for r in records))
    evidence_text = read_text(evidence) if evidence.exists() else ""
    refs_text = read_text(refs_bib) if refs_bib.exists() else ""
    for record in records[:50]:
        title = str(record.get("title", "")).strip()
        if title and len(normalize_text(title)) >= 20:
            title_norm = normalize_text(title)
            if title_norm not in normalize_text(evidence_text) and title_norm not in normalize_text(refs_text):
                failures.append(f"manifest title not used in evidence-map or references: {title[:60]}")
                break
    bib_titles = re.findall(r"title\s*=\s*[{\"](.+?)[}\"]\s*,", refs_text, flags=re.I | re.S)
    unmatched_bib = [
        re.sub(r"\s+", " ", title).strip()[:60]
        for title in bib_titles[:40]
        if normalize_text(re.sub(r"[{}]", "", title)) not in joined_titles
    ]
    if unmatched_bib:
        failures.append(f"references.bib titles not backed by literature manifest: {unmatched_bib[:3]}")

    if failures:
        gate.fail("literature manifest verification failed: " + "; ".join(failures[:10]))
    else:
        gate.pass_("literature manifest backs evidence-map and references")


# ──────────────────────────────────────────────────────────
# Cross-validation helpers for experiment claims (Issue 3)
# ──────────────────────────────────────────────────────────

def extract_numeric_claims(text: str) -> list[dict]:
    """Extract (metric_context, numeric_value) pairs from running text."""
    claims: list[dict] = []
    prose_text = "\n".join(
        line for line in text.splitlines()
        if line.strip()
        and not line.lstrip().startswith("|")
        and not re.match(r"^\s*\[\d+\]\s+", line)
    )
    # Percentage claims: "准确率达到92.5%", "F1为87.3%"
    for m in re.finditer(
        r"([\u4e00-\u9fffA-Za-z0-9]+[^\d\n]{0,30}?)(\d+\.?\d*)\s*%", prose_text
    ):
        try:
            context = m.group(1).strip()[-20:]
            window = prose_text[max(0, m.start() - 30) : min(len(prose_text), m.end() + 30)]
            if re.search(r"(置信区间|置信水平|confidence\s+interval|\bCI\b|分位|百分位)", window, re.I):
                continue
            claims.append({"context": context, "value": float(m.group(2)), "unit": "%"})
        except ValueError:
            pass
    # Absolute value claims: "MAPE为0.053", "R²=0.892"
    for m in re.finditer(
        r"(?:MAPE|RMSE|MAE|R2|R²|AUC|AUROC|mAP|loss|误差|损失)\s*[=＝为达到至]?\s*(\d+\.\d+)",
        prose_text, re.I,
    ):
        try:
            claims.append({"context": m.group(0)[:30], "value": float(m.group(1)), "unit": "abs"})
        except ValueError:
            pass
    return claims


def extract_baseline_names(text: str) -> list[str]:
    """Extract baseline method names mentioned in results text."""
    names: list[str] = []
    # Common ML model names
    model_patterns = [
        r"(?:Logistic\s*Regression|随机森林|Random\s*Forest|XGBoost|LightGBM|CatBoost|"
        r"\bSVM\b|支持向量机|决策树|Decision\s*Tree|朴素贝叶斯|Naive\s*Bayes|"
        r"\bKNN\b|K近邻|神经网络|Neural\s*Network|\bBERT\b|\bGPT\b|ResNet|VGG|YOLO|"
        r"LSTM|GRU|Transformer|Attention|注意力机制)",
    ]
    for pat in model_patterns:
        for m in re.finditer(pat, text, re.I):
            name = m.group(0).strip()
            if name not in names:
                names.append(name)
    # Also check for Chinese baseline descriptions
    for m in re.finditer(r"(?:基线|对比方法|基准)[^\n]*?([\u4e00-\u9fffA-Za-z]{2,20})", text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start: line_end if line_end != -1 else len(text)]
        if re.search(r"基线模型|相对基线|相对于基线|独立模型|空模型", line):
            continue
        name = m.group(1).strip()
        if name and name not in names:
            names.append(name)
    return names


def extract_p_value_claims(text: str) -> list[dict]:
    """Extract p-value claims from text."""
    claims: list[dict] = []
    for m in re.finditer(r"p\s*[<＞>=＝]\s*(\d+\.\d+)", text, re.I):
        try:
            claims.append({"value": float(m.group(1)), "raw": m.group(0)})
        except ValueError:
            pass
    for m in re.finditer(r"p\s*=\s*(\d+\.\d+)", text, re.I):
        try:
            claims.append({"value": float(m.group(1)), "raw": m.group(0)})
        except ValueError:
            pass
    return claims


def _parse_csv_metrics(path: Path) -> list[dict]:
    """Parse raw-metrics.csv into structured list of {model, metric, value}."""
    metrics: list[dict] = []
    try:
        lines = [ln for ln in read_text(path).splitlines() if ln.strip()]
        if len(lines) < 2:
            return metrics
        header = [h.strip().lower() for h in lines[0].split(",")]
        for line in lines[1:]:
            cells = [c.strip() for c in line.split(",")]
            row = dict(zip(header, cells, strict=False))
            try:
                val = float(row.get("value", "0"))
                metrics.append({
                    "model": row.get("model", ""),
                    "metric": row.get("metric", ""),
                    "value": val,
                })
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return metrics


def _find_matching_metric(
    claimed_value: float, actuals: list[dict], tolerance: float = 0.02
) -> bool:
    """Check if claimed value matches any actual metric within tolerance."""
    for actual in actuals:
        diff = abs(claimed_value - actual["value"])
        if actual["value"] > 0:
            rel_diff = diff / actual["value"]
            if rel_diff <= tolerance:
                return True
        if diff <= tolerance:
            return True
    return False


def cross_validate_experiment_claims(root: Path, text: str, gate: Gate) -> None:
    """Cross-validate claimed numbers against actual artifact data."""
    # 1. Numeric claim traceability
    claimed_numbers = extract_numeric_claims(text)
    metrics_path = root / "results" / "raw-metrics.csv"
    if metrics_path.exists() and claimed_numbers:
        actual_metrics = _parse_csv_metrics(metrics_path)
        if actual_metrics:
            untraceable: list[str] = []
            for claim in claimed_numbers[:30]:
                if not _find_matching_metric(claim["value"], actual_metrics):
                    untraceable.append(f"{claim['context']}: {claim['value']}{claim['unit']}")
            if untraceable:
                gate.fail(
                    "numeric claims not traceable to raw-metrics.csv: "
                    + "; ".join(untraceable[:5])
                )

    # 2. Baseline name verification
    claimed_baselines = extract_baseline_names(text)
    baseline_path = root / "plan" / "baseline-verify.json"
    if baseline_path.exists() and claimed_baselines:
        try:
            bl_data = json.loads(read_text(baseline_path))
            verified_names = set()
            for src in bl_data.get("baseline_sources", []):
                name = src.get("name", "")
                if name:
                    verified_names.add(name.lower())
            for cb in claimed_baselines:
                if cb.lower() not in verified_names and not any(
                    cb.lower() in vn for vn in verified_names
                ):
                    gate.fail(f"claimed baseline '{cb}' not found in baseline-verify.json")
        except (json.JSONDecodeError, AttributeError):
            pass

    # 3. P-value verification
    p_claims = extract_p_value_claims(text)
    stats_path = root / "results" / "statistical-tests.json"
    if stats_path.exists() and p_claims:
        try:
            stats = json.loads(read_text(stats_path))
            actual_p_values = [
                t["p_value"] for t in stats.get("tests", [])
                if isinstance(t, dict) and "p_value" in t
            ]
            for pc in p_claims:
                if not any(abs(pc["value"] - ap) < 0.001 for ap in actual_p_values):
                    gate.fail(
                        f"claimed p-value '{pc['raw']}' not found in statistical-tests.json"
                    )
        except (json.JSONDecodeError, TypeError):
            pass

    # 4. Figure/table reference verification
    claim_refs = re.findall(r"(?:图|表|Fig(?:ure)?|Table)\s*(\d+)", text)
    if claim_refs:
        figures_dir = root / "figures"
        for ref_str in set(claim_refs):
            ref_num = int(ref_str)
            fig_exists = False
            if figures_dir.exists():
                fig_exists = any(
                    re.search(rf"figure[_-]?{ref_num}", p.name, re.I)
                    for p in figures_dir.rglob("*.png")
                ) or any(
                    re.search(rf"figure[_-]?{ref_num}", p.name, re.I)
                    for p in figures_dir.rglob("*.svg")
                ) or any(
                    re.search(rf"figure[_-]?{ref_num}", p.name, re.I)
                    for p in figures_dir.rglob("*.pdf")
                )
            # Also check if table is in the full-paper text as markdown table
            if not fig_exists:
                table_pattern = rf"(?:表\s*{ref_num}|Table\s*{ref_num})"
                if not re.search(table_pattern, text, re.I):
                    gate.warn(f"claim references figure/table #{ref_num} which may not exist")


def check_experiment_claims(root: Path, text: str, gate: Gate) -> None:
    review_mode = is_review_framework(root)
    simulated_patterns = [
        "模拟环境生成",
        "尚未经过真实",
        "待真实实验",
        "占位数据",
        "synthetic",
        "simulated data",
        "not yet validated",
    ]
    simulated_hits = [pattern for pattern in simulated_patterns if re.search(pattern, text, re.I)]
    if simulated_hits:
        gate.fail("experiment/results rely on simulated or unvalidated data: " + ", ".join(simulated_hits))

    artifact_failures = []
    if review_mode:
        hits = [claim for claim in STRONG_EXPERIMENT_CLAIMS if re.search(claim, text, re.I)]
        if hits:
            gate.fail(
                "strong experiment claims present in review/framework paper: "
                + ", ".join(hits)
            )
        else:
            gate.pass_("review/framework paper has no strong experiment claims")
        return
    for rel, kind in REQUIRED_EXPERIMENT_ARTIFACTS:
        path = root / rel
        if not path.exists():
            artifact_failures.append(f"missing {rel}")
            continue
        try:
            if kind == "json":
                data = read_json(path)
                if not isinstance(data, dict):
                    artifact_failures.append(f"{rel} is not a JSON object")
                    continue
                status = str(data.get("status", "")).upper()
                source_hash = str(data.get("source_hash", ""))
                evidence_chain_hash = str(data.get("evidence_chain_hash", ""))
                if status != "PASS":
                    artifact_failures.append(f"{rel} status is not PASS")
                if source_hash:
                    if source_hash != sha256(root / "full-paper.md"):
                        artifact_failures.append(f"{rel} source_hash does not match full-paper")
                elif not evidence_chain_hash:
                    artifact_failures.append(f"{rel} missing source_hash or evidence_chain_hash")
                elif not re.fullmatch(r"[a-fA-F0-9]{32,64}", evidence_chain_hash):
                    artifact_failures.append(f"{rel} evidence_chain_hash is not a valid hex digest")
                for required_key in ["commands", "data_hashes"]:
                    if required_key not in data:
                        artifact_failures.append(f"{rel} missing {required_key}")
                    elif not data.get(required_key):
                        artifact_failures.append(f"{rel} has empty {required_key}")
                if rel == "plan/dataset-verify.json":
                    if not non_empty_list(data.get("dataset_urls")):
                        artifact_failures.append(f"{rel} missing non-empty dataset_urls")
                    else:
                        for url in data.get("dataset_urls", []):
                            if not isinstance(url, str) or not valid_url(url):
                                artifact_failures.append(f"{rel} has invalid dataset url")
                                break
                    if not str(data.get("license_or_access_notes", "")).strip():
                        artifact_failures.append(f"{rel} missing license_or_access_notes")
                    if not str(data.get("sample_size_source", "")).strip():
                        artifact_failures.append(f"{rel} missing sample_size_source")
                if rel == "plan/baseline-verify.json":
                    if not non_empty_list(data.get("baseline_sources")):
                        artifact_failures.append(f"{rel} missing non-empty baseline_sources")
                    else:
                        for idx, source in enumerate(data.get("baseline_sources", []), start=1):
                            if not isinstance(source, dict):
                                artifact_failures.append(f"{rel} baseline source #{idx} is not an object")
                                continue
                            if not str(source.get("name", "")).strip():
                                artifact_failures.append(f"{rel} baseline source #{idx} missing name")
                            if not (source.get("doi") or source.get("paper_url") or source.get("code_url")):
                                artifact_failures.append(f"{rel} baseline source #{idx} missing doi/paper_url/code_url")
                            for url_key in ["paper_url", "code_url"]:
                                url = str(source.get(url_key, "")).strip()
                                if url and not valid_url(url):
                                    artifact_failures.append(f"{rel} baseline source #{idx} has invalid {url_key}")
                if rel == "plan/experiment-run-manifest.json":
                    for required_key in [
                        "random_seeds",
                        "metric_files",
                        "statistical_test_files",
                        "input_data_hashes",
                        "code_hashes",
                    ]:
                        if required_key not in data or not data.get(required_key):
                            artifact_failures.append(f"{rel} missing non-empty {required_key}")
                    recompute = data.get("metric_recompute_command")
                    if not isinstance(recompute, dict) or not recompute.get("cmd"):
                        artifact_failures.append(f"{rel} missing metric_recompute_command.cmd")
                    elif recompute.get("exit_code") != 0:
                        artifact_failures.append(f"{rel} metric_recompute_command exit_code is not 0")
                commands = data.get("commands")
                if not isinstance(commands, list):
                    artifact_failures.append(f"{rel} commands must be a non-empty list")
                else:
                    for idx, command in enumerate(commands, start=1):
                        if not isinstance(command, dict):
                            artifact_failures.append(f"{rel} command #{idx} is not an object")
                            continue
                        if not command.get("cmd"):
                            artifact_failures.append(f"{rel} command #{idx} missing cmd")
                        if command.get("exit_code") != 0:
                            artifact_failures.append(f"{rel} command #{idx} exit_code is not 0")
                        log_rel = command.get("log")
                        if not log_rel or not (root / str(log_rel)).exists():
                            artifact_failures.append(f"{rel} command #{idx} missing log file")
                        else:
                            log_path = root / str(log_rel)
                            if log_path.stat().st_size == 0:
                                artifact_failures.append(f"{rel} command #{idx} log file is empty")
                            expected_log_hash = command.get("log_sha256")
                            if expected_log_hash and sha256(log_path) != expected_log_hash:
                                artifact_failures.append(f"{rel} command #{idx} log_sha256 mismatch")
                data_hashes = data.get("data_hashes") if isinstance(data.get("data_hashes"), dict) else {}
                for hash_path, expected_hash in data_hashes.items():
                    data_path = root / hash_path
                    if not expected_hash:
                        artifact_failures.append(f"{rel} data hash empty: {hash_path}")
                        continue
                    if not data_path.exists():
                        artifact_failures.append(f"{rel} data file missing: {hash_path}")
                    elif sha256(data_path) != expected_hash:
                        artifact_failures.append(f"{rel} data hash mismatch: {hash_path}")
            elif kind == "jsonl":
                # Full literature checks are done in check_literature_manifest().
                if not read_text(path).strip():
                    artifact_failures.append(f"{rel} is empty")
            elif kind == "csv":
                lines = [line for line in read_text(path).splitlines() if line.strip()]
                if len(lines) < 2:
                    artifact_failures.append(f"{rel} has no metric rows")
                header = lines[0].lower().split(",") if lines else []
                required_columns = {"model", "metric", "value"}
                if not required_columns.issubset(set(cell.strip() for cell in header)):
                    artifact_failures.append(f"{rel} missing required columns model,metric,value")
                metric_values = csv_metric_values(path) if path.exists() else []
                if len(metric_values) < 5:
                    artifact_failures.append(f"{rel} contains fewer than 5 numeric metric values")
                else:
                    normalized_text = normalize_text(text)
                    matched = [
                        value for value in metric_values[:30]
                        if compact_number(value) and compact_number(value) in normalized_text
                    ]
                    if len(set(matched)) < min(5, len(set(metric_values))):
                        artifact_failures.append(f"{rel} values are not traceable to full-paper text")
        except json.JSONDecodeError:
            artifact_failures.append(f"{rel} is invalid JSON")
    stats_path = root / "results" / "statistical-tests.json"
    if stats_path.exists():
        try:
            stats = json.loads(read_text(stats_path))
            tests = stats.get("tests")
            if not isinstance(tests, list) or not tests:
                artifact_failures.append("results/statistical-tests.json missing non-empty tests list")
            else:
                for idx, test in enumerate(tests[:10], start=1):
                    if not isinstance(test, dict):
                        artifact_failures.append(f"statistical test #{idx} is not an object")
                        continue
                    if "p_value" not in test or "method" not in test or "comparison" not in test:
                        artifact_failures.append(f"statistical test #{idx} missing method/comparison/p_value")
        except json.JSONDecodeError:
            artifact_failures.append("results/statistical-tests.json is invalid JSON")
    if artifact_failures:
        gate.fail("real experiment artifacts incomplete: " + "; ".join(artifact_failures[:10]))
    else:
        gate.pass_("real experiment artifacts are present and machine-verifiable")

    # Cross-validate numeric claims against actual data (only when artifacts exist)
    if not artifact_failures:
        cross_validate_experiment_claims(root, text, gate)

    experiment_path = root / "chapters" / "04-experiments.md"
    results_path = root / "chapters" / "05-results.md"
    protocol_path = root / "plan" / "experiment-protocol.md"
    has_experiment_chapter = experiment_path.exists()
    has_results_chapter = results_path.exists()
    has_protocol = protocol_path.exists()
    has_result_headings = bool(re.search(r"^#\s*(四|4|五|5|实验|结果)", text, flags=re.M))
    has_result_tables = bool(re.search(r"(?m)^\|.*\|", read_text(results_path) if results_path.exists() else ""))
    has_metrics = bool(
        re.search(
            r"Accuracy|F1|Precision|Recall|AUC|AUROC|MAPE|RMSE|MAE|R2|R²|mAP|PRO|准确率|召回率",
            read_text(results_path) if results_path.exists() else "",
            flags=re.I,
        )
    )
    has_baselines = bool(re.search(r"baseline|基线|对比方法|消融", read_text(protocol_path) if protocol_path.exists() else "", flags=re.I))
    has_real_artifacts = not artifact_failures
    if (
        has_experiment_chapter
        and has_results_chapter
        and has_protocol
        and has_result_headings
        and has_result_tables
        and has_metrics
        and has_baselines
        and has_real_artifacts
    ):
        if not simulated_hits:
            gate.pass_("experiment/result artifacts exist for strong claims")
        return

    hits = [claim for claim in STRONG_EXPERIMENT_CLAIMS if re.search(claim, text, re.I)]
    if hits:
        gate.fail(
            "strong experiment claims present without complete experiment/results artifacts: "
            + ", ".join(hits)
        )
    else:
        gate.pass_("no strong experiment claims without complete artifacts")


def check_submission_compliance(root: Path, text: str, gate: Gate) -> None:
    """Check required submission declarations: ethics, DAS, COI, CRediT."""
    # 1. Data availability statement
    da_path = root / "plan" / "data-availability-statement.md"
    da_text = da_path.read_text(encoding="utf-8").strip() if da_path.exists() else ""
    if len(da_text) > 50:
        gate.pass_(f"data availability statement found ({len(da_text)} chars)")
    else:
        gate.fail("missing data availability statement (plan/data-availability-statement.md)")

    # 2. Ethics / IRB — auto-pass for review/framework papers
    ethics_keywords = ["伦理", "ethics", "IRB", "知情同意", "informed consent", "伦理审查", "伦理委员会"]
    ethics_found = False
    for p in [root / "submission" / "ethics-statement.md", root / "plan" / "ethics-statement.md"]:
        if p.exists():
            t = p.read_text(encoding="utf-8")
            if any(kw.lower() in t.lower() for kw in ethics_keywords):
                ethics_found = True
                break
    if not ethics_found:
        auto_config = root / "plan" / "auto-config.json"
        paper_type = ""
        if auto_config.exists():
            try:
                cfg = json.loads(auto_config.read_text(encoding="utf-8"))
                paper_type = cfg.get("paper_type", "")
            except (json.JSONDecodeError, OSError):
                pass
        if paper_type in ("review", "framework"):
            ethics_found = True
    if ethics_found:
        gate.pass_("ethics/IRB statement verified")
    else:
        gate.fail("missing ethics/IRB statement (required for empirical papers)")

    # 3. Conflict of interest
    coi_keywords = ["利益冲突", "conflict of interest", "COI", "competing interests"]
    coi_found = False
    for p in [root / "submission" / "conflict-of-interest.md", root / "plan" / "conflict-of-interest.md"]:
        if p.exists():
            t = p.read_text(encoding="utf-8")
            if any(kw.lower() in t.lower() for kw in coi_keywords):
                coi_found = True
                break
    if not coi_found and text:
        coi_found = any(kw.lower() in text.lower() for kw in coi_keywords)
    if coi_found:
        gate.pass_("conflict of interest declaration found")
    else:
        gate.fail("missing conflict of interest declaration")

    # 4. CRediT / author contribution
    credit_keywords = ["作者贡献", "CRediT", "Author Contributions", "author contribution"]
    credit_found = any(kw.lower() in text.lower() for kw in credit_keywords) if text else False
    if credit_found:
        gate.pass_("author contribution statement found")
    else:
        gate.fail("missing author contribution / CRediT statement")

    # 5. Funding statement
    funding_keywords = ["基金", "资助", "funding", "financial support", "grant", "acknowledgment", "致谢"]
    funding_found = any(kw.lower() in text.lower() for kw in funding_keywords) if text else False
    if not funding_found:
        for p in [root / "submission" / "funding.md", root / "plan" / "funding.md"]:
            if p.exists():
                funding_found = True
                break
    if funding_found:
        gate.pass_("funding statement found")
    else:
        gate.warn("no funding statement detected (required by most journals)")

    # 6. Supplementary material check
    supp_dir = root / "supplementary"
    has_supplementary = supp_dir.exists() and any(supp_dir.iterdir()) if supp_dir.exists() else False
    if has_supplementary:
        gate.pass_("supplementary material directory exists")
    else:
        gate.warn("no supplementary material found (may be required for empirical papers)")

    # 7. AI use disclosure — content-level check ported from the retired
    # submission_checklist module: the file must exist AND mention AI usage.
    ai_keywords = ["AI", "人工智能", "ChatGPT", "Claude", "LLM", "大语言模型",
                   "artificial intelligence", "generated", "生成式"]
    ai_found = False
    for p in [root / "submission" / "ai-use-disclosure.md",
              root / "plan" / "ai-use-disclosure.md"]:
        if p.exists():
            t = p.read_text(encoding="utf-8")
            if any(kw in t for kw in ai_keywords):
                ai_found = True
                break
    if ai_found:
        gate.pass_("AI use disclosure found with substantive content")
    else:
        gate.fail("missing AI use disclosure (submission/ai-use-disclosure.md)")


def check_statistical_reporting(root: Path, text: str, gate: Gate) -> None:
    """Check statistical reporting completeness for empirical papers.

    Verifies: p-values include exact values, sample sizes reported,
    effect sizes mentioned where applicable.
    """
    if not text:
        return

    # Detect if this is an empirical paper (has experiment/statistics content)
    empirical_indicators = ["实验", "experiment", "样本", "sample", "统计", "statistic", "检验", "test"]
    is_empirical = sum(1 for kw in empirical_indicators if kw in text) >= 3
    if not is_empirical:
        gate.pass_("statistical reporting: not empirical paper, skipping")
        return

    # Check for vague p-value reporting
    import re as _re
    vague_p = _re.findall(r"[pP]\s*[<>=≤≥]\s*0\.0[015]", text)
    exact_p = _re.findall(r"[pP]\s*=\s*0\.\d+", text)
    if vague_p and not exact_p:
        gate.warn(f"statistical reporting: only vague p-values found ({len(vague_p)} instances like 'p<0.05'), "
                  f"consider reporting exact p-values")
    elif exact_p:
        gate.pass_(f"statistical reporting: {len(exact_p)} exact p-value(s) found")

    # Check for sample size reporting
    sample_patterns = [
        r"[nN]\s*=\s*\d+",
        r"样本量",
        r"sample size",
        r"参与者",
        r"participants",
        r"被试",
    ]
    sample_found = any(_re.search(pat, text) for pat in sample_patterns)
    if sample_found:
        gate.pass_("statistical reporting: sample size mentioned")
    else:
        gate.warn("statistical reporting: no sample size detected in empirical paper")

    # Check for effect size reporting
    effect_patterns = [
        r"Cohen'?s?\s*d",
        r"eta.?squared",
        r"效应量",
        r"effect size",
        r"odds ratio",
        r"relative risk",
        r"confidence interval",
        r"置信区间",
    ]
    effect_found = any(_re.search(pat, text, _re.IGNORECASE) for pat in effect_patterns)
    if effect_found:
        gate.pass_("statistical reporting: effect size / confidence interval mentioned")
    else:
        gate.warn("statistical reporting: no effect size or confidence interval detected")


def check_novelty_verdict(root: Path, gate: Gate) -> None:
    """Enforce novelty reviewer verdict: score >= 60 and no P0 findings."""
    novelty_path = root / "plan" / "review-9-novelty.md"
    if not novelty_path.exists():
        gate.fail("novelty review report missing (plan/review-9-novelty.md)")
        return
    text = novelty_path.read_text(encoding="utf-8")
    # Extract score
    match = re.search(r"##\s*评分[：:]\s*(\d+)", text)
    if not match:
        gate.fail("novelty review has no machine-readable score")
        return
    score = int(match.group(1))
    if score < 70:
        gate.fail(f"novelty score too low: {score}/100 (minimum 70)")
    else:
        gate.pass_(f"novelty score: {score}/100")
    # Check for P0 findings
    p0_matches = re.findall(r"\bP0\b", text)
    if p0_matches:
        gate.fail(f"novelty review has {len(p0_matches)} P0 finding(s) — blocking")


def check_reference_recency(root: Path, gate: Gate) -> None:
    """Check that references.bib has adequate recency (recent 5 years >= 40%)."""
    refs_bib = root / "references.bib"
    if not refs_bib.exists():
        return  # Already caught by check_references
    bib_text = refs_bib.read_text(encoding="utf-8")
    years = [int(y) for y in re.findall(r"year\s*=\s*\{?(\d{4})\}?", bib_text, re.IGNORECASE)]
    if not years:
        gate.fail("no year fields found in references.bib")
        return
    current_year = 2026
    recent_cutoff = current_year - 5
    recent_count = sum(1 for y in years if y >= recent_cutoff)
    recent_pct = recent_count / len(years) * 100
    if recent_pct >= 50:
        gate.pass_(f"reference recency: {recent_pct:.0f}% from {recent_cutoff}-{current_year}")
    elif recent_pct >= 30:
        gate.warn(f"reference recency below 50%: {recent_pct:.0f}% from {recent_cutoff}-{current_year}")
    else:
        gate.fail(f"reference recency critically low: {recent_pct:.0f}% from {recent_cutoff}-{current_year}")
    # Check for single-decade dominance
    if years:
        decade_counts: dict[int, int] = {}
        for y in years:
            decade = (y // 10) * 10
            decade_counts[decade] = decade_counts.get(decade, 0) + 1
        max_decade = max(decade_counts, key=decade_counts.get)  # type: ignore[arg-type]
        max_pct = decade_counts[max_decade] / len(years) * 100
        if max_pct > 40:
            gate.warn(f"single decade dominance: {max_decade}s has {max_pct:.0f}% of references")


def check_reference_language_balance(root: Path, text: str, gate: Gate) -> None:
    """Check that Chinese-language papers have sufficient Chinese references.
    For CSSCI-targeted papers: Chinese references >= 40%."""
    refs_bib = root / "references.bib"
    if not refs_bib.exists():
        return  # Already caught by check_references

    bib_text = refs_bib.read_text(encoding="utf-8")
    entries = re.split(r"^@", bib_text, flags=re.M)
    entries = [e for e in entries if e.strip()]

    if not entries:
        return

    # Detect paper language from full-paper.md title and content
    title_match = re.search(r"^#\s*(.+)", text, flags=re.M)
    paper_title = title_match.group(1) if title_match else ""
    sample = (paper_title + " " + text[:500])
    chinese_chars = len(re.findall(r"[一-鿿]", sample))
    total_alpha = len(re.findall(r"[a-zA-Z]", sample))
    is_chinese_paper = chinese_chars > total_alpha * 0.3

    if not is_chinese_paper:
        gate.pass_("reference language balance: non-Chinese paper, no Chinese ref requirement")
        return

    # Count Chinese references by checking title/author fields
    chinese_count = 0
    english_count = 0
    for entry in entries:
        title_m = re.search(r"title\s*=\s*\{(.+?)\}", entry, re.DOTALL)
        author_m = re.search(r"author\s*=\s*\{(.+?)\}", entry, re.DOTALL)
        title_val = title_m.group(1) if title_m else ""
        author_val = author_m.group(1) if author_m else ""
        combined = title_val + " " + author_val

        if re.search(r"[一-鿿]", combined):
            chinese_count += 1
        else:
            english_count += 1

    total = chinese_count + english_count
    if total == 0:
        return

    chinese_pct = chinese_count / total * 100
    if chinese_pct >= 40:
        gate.pass_(f"reference language balance: {chinese_pct:.0f}% Chinese ({chinese_count}/{total})")
    elif chinese_pct >= 20:
        gate.warn(f"reference language balance: {chinese_pct:.0f}% Chinese ({chinese_count}/{total}), >=40% recommended for CSSCI")
    else:
        gate.fail(f"reference language balance: {chinese_pct:.0f}% Chinese ({chinese_count}/{total}), >=40% required for Chinese-language papers")


def check_plagiarism_clearance(root: Path, gate: Gate) -> None:
    """Require a plagiarism report file to exist (manual step by user)."""
    candidates = [
        root / "submission" / "plagiarism-report.pdf",
        root / "submission" / "plagiarism-report.md",
        root / "submission" / "plagiarism-report.txt",
        root / "submission" / "ithenticate-report.pdf",
        root / "submission" / "turnitin-report.pdf",
    ]
    found = any(p.exists() for p in candidates)
    if found:
        gate.pass_("plagiarism clearance report found")
    else:
        gate.fail("no plagiarism report found (place in submission/plagiarism-report.{pdf,md,txt})")


def check_ledger_integrity(root: Path, gate: Gate) -> None:
    """Verify claim-evidence-source ledger integrity via verify-ledgers.py.

    This is a BLOCKING check: FAIL issues from the ledger verifier are
    propagated as gate failures, preventing false PASS when the three-level
    claim->evidence->source chain is broken.
    """
    script_dir = Path(__file__).resolve().parent
    verify_path = (script_dir / ".." / ".." / "scripts" / "verify-ledgers.py").resolve()
    if not verify_path.exists():
        gate.warn(f"verify-ledgers.py not found at {verify_path} — skipping ledger integrity check")
        return

    ledgers_dir = root / "ledgers"
    if not ledgers_dir.exists():
        gate.warn("no ledgers/ directory — skipping ledger integrity check")
        return

    claim_ledger = ledgers_dir / "claim-ledger.jsonl"
    args = [sys.executable, str(verify_path), str(root)]
    if not claim_ledger.exists():
        args.append("--source-evidence-only")

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        gate.fail("ledger integrity check timed out (120s)")
        return

    output = result.stdout + result.stderr
    fail_lines = [ln for ln in output.splitlines() if ln.startswith("FAIL:")]
    warn_lines = [ln for ln in output.splitlines() if ln.startswith("WARN:")]

    if result.returncode != 0 and fail_lines:
        for line in fail_lines:
            gate.fail(f"ledger: {line[5:].strip()}")
    elif warn_lines:
        for line in warn_lines:
            gate.warn(f"ledger: {line[5:].strip()}")
    else:
        gate.pass_("ledger integrity verified (claim->evidence->source chain intact)")


def check_text_quality(root: Path, text: str, gate: Gate) -> None:
    """Non-LLM text quality metrics — deterministic anchors against LLM artifacts.

    Checks: sentence length variance, paragraph length uniformity,
    vocabulary overlap between consecutive paragraphs, connector word entropy.
    """
    script_dir = Path(__file__).resolve().parent
    metrics_path = script_dir / "text_quality_metrics.py"
    if not metrics_path.exists():
        gate.warn("text_quality_metrics.py not found — skipping deterministic text quality check")
        return

    try:
        from text_quality_metrics import analyze_text_quality
        report = analyze_text_quality(text)
    except Exception as exc:
        gate.warn(f"text quality metrics failed: {exc}")
        return

    for m in report.metrics:
        if m.passed:
            gate.pass_(f"text quality: {m.name} = {m.value} ({m.detail})")
        else:
            gate.fail(f"text quality: {m.name} = {m.value} (threshold: {m.operator} {m.threshold}) — {m.detail}")


def check_journal_compliance(root: Path, text: str, gate: Gate, blocking: bool = False) -> None:
    """Check paper against target journal template requirements.

    Advisory (WARN) in the default strict profile; blocking (FAIL) under
    --submission when a template section exists. Auto-detects the template
    from plan/auto-config.json or defaults to CSSCI General.
    """
    # Try to import journal_templates from papers/scripts/
    script_dir = Path(__file__).resolve().parent
    templates_path = (script_dir / ".." / ".." / "papers" / "scripts" / "journal_templates.py").resolve()
    if not templates_path.exists():
        return  # Silently skip if templates not available

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("journal_templates", str(templates_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        template = mod.detect_template(root)
    except Exception:
        return

    gate.pass_(f"journal template: {template.name} ({template.name_en})")

    # Check abstract length
    if template.abstract_max_chars > 0:
        # Find abstract in text
        import re as _re
        abstract_match = _re.search(r"(?:摘\s*要|Abstract)[：:\s]*(.+?)(?:\n\n|\n#|\n##)", text, _re.DOTALL)
        if abstract_match:
            abstract_text = abstract_match.group(1).strip()
            abstract_len = len(re.sub(r"\s+", "", abstract_text))
            if abstract_len > template.abstract_max_chars:
                gate.fail(f"journal: abstract too long ({abstract_len} chars, max {template.abstract_max_chars})")
            else:
                gate.pass_(f"journal: abstract length OK ({abstract_len}/{template.abstract_max_chars} chars)")

    # Check reference count
    bib_path = root / "references.bib"
    if bib_path.exists() and template.ref_min_count > 0:
        bib_text = bib_path.read_text(encoding="utf-8")
        ref_count = len(re.findall(r"@\w+\{", bib_text))
        if ref_count < template.ref_min_count:
            gate.fail(f"journal: too few references ({ref_count}, min {template.ref_min_count})")
        else:
            gate.pass_(f"journal: reference count OK ({ref_count}, min {template.ref_min_count})")

    # Check required sections
    if template.required_sections:
        missing_sections = []
        for section in template.required_sections:
            # Check for section in headings or text
            if not (re.search(rf"#{1,3}\s*{re.escape(section)}", text) or section in text):
                missing_sections.append(section)
        if missing_sections:
            message = f"journal: missing recommended sections: {', '.join(missing_sections)}"
            gate.fail(message) if blocking else gate.warn(message)
        else:
            gate.pass_(f"journal: all required sections present ({len(template.required_sections)})")

    # Check keyword count
    if template.keywords_count[0] > 0:
        kw_match = re.search(r"(?:关键词|Keywords)[：:\s]*(.+?)(?:\n\n|\n#)", text, re.DOTALL)
        if kw_match:
            kw_text = kw_match.group(1).strip()
            kw_count = len(re.findall(r"[，,;；]", kw_text)) + 1
            min_kw, max_kw = template.keywords_count
            if kw_count < min_kw:
                message = f"journal: too few keywords ({kw_count}, min {min_kw})"
                gate.fail(message) if blocking else gate.warn(message)
            elif kw_count > max_kw:
                message = f"journal: too many keywords ({kw_count}, max {max_kw})"
                gate.fail(message) if blocking else gate.warn(message)
            else:
                gate.pass_(f"journal: keyword count OK ({kw_count})")


def check_submission_signoff(root: Path, gate: Gate) -> None:
    """Submission profile state requirement (schemas/state-transitions.json S11).

    Accepts SUBMISSION_PACKAGE_READY, or TECHNICAL_PASS with human signoff
    artifacts present: non-empty human_signoff_hashes in plan/status.json plus
    ledgers/human-signoff.json."""
    status_path = root / "plan" / "status.json"
    if not status_path.exists():
        gate.fail("submission: plan/status.json missing")
        return
    try:
        status = json.loads(read_text(status_path))
    except json.JSONDecodeError as exc:
        gate.fail(f"submission: plan/status.json invalid JSON: {exc}")
        return
    if not isinstance(status, dict):
        gate.fail("submission: plan/status.json must contain a JSON object")
        return
    st = str(status.get("status", ""))
    signoff_hashes = status.get("human_signoff_hashes")
    signoff_file = root / "ledgers" / "human-signoff.json"
    if st == "SUBMISSION_PACKAGE_READY":
        gate.pass_(f"submission: status.json status={st}")
    elif st == "TECHNICAL_PASS":
        if not isinstance(signoff_hashes, dict) or not signoff_hashes:
            gate.fail(
                "submission: TECHNICAL_PASS without human_signoff_hashes in "
                "plan/status.json — run 'paperctl signoff' before submission packaging"
            )
        elif not signoff_file.exists():
            gate.fail(
                "submission: TECHNICAL_PASS without ledgers/human-signoff.json — "
                "run 'paperctl signoff' before submission packaging"
            )
        else:
            gate.pass_("submission: TECHNICAL_PASS with human signoff artifacts present")
    else:
        gate.fail(
            f"submission: status.json status={st!r} (want SUBMISSION_PACKAGE_READY "
            "or TECHNICAL_PASS with human signoff artifacts present)"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_path")
    parser.add_argument("--mode", default="strict", choices=["strict"])
    parser.add_argument(
        "--submission",
        action="store_true",
        help="Submission profile: additionally require S11 human-signoff state and "
             "treat journal-compliance findings as blocking",
    )
    args = parser.parse_args()

    root = Path(args.project_path).resolve()
    gate = Gate(failures=[], warnings=[], echo=True)

    print(f"Strict quality gate: {root}")
    text = check_structure(root, gate)
    if text:
        full_hash = sha256(root / "full-paper.md")
        print(f"Source full-paper sha256: {full_hash}")
        check_project_identity(root, text, full_hash, gate)
        check_style(text, gate)
        check_text_quality(root, text, gate)
        check_references(root, text, gate)
        check_literature_manifest(root, text, gate)
        check_single_source(root, full_hash, gate)
        check_report_hashes(root, full_hash, gate)
        check_review_and_fix_reports(root, text, full_hash, gate)
        check_review_framework_assets(root, text, gate)
        check_review_methodology_gate(root, text, gate)
        check_experiment_claims(root, text, gate)
        check_ledger_integrity(root, gate)
        check_submission_compliance(root, text, gate)
        check_statistical_reporting(root, text, gate)
        check_novelty_verdict(root, gate)
        check_reference_recency(root, gate)
        check_reference_language_balance(root, text, gate)
        check_plagiarism_clearance(root, gate)
        check_journal_compliance(root, text, gate, blocking=args.submission)

    if args.submission:
        check_submission_signoff(root, gate)
    print()
    print("Summary")
    print(f"Failures: {len(gate.failures)}")
    print(f"Warnings: {len(gate.warnings)}")
    if gate.failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
