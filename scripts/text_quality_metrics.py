"""Non-LLM text quality metrics for academic papers.

Provides deterministic, reproducible quality checks that serve as anchors
independent of LLM self-evaluation. Used by strict_quality_gate.py as a
blocking gate dimension.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────

# Chinese sentence-ending punctuation
_CN_SENTENCE_END = re.compile(r"[。！？；…]+")
# English sentence-ending punctuation
_EN_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")
# Chinese paragraph connector words (模板化过渡词)
_CN_CONNECTORS = [
    "首先", "其次", "再次", "最后", "此外", "另外", "与此同时",
    "综上所述", "总之", "因此", "所以", "然而", "但是", "尽管",
    "虽然", "一方面", "另一方面", "不仅", "而且", "同时",
]
# English paragraph connector words
_EN_CONNECTORS = [
    "however", "therefore", "moreover", "furthermore", "additionally",
    "consequently", "nevertheless", "nonetheless", "meanwhile",
    "subsequently", "accordingly", "thus", "hence", "likewise",
]


@dataclass
class MetricResult:
    """A single metric check result."""
    name: str
    value: float
    threshold: float
    operator: str  # "lt", "gt", "between"
    passed: bool
    detail: str = ""


@dataclass
class TextQualityReport:
    """Aggregated text quality report."""
    metrics: list[MetricResult] = field(default_factory=list)

    @property
    def failures(self) -> list[MetricResult]:
        return [m for m in self.metrics if not m.passed]

    @property
    def warnings(self) -> list[MetricResult]:
        return [m for m in self.metrics if not m.passed and m.operator == "warn"]

    @property
    def blocking_failures(self) -> list[MetricResult]:
        return [m for m in self.metrics if not m.passed and m.operator != "warn"]


# ── Paragraph Extraction ──────────────────────────────────────────────────

def extract_prose_paragraphs(text: str, *, min_chars: int = 50) -> list[str]:
    """Extract prose paragraphs from markdown text.

    Excludes: headings, code blocks, tables, list items, empty lines.
    Returns paragraphs with at least min_chars of non-whitespace content.
    """
    paragraphs: list[str] = []
    in_code_block = False
    current: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()
        # Toggle code blocks
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        # Skip headings, tables, list items, images, HTML, and reference entries.
        if (stripped.startswith("#") or stripped.startswith("|")
                or stripped.startswith("- ") or stripped.startswith("* ")
                or stripped.startswith("!") or stripped.startswith("<")
                or re.match(r"^\[\d+\]\s+", stripped)):
            continue
        # Empty line = paragraph boundary
        if not stripped:
            if current:
                para = "\n".join(current)
                if len(re.sub(r"\s+", "", para)) >= min_chars:
                    paragraphs.append(para)
                current = []
            continue
        current.append(line)

    # Last paragraph
    if current:
        para = "\n".join(current)
        if len(re.sub(r"\s+", "", para)) >= min_chars:
            paragraphs.append(para)

    return paragraphs


def extract_sentences(text: str) -> list[str]:
    """Extract sentences from Chinese/English mixed text."""
    # Split on Chinese sentence endings first
    parts = _CN_SENTENCE_END.split(text)
    sentences: list[str] = []
    for part in parts:
        # Further split on English sentence endings
        en_parts = _EN_SENTENCE_END.split(part.strip())
        for en_part in en_parts:
            en_part = en_part.strip()
            if len(en_part) > 2:  # Filter out fragments (punctuation remnants)
                sentences.append(en_part)
    return sentences


# ── Metric Functions ──────────────────────────────────────────────────────

def check_sentence_length_variance(paragraphs: list[str]) -> MetricResult:
    """Check that sentence lengths vary (not monotonous LLM output).

    LLM text tends to produce uniformly-length sentences. A low coefficient
    of variation (CV < 0.3) is suspicious.
    """
    all_sentences: list[str] = []
    for para in paragraphs:
        all_sentences.extend(extract_sentences(para))

    if len(all_sentences) < 5:
        return MetricResult(
            name="sentence_length_cv",
            value=0.0, threshold=0.3, operator="gt",
            passed=True, detail="too few sentences to evaluate"
        )

    lengths = [len(re.sub(r"\s+", "", s)) for s in all_sentences]
    mean_len = statistics.mean(lengths)
    if mean_len == 0:
        return MetricResult(
            name="sentence_length_cv",
            value=0.0, threshold=0.3, operator="gt",
            passed=True, detail="zero-length sentences"
        )

    cv = statistics.stdev(lengths) / mean_len
    return MetricResult(
        name="sentence_length_cv",
        value=round(cv, 3), threshold=0.3, operator="gt",
        passed=cv >= 0.3,
        detail=f"CV={cv:.3f} (mean={mean_len:.0f} chars, n={len(lengths)} sentences)"
    )


def check_paragraph_length_variance(paragraphs: list[str]) -> MetricResult:
    """Check that paragraph lengths vary (KS test against uniform).

    LLM text tends to produce paragraphs of very similar length.
    A KS statistic > 0.6 suggests suspicious uniformity.
    """
    if len(paragraphs) < 5:
        return MetricResult(
            name="paragraph_length_uniformity",
            value=0.0, threshold=0.6, operator="lt",
            passed=True, detail="too few paragraphs to evaluate"
        )

    lengths = sorted([len(re.sub(r"\s+", "", p)) for p in paragraphs])
    n = len(lengths)
    min_len, max_len = lengths[0], lengths[-1]

    if max_len == min_len:
        ks_stat = 1.0  # Perfectly uniform
    else:
        # KS test: max deviation from uniform CDF
        ks_stat = 0.0
        for i, ln in enumerate(lengths):
            expected = (ln - min_len) / (max_len - min_len) if max_len > min_len else 0
            observed = (i + 1) / n
            ks_stat = max(ks_stat, abs(expected - observed))

    return MetricResult(
        name="paragraph_length_uniformity",
        value=round(ks_stat, 3), threshold=0.6, operator="lt",
        passed=ks_stat < 0.6,
        detail=f"KS={ks_stat:.3f} (n={n}, range={min_len}-{max_len} chars)"
    )


def check_vocabulary_overlap(paragraphs: list[str]) -> MetricResult:
    """Check that consecutive paragraphs don't reuse too many words.

    Jaccard similarity > 0.4 between consecutive paragraphs suggests
    mechanical repetition (common in LLM output).
    """
    if len(paragraphs) < 2:
        return MetricResult(
            name="vocabulary_overlap",
            value=0.0, threshold=0.4, operator="lt",
            passed=True, detail="too few paragraphs to evaluate"
        )

    def word_set(text: str) -> set[str]:
        return set(re.findall(r"[一-鿿]+|[a-zA-Z]+", text.lower()))

    max_jaccard = 0.0
    worst_pair = (0, 1)
    for i in range(len(paragraphs) - 1):
        w1 = word_set(paragraphs[i])
        w2 = word_set(paragraphs[i + 1])
        if not w1 or not w2:
            continue
        intersection = w1 & w2
        union = w1 | w2
        jaccard = len(intersection) / len(union) if union else 0
        if jaccard > max_jaccard:
            max_jaccard = jaccard
            worst_pair = (i, i + 1)

    return MetricResult(
        name="vocabulary_overlap",
        value=round(max_jaccard, 3), threshold=0.4, operator="lt",
        passed=max_jaccard < 0.4,
        detail=f"max Jaccard={max_jaccard:.3f} between paragraphs {worst_pair[0]}-{worst_pair[1]}"
    )


def check_connector_entropy(paragraphs: list[str]) -> MetricResult:
    """Check that connector/transition words are varied, not repetitive.

    If the same connector word appears in > 30% of paragraphs, the text
    likely uses template-driven transitions.
    """
    if len(paragraphs) < 3:
        return MetricResult(
            name="connector_entropy",
            value=1.0, threshold=0.3, operator="gt",
            passed=True, detail="too few paragraphs to evaluate"
        )

    all_connectors = _CN_CONNECTORS + _EN_CONNECTORS
    connector_counts: dict[str, int] = {}
    for para in paragraphs:
        found_in_para: set[str] = set()
        for conn in all_connectors:
            if conn in para.lower():
                found_in_para.add(conn)
        for conn in found_in_para:
            connector_counts[conn] = connector_counts.get(conn, 0) + 1

    if not connector_counts:
        return MetricResult(
            name="connector_entropy",
            value=1.0, threshold=0.3, operator="gt",
            passed=True, detail="no connector words found"
        )

    # Check max dominance: most-used connector / total paragraphs
    max_count = max(connector_counts.values())
    dominance = max_count / len(paragraphs)

    # Shannon entropy of connector distribution
    total = sum(connector_counts.values())
    entropy = -sum((c / total) * math.log2(c / total) for c in connector_counts.values())
    max_entropy = math.log2(len(connector_counts)) if len(connector_counts) > 1 else 1.0
    normalized_entropy = entropy / max_entropy if max_entropy > 0 else 1.0

    # Fail if dominance > 30% (same connector in too many paragraphs)
    passed = dominance < 0.3
    return MetricResult(
        name="connector_entropy",
        value=round(dominance, 3), threshold=0.3, operator="lt",
        passed=passed,
        detail=f"max_dominance={dominance:.3f}, entropy={normalized_entropy:.3f} "
               f"(top: {sorted(connector_counts.items(), key=lambda x: -x[1])[:3]})"
    )


# ── Main Entry Point ──────────────────────────────────────────────────────

def analyze_text_quality(text: str) -> TextQualityReport:
    """Run all text quality metrics on a paper's full text.

    Returns a TextQualityReport with all metric results.
    """
    paragraphs = extract_prose_paragraphs(text, min_chars=50)
    report = TextQualityReport()

    report.metrics.append(check_sentence_length_variance(paragraphs))
    report.metrics.append(check_paragraph_length_variance(paragraphs))
    report.metrics.append(check_vocabulary_overlap(paragraphs))
    report.metrics.append(check_connector_entropy(paragraphs))

    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python text_quality_metrics.py <full-paper.md>")
        sys.exit(1)
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    report = analyze_text_quality(text)
    for m in report.metrics:
        status = "PASS" if m.passed else "FAIL"
        print(f"{status}: {m.name} = {m.value} (threshold: {m.operator} {m.threshold}) — {m.detail}")
    if report.blocking_failures:
        print(f"\n{len(report.blocking_failures)} blocking failure(s)")
        sys.exit(1)
    else:
        print(f"\nAll {len(report.metrics)} metrics passed")
        sys.exit(0)
