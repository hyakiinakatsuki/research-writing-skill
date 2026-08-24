#!/usr/bin/env python3
"""Enforce machine-readable status semantics for paper workspaces.

The paper pipeline has two very different states:

- draft artifacts that may be useful for review;
- final/submission artifacts that passed every required gate.

This script prevents a draft or partially verified workspace from carrying a
generic ``STATUS: PASS`` marker in final reports.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

FINAL_REPORTS = [
    "plan/final-quality-gate.md",
    "plan/final-gate-summary.md",
    "plan/quality-gate-final.md",
    "plan/review-anti-fabrication.md",
]

SUBMISSION_REQUIRED_REPORTS = FINAL_REPORTS + [
    "plan/final-review-report.md",
]

SUBMISSION_REQUIRED_ARTIFACTS = [
    "full-paper.md",
    "main.tex",
    "main.pdf",
    "main.final.pdf",
    "plan/research-quality-gate.log",
    "plan/strict-quality-gate.log",
]

BLOCKING_PATTERNS = [
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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def final_status(text: str) -> str:
    matches = re.findall(r"STATUS:\s*(PASS|FAIL|NEED_RETRY|MANUAL_REQUIRED|DRAFT_ONLY)", text, re.I)
    if matches:
        return matches[-1].upper()
    if re.search(r"(?:TECHNICAL_GATE_STATUS|QUALITY_GATE_STATUS):\s*RECORDED", text, re.I) and re.search(
        r"全部PASS|整体[：:]\s*PASS|是否达标[：:]\s*(是|PASS)",
        text,
        re.I,
    ):
        return "PASS"
    return ""


def markdown_title(text: str) -> str:
    front_matter = {"摘要", "中文摘要", "Abstract", "关键词 Keywords", "关键词", "Keywords"}
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match and match.group(1).strip() not in front_matter:
            return match.group(1).strip()
    return ""


def config_title(root: Path) -> str:
    config = root / "plan" / "auto-config.json"
    if not config.exists():
        return ""
    try:
        data = json.loads(read_text(config))
    except json.JSONDecodeError:
        return ""
    meta = data.get("paper_meta") if isinstance(data, dict) else None
    if isinstance(meta, dict):
        title = meta.get("title_cn") or meta.get("TITLE_CN")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return ""


def read_json(path: Path) -> object:
    return json.loads(read_text(path))


def blocking_findings(text: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in BLOCKING_PATTERNS:
        if re.search(pattern, text, re.I | re.M):
            findings.append(label)
    return findings


def write_manifest(root: Path, manifest: dict) -> None:
    plan_dir = root / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "status-contract.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def submission_state_ready(root: Path) -> tuple[bool, dict]:
    status_path = root / "plan" / "status.json"
    if not status_path.exists():
        return False, {}
    try:
        status = read_json(status_path)
    except json.JSONDecodeError:
        return False, {}
    if not isinstance(status, dict) or status.get("status") != "SUBMISSION_PACKAGE_READY":
        return False, status if isinstance(status, dict) else {}
    if status.get("current_stage") != "S11":
        return False, status
    completed = status.get("completed_stages")
    if not isinstance(completed, list) or "S10" not in completed or "S11" not in completed:
        return False, status
    hashes = status.get("last_artifact_hashes")
    signoff_hashes = status.get("human_signoff_hashes")
    if not isinstance(hashes, dict) or not isinstance(signoff_hashes, dict):
        return False, status
    for artifact in ["main.tex", "main.pdf", "main.final.pdf"]:
        path = root / artifact
        if not path.exists() or hashes.get(artifact) != sha256(path):
            return False, status
        if signoff_hashes.get(artifact) != hashes.get(artifact):
            return False, status
    signoff = root / "ledgers" / "human-signoff.json"
    review_ledger = root / "ledgers" / "review-ledger.jsonl"
    if not signoff.exists() or not review_ledger.exists():
        return False, status
    return True, status


TECHNICAL_REQUIRED_ARTIFACTS = [
    "full-paper.md",
    "references.bib",
    "main.tex",
    "main.pdf",
    "plan/status.json",
]


def technical_state_ready(root: Path) -> tuple[bool, dict]:
    """Unattended DoD: TECHNICAL_PASS with core delivery artifacts (no human signoff)."""
    status_path = root / "plan" / "status.json"
    if not status_path.exists():
        return False, {}
    try:
        status = read_json(status_path)
    except json.JSONDecodeError:
        return False, {}
    if not isinstance(status, dict):
        return False, {}
    st = status.get("status", "")
    if st not in {"TECHNICAL_PASS", "SUBMISSION_PACKAGE_READY"}:
        return False, status
    completed = status.get("completed_stages")
    if isinstance(completed, list) and "S10" not in completed and st == "TECHNICAL_PASS":
        # Allow missing completed_stages entry if artifacts prove export
        pass
    for rel in TECHNICAL_REQUIRED_ARTIFACTS:
        path = root / rel
        if not path.exists() or path.stat().st_size == 0:
            return False, status
    # PDF magic
    pdf = root / "main.pdf"
    try:
        head = pdf.read_bytes()[:5]
        if head != b"%PDF-":
            return False, status
    except OSError:
        return False, status
    full = root / "full-paper.md"
    if full.stat().st_size < 2000:
        return False, status
    return True, status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_path")
    parser.add_argument("--submission", action="store_true")
    parser.add_argument(
        "--technical",
        action="store_true",
        help="Unattended DoD: TECHNICAL_PASS artifacts only (no human signoff)",
    )
    args = parser.parse_args()

    if args.submission and args.technical:
        print("ERROR: --submission and --technical are mutually exclusive")
        return 2

    root = Path(args.project_path).resolve()
    failures: list[str] = []
    warnings: list[str] = []
    state_payload: dict = {}

    full_paper = root / "full-paper.md"
    if not full_paper.exists():
        failures.append("missing full-paper.md")
        full_hash = ""
        title = ""
    else:
        full_text = read_text(full_paper)
        full_hash = sha256(full_paper)
        title = config_title(root) or markdown_title(full_text)

    if args.technical:
        ready, state_payload = technical_state_ready(root)
        for rel in TECHNICAL_REQUIRED_ARTIFACTS:
            artifact = root / rel
            if not artifact.exists():
                failures.append(f"missing required technical artifact: {rel}")
            elif artifact.stat().st_size == 0:
                failures.append(f"empty required technical artifact: {rel}")
        if full_paper.exists() and full_paper.stat().st_size < 2000:
            failures.append("full-paper.md too short for technical pass (<2000 bytes)")
        pdf = root / "main.pdf"
        if pdf.exists():
            try:
                if pdf.read_bytes()[:5] != b"%PDF-":
                    failures.append("main.pdf missing PDF magic")
            except OSError as exc:
                failures.append(f"main.pdf unreadable: {exc}")
        st = state_payload.get("status", "") if isinstance(state_payload, dict) else ""
        if st and st not in {"TECHNICAL_PASS", "SUBMISSION_PACKAGE_READY"}:
            failures.append(f"status.json status={st!r} (want TECHNICAL_PASS)")
        if not ready and not failures:
            failures.append("technical_state_ready returned false")
        # Technical mode: reports are soft (WARN only) so unattended path is not blocked
        # by incomplete report binding while delivery artifacts exist.
        for rel in FINAL_REPORTS:
            path = root / rel
            if not path.exists():
                warnings.append(f"missing optional technical report: {rel}")
        mode = "technical"
        required_reports: list[str] = []
    elif args.submission:
        state_ready, state_payload = submission_state_ready(root)
        for rel in SUBMISSION_REQUIRED_ARTIFACTS:
            artifact = root / rel
            if not artifact.exists():
                failures.append(f"missing required submission artifact: {rel}")
            elif artifact.stat().st_size == 0:
                failures.append(f"empty required submission artifact: {rel}")
        research_log = root / "plan/research-quality-gate.log"
        if research_log.exists():
            log_text = read_text(research_log)
            if "Research quality gate passed." not in log_text:
                failures.append("plan/research-quality-gate.log does not record a passing research gate")
        strict_log = root / "plan/strict-quality-gate.log"
        if strict_log.exists():
            log_text = read_text(strict_log)
            if "Failures: 0" not in log_text:
                failures.append("plan/strict-quality-gate.log does not record Failures: 0")
        binding_path = root / "plan/gate-binding.json"
        if not binding_path.exists():
            failures.append("missing plan/gate-binding.json")
        else:
            try:
                binding = read_json(binding_path)
            except json.JSONDecodeError as exc:
                failures.append(f"plan/gate-binding.json is invalid JSON: {exc}")
                binding = {}
            if isinstance(binding, dict):
                if binding.get("status") != "PASS":
                    failures.append("plan/gate-binding.json is not PASS")
                if binding.get("project_path") != str(root):
                    failures.append("plan/gate-binding.json is not bound to current project path")
                if full_hash and binding.get("full_paper_sha256") != full_hash:
                    failures.append("plan/gate-binding.json is not bound to current full-paper sha256")
                if title and normalize(str(binding.get("title", ""))) != normalize(title):
                    failures.append("plan/gate-binding.json is not bound to current paper title")
        if (root / "main.final.pdf").exists() and (root / "main.pdf").exists():
            if sha256(root / "main.final.pdf") != sha256(root / "main.pdf"):
                failures.append("main.final.pdf does not match current main.pdf")
        if (root / "main.tex").exists() and full_hash:
            tex = read_text(root / "main.tex")
            if full_hash not in tex:
                failures.append("main.tex is not bound to current full-paper sha256")
        if not state_ready and not failures:
            failures.append("submission_state_ready returned false")
        mode = "submission"
        required_reports = SUBMISSION_REQUIRED_REPORTS
    else:
        mode = "workspace"
        required_reports = FINAL_REPORTS

    reports_seen: list[str] = []
    report_findings: dict[str, list[str]] = {}

    output_aliases = {str(root)}
    root_text = str(root)
    if root_text.startswith("/private/var/"):
        output_aliases.add(root_text.replace("/private/var/", "/var/", 1))
    elif root_text.startswith("/var/"):
        output_aliases.add(root_text.replace("/var/", "/private/var/", 1))

    for rel in required_reports:
        path = root / rel
        if not path.exists():
            failures.append(f"missing required status report: {rel}")
            continue

        reports_seen.append(rel)
        text = read_text(path)
        status = final_status(text)
        findings = blocking_findings(text)
        report_findings[rel] = findings

        if full_hash and full_hash not in text:
            failures.append(f"{rel} is not bound to current full-paper sha256")
        if title and normalize(title) not in normalize(text):
            failures.append(f"{rel} is not bound to current paper title")
        if not any(alias in text for alias in output_aliases):
            failures.append(f"{rel} is not bound to current output path")

        if status == "PASS" and findings:
            failures.append(
                f"{rel} uses STATUS: PASS while recording blocking/non-final evidence: "
                + ", ".join(findings[:5])
            )
        elif args.submission and status != "PASS" and not (
            isinstance(state_payload, dict) and state_payload.get("status") == "SUBMISSION_PACKAGE_READY"
        ):
            failures.append(f"{rel} does not end with submission PASS status; found {status or 'EMPTY'}")
        elif not args.submission and not args.technical and status in {"FAIL", "NEED_RETRY", "MANUAL_REQUIRED"}:
            warnings.append(f"{rel} is non-passing: {status}")

        if args.submission and findings:
            failures.append(f"{rel} contains submission-blocking evidence: " + ", ".join(findings[:5]))

    manifest = {
        "status": "PASS" if not failures else "FAIL",
        "mode": mode,
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "project_path": str(root),
        "full_paper_sha256": full_hash,
        "title": title,
        "reports_seen": reports_seen,
        "report_findings": report_findings,
        "failures": failures,
        "warnings": warnings,
        "state_machine_status": (
            state_payload.get("status", "")
            if isinstance(state_payload, dict)
            else ""
        ),
    }
    write_manifest(root, manifest)

    print(f"Status contract: {root}")
    for failure in failures:
        print(f"FAIL: {failure}")
    for warning in warnings:
        print(f"WARN: {warning}")
    print(f"STATUS: {manifest['status']}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
