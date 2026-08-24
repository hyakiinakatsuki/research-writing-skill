"""Shared building blocks for the research + strict quality gates.

Single source (audit C4/C10):
- GateResult accumulator (failures/warnings, optional stdout echo)
- is_review_framework paper-type detection

Both gates previously carried drifted copies of these; quality-gate.sh runs
them back-to-back, so divergent review-framework detection produced
one-gate-checks-one-skips gaps.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GateResult:
    """Failure/warning accumulator.

    echo=True preserves the strict gate's historical stdout contract
    (FAIL:/WARN:/PASS: lines consumed by quality-gate.sh log parsing);
    the research gate runs silently with the default echo=False.
    """

    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    echo: bool = False

    def fail(self, msg: str) -> None:
        self.failures.append(msg)
        if self.echo:
            print(f"FAIL: {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        if self.echo:
            print(f"WARN: {msg}")

    def pass_(self, msg: str) -> None:
        if self.echo:
            print(f"PASS: {msg}")

    @property
    def passed(self) -> bool:
        return not self.failures


def is_review_framework(root: Path) -> bool:
    """True when plan/auto-config.json or chapter-architecture marks the
    project as a review/framework paper.

    Case-insensitive marker match (the superseding semantics: the research
    gate's copy missed capitalized "Review"); falls back to the
    chapter-architecture heuristic when auto-config is absent/uninformative.
    """
    config_path = root / "plan" / "auto-config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8", errors="replace"))
            paper_meta = data.get("paper_meta", {}) if isinstance(data, dict) else {}
            marker = " ".join(
                str(paper_meta.get(key, "")) for key in ["paper_type", "workflow_mode", "model_abbr"]
            ).lower()
            if re.search(r"review|framework|综述|框架", marker):
                return True
        except (json.JSONDecodeError, AttributeError):
            pass

    arch_path = root / "plan" / "chapter-architecture.md"
    if arch_path.exists():
        arch_text = arch_path.read_text(encoding="utf-8", errors="replace")
        return "02-literature-framework.md" in arch_text and "04-experiments.md" not in arch_text
    return False
