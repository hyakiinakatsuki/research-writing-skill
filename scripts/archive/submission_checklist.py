#!/usr/bin/env python3
"""Submission checklist: verifies required declarations for top-journal submission.

Checks:
1. Data availability statement
2. Ethics / IRB statement
3. Conflict of interest declaration
4. AI use disclosure
5. Bilingual figure/table captions
6. Reference count minimums
7. Abstract presence (Chinese + English)

Usage:
    python3 submission_checklist.py <paper-project-dir> [--json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def check_submission(project: Path) -> dict:
    """Run all submission checks. Returns a dict with per-check results."""
    checks: list[dict] = []
    overall_pass = True

    full_paper = project / "full-paper.md"
    paper_text = _read(full_paper)

    # ── 1. Data availability statement ──
    da_path = project / "plan" / "data-availability-statement.md"
    da_text = _read(da_path)
    da_ok = bool(da_text.strip()) and len(da_text.strip()) > 50
    checks.append({
        "name": "data-availability",
        "passed": da_ok,
        "detail": f"Found {da_path.name}: {'YES' if da_text.strip() else 'NO'}, "
                  f"length={len(da_text.strip())}",
    })
    if not da_ok:
        overall_pass = False

    # ── 2. Ethics / IRB statement ──
    # Check for ethics statement in submission/ or plan/ or full-paper
    ethics_keywords = ["伦理", "ethics", "IRB", "知情同意", "informed consent", "伦理审查", "伦理委员会"]
    ethics_found = False
    for p in [project / "submission" / "ethics-statement.md",
              project / "plan" / "ethics-statement.md"]:
        t = _read(p)
        if any(kw.lower() in t.lower() for kw in ethics_keywords):
            ethics_found = True
            break
    if not ethics_found:
        # Check if it's a review/framework paper (may not need IRB)
        auto_config = project / "plan" / "auto-config.json"
        paper_type = ""
        if auto_config.exists():
            try:
                cfg = json.loads(_read(auto_config))
                paper_type = cfg.get("paper_type", "")
            except json.JSONDecodeError:
                pass
        if paper_type in ("review", "framework"):
            ethics_found = True  # Review papers may not need IRB
    checks.append({
        "name": "ethics-statement",
        "passed": ethics_found,
        "detail": "Ethics/IRB statement found" if ethics_found
                  else "Missing ethics statement (required for empirical, optional for review)",
    })
    if not ethics_found:
        overall_pass = False

    # ── 3. Conflict of interest ──
    coi_keywords = ["利益冲突", "conflict of interest", "COI", "competing interests"]
    coi_found = False
    for p in [project / "submission" / "conflict-of-interest.md",
              project / "plan" / "conflict-of-interest.md"]:
        t = _read(p)
        if any(kw.lower() in t.lower() for kw in coi_keywords):
            coi_found = True
            break
    if not coi_found and paper_text:
        coi_found = any(kw.lower() in paper_text.lower() for kw in coi_keywords)
    checks.append({
        "name": "conflict-of-interest",
        "passed": coi_found,
        "detail": "COI declaration found" if coi_found else "Missing conflict of interest declaration",
    })
    if not coi_found:
        overall_pass = False

    # ── 4. AI use disclosure ──
    ai_keywords = ["AI", "人工智能", "ChatGPT", "Claude", "LLM", "大语言模型",
                    "artificial intelligence", "generated", "生成式"]
    ai_found = False
    for p in [project / "submission" / "ai-use-disclosure.md",
              project / "plan" / "ai-use-disclosure.md"]:
        t = _read(p)
        if any(kw in t for kw in ai_keywords):
            ai_found = True
            break
    checks.append({
        "name": "ai-use-disclosure",
        "passed": ai_found,
        "detail": "AI use disclosure found" if ai_found else "Missing AI use disclosure",
    })
    if not ai_found:
        overall_pass = False

    # ── 5. Bilingual figure/table captions ──
    if paper_text:
        fig_refs = re.findall(r"!\[([^\]]*)\]", paper_text)
        # Check figure captions for bilingual (Chinese + English)
        fig_bilingual = 0
        for cap in fig_refs:
            has_cn = bool(re.search(r"[一-鿿]", cap))
            has_en = bool(re.search(r"[a-zA-Z]{3,}", cap))
            if has_cn and has_en:
                fig_bilingual += 1
        total_figs = len([f for f in fig_refs if f.strip()])
        fig_ok = fig_bilingual >= total_figs * 0.8 if total_figs > 0 else True
        checks.append({
            "name": "bilingual-captions",
            "passed": fig_ok,
            "detail": f"Figures: {fig_bilingual}/{total_figs} bilingual",
        })
        if not fig_ok:
            overall_pass = False
    else:
        checks.append({
            "name": "bilingual-captions",
            "passed": False,
            "detail": "full-paper.md not found",
        })
        overall_pass = False

    # ── 6. Reference count ──
    if paper_text:
        ref_count = len(re.findall(r"^\[(\d+)\]", paper_text, re.MULTILINE))
        ref_ok = ref_count >= 25
        checks.append({
            "name": "reference-count",
            "passed": ref_ok,
            "detail": f"References: {ref_count} (minimum 25)",
        })
        if not ref_ok:
            overall_pass = False
    else:
        checks.append({"name": "reference-count", "passed": False, "detail": "No paper text"})
        overall_pass = False

    # ── 7. Abstract presence ──
    if paper_text:
        has_cn_abstract = bool(re.search(r"#\s*摘\s*要", paper_text))
        has_en_abstract = bool(re.search(r"#\s*Abstract", paper_text, re.IGNORECASE))
        abstract_ok = has_cn_abstract and has_en_abstract
        checks.append({
            "name": "abstract",
            "passed": abstract_ok,
            "detail": f"Chinese: {'YES' if has_cn_abstract else 'NO'}, "
                      f"English: {'YES' if has_en_abstract else 'NO'}",
        })
        if not abstract_ok:
            overall_pass = False
    else:
        checks.append({"name": "abstract", "passed": False, "detail": "No paper text"})
        overall_pass = False

    return {
        "overall": "PASS" if overall_pass else "FAIL",
        "checks": checks,
        "passed": sum(1 for c in checks if c["passed"]),
        "total": len(checks),
    }


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python3 submission_checklist.py <paper-project-dir> [--json]")
        raise SystemExit(0)

    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"Project directory not found: {project}")
        raise SystemExit(5)

    result = check_submission(project)

    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"SUBMISSION_CHECKLIST: {result['overall']}")
        print(f"Checks: {result['passed']}/{result['total']} passed\n")
        for c in result["checks"]:
            status = "PASS" if c["passed"] else "FAIL"
            print(f"  [{status}] {c['name']}: {c['detail']}")

    raise SystemExit(0 if result["overall"] == "PASS" else 4)


if __name__ == "__main__":
    main()
