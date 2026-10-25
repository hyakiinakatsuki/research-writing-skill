#!/usr/bin/env python3
"""Render full-paper.md to a polished academic-paper LaTeX file.

Supports multiple journal templates selectable via auto-config.json.
The renderer is deterministic and source-bound: main.tex is generated only from
full-paper.md plus metadata in plan/auto-config.json. Manuscript content should
not be edited in main.tex.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

SPECIALS = {
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "_": r"\_",
}

MATH_SYMBOLS = {
    "α": r"$\alpha$",
    "β": r"$\beta$",
    "χ": r"$\chi$",
    "≈": r"$\approx$",
    "≤": r"$\leq$",
    "≥": r"$\geq$",
    "±": r"$\pm$",
    "²": r"$^2$",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def escape_plain(text: str) -> str:
    for old, new in MATH_SYMBOLS.items():
        text = text.replace(old, new)
    for old, new in SPECIALS.items():
        text = text.replace(old, new)
    return text


def escape_latex(text: str) -> str:
    parts = re.split(r"(\$[^$]+\$)", text)
    return "".join(part if part.startswith("$") and part.endswith("$") else escape_plain(part) for part in parts)


def convert_inline(text: str, *, convert_citations: bool = True) -> str:
    text = re.sub(r"\\+n", lambda _: r"\\ ", text)
    parts = re.split(r"(\$[^$]+\$)", text)
    processed: list[str] = []
    for part in parts:
        if part.startswith("$") and part.endswith("$"):
            processed.append(part)
        else:
            part = re.sub(r"\*\*(.+?)\*\*", r"\1", part)
            part = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", part)
            if convert_citations:
                # Convert [N] numeric citations to \cite{srcNN}
                part = re.sub(
                    r"\[(\d+)\]",
                    lambda m: r"\cite{" + f"src{int(m.group(1)):02d}" + "}",
                    part,
                )
            processed.append(part)
    return escape_latex("".join(processed))


def strip_heading_number(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\d+(?:\.\d+)*\s+", "", text)
    text = re.sub(r"^第[一二三四五六七八九十]+章\s*", "", text)
    text = re.sub(r"^[（(]?[一二三四五六七八九十]+[）)]?[、.．]?\s*", "", text)
    return text.strip()


def read_metadata(root: Path, fallback_title: str) -> dict[str, str]:
    meta = {
        "title_cn": fallback_title or "论文题目",
        "title_en": "",
        "field": "",
        "model_abbr": "",
        "latex_template": "cn-journal-submission-v2",
        "author_line": "",
        "affiliation_line": "",
        "manuscript_status": "",
    }
    config = root / "plan" / "auto-config.json"
    if not config.exists():
        return meta
    try:
        data = json.loads(config.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return meta
    paper_meta = data.get("paper_meta", {}) if isinstance(data, dict) else {}
    if isinstance(paper_meta, dict):
        meta["title_cn"] = paper_meta.get("title_cn") or meta["title_cn"]
        meta["title_en"] = paper_meta.get("title_en") or ""
        meta["field"] = paper_meta.get("field") or ""
        meta["model_abbr"] = paper_meta.get("model_abbr") or ""
        meta["latex_template"] = paper_meta.get("latex_template", "cn-journal-submission-v2")
        meta["author_line"] = paper_meta.get("author_line") or ""
        meta["affiliation_line"] = paper_meta.get("affiliation_line") or ""
        meta["manuscript_status"] = paper_meta.get("manuscript_status") or ""
    return meta


def normalize_table_caption(caption: str, table_no: int) -> str:
    caption = caption.strip().strip("*").strip()
    if not caption:
        return f"表 {table_no}"
    return caption


def flush_table(lines: list[str], out: list[str], manifest: dict, caption: str = "") -> None:
    if not lines:
        return
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    lines.clear()
    if not rows:
        return

    cols = max(len(row) for row in rows)
    manifest["tables"] += 1
    table_no = manifest["tables"]
    table_caption = normalize_table_caption(caption, table_no)
    out.extend([
        r"\begin{table}[H]",
        r"\centering",
        rf"\caption{{{convert_inline(table_caption)}}}",
        r"\small",
        r"\renewcommand{\arraystretch}{1.3}",
        r"\resizebox{\linewidth}{!}{%",
        r"\begin{tabular}{" + "l" * cols + "}",
        r"\toprule",
    ])
    for idx, row in enumerate(rows):
        padded = row + [""] * (cols - len(row))
        out.append(" & ".join(convert_inline(cell) for cell in padded) + r" \\")
        if idx == 0:
            out.append(r"\midrule")
    out.extend([r"\bottomrule", r"\end{tabular}", r"}", r"\end{table}", ""])


# ──────────────────────────────────────────────────────────
# Template Registry
# ──────────────────────────────────────────────────────────

@dataclass
class LatexTemplate:
    name: str
    language: str  # "zh" or "en"
    document_class: str
    preamble: list[str]
    title_page_fn: Callable  # (meta: dict, title: str, body: list[str]) -> None
    abstract_commands: tuple[str, str, str]  # (abstract_title, abstract_en_title, keywords)
    extra_packages: list[str] = field(default_factory=list)


TEMPLATES: dict[str, LatexTemplate] = {}


def register_template(t: LatexTemplate) -> None:
    TEMPLATES[t.name] = t


# ── cn-journal-submission-v2 (CSSCI 中文期刊) ──

def _cn_title_page(meta: dict, title: str, body: list[str]) -> None:
    author_line = meta.get("author_line") or "匿名评审稿"
    affiliation_line = meta.get("affiliation_line") or "作者与单位信息按投稿系统提交"
    manuscript_status = meta.get("manuscript_status") or "技术复核稿"
    title_size = "3" if len(title) > 20 else "2"  # 长标题降号保证单行
    body.extend([
        r"\begin{titlepage}",
        r"\noindent\begin{tabular}{ll}"
        rf"\heiti 分类号：& {convert_inline(meta.get('classification_no', '') or '—')} \\"
        rf"[0.2em] \heiti 密\quad 级：& {convert_inline(meta.get('security_level', '') or '内部')} \\"
        r"\end{tabular}"
        r"\vspace*{0.8cm}",
        r"{\color[HTML]{1F3864}\rule{0.86\textwidth}{0.6pt}\par}",
        r"\vspace{0.9cm}",
        r"{\zihao{-4} CSSCI 期刊投稿稿件\par}",
        r"\vspace{1.2cm}",
        rf"{{\heiti\zihao{{{title_size}}} {convert_inline(title)}\par}}",
    ])
    if meta.get("title_en"):
        body.append(rf"{{\vspace{{0.5cm}}\zihao{{4}} {convert_inline(meta['title_en'])}\par}}")
    else:
        body.append(r"\vspace{0.1cm}")
    body.extend([
        r"\vspace{0.8cm}",
        r"{\color[HTML]{1F3864}\rule{0.6\textwidth}{0.3pt}\par}",
        r"\vspace{1.4cm}",
        rf"{{\zihao{{4}} \heiti {convert_inline(author_line)}\par}}",
        r"\vspace{0.5cm}",
        rf"{{\zihao{{-4}} {convert_inline(affiliation_line)}\par}}",
        r"\vfill",
        r"\begin{tabular}{rl}",
        rf"\heiti 学科领域：& {convert_inline(meta.get('field', '') or '自动生成论文')} \\",
        rf"\heiti 模型简称：& {convert_inline(meta.get('model_abbr', '') or '—')} \\",
        r"\heiti 投稿日期：& \today \\",
        rf"\heiti 稿件状态：& {convert_inline(manuscript_status)} \\",
        r"\end{tabular}",
        r"\vfill",
        r"{\color[HTML]{1F3864}\rule{0.86\textwidth}{0.6pt}\par}",
        r"\end{titlepage}",
    ])
    if str(meta.get("line_numbers", "")).lower() in ("1", "true", "yes"):
        body.append(r"\linenumbers")
    body.extend([
        r"\pagenumbering{Roman}",
        r"\tableofcontents",
        r"\clearpage",
        r"\listoffigures",
        r"\listoftables",
        r"\clearpage",
        r"\pagenumbering{arabic}",
        "",
    ])


_CN_PREAMBLE = [
    r"\documentclass[UTF8,a4paper,12pt]{ctexart}",
    r"\usepackage{amsmath,amssymb}",
    r"\usepackage{graphicx}",
    r"\usepackage{booktabs}",
    r"\usepackage{array}",
    r"\usepackage{tabularx}",
    r"\usepackage{longtable}",
    r"\usepackage{multirow}",
    r"\usepackage{threeparttable}",
    r"\usepackage{float}",
    r"\usepackage{geometry}",
    r"\usepackage{setspace}",
    r"\usepackage{titlesec}",
    r"\usepackage{titletoc}",
    r"\usepackage{fancyhdr}",
    r"\usepackage{caption}",
    r"\usepackage{enumitem}",
    r"\usepackage{xcolor}",
    r"\usepackage{xurl}",
    r"\usepackage{lineno}",
    r"\usepackage[hang,flushmargin]{footmisc}",
    r"\usepackage{microtype}",
    r"\usepackage{hyperref}",
    r"\numberwithin{equation}{section}",
    r"\setlength{\footnotesep}{0.9em}",
    r"\renewcommand{\footnoterule}{\vspace*{0.3em}\hrule width 0.3\textwidth height 0.4pt \vspace*{0.4em}}",
    r"\geometry{top=2.5cm,bottom=2.5cm,left=2.5cm,right=2.5cm,headheight=15pt,headsep=0.4cm}",
    r"\setstretch{1.5}",
    r"\setlength{\parindent}{2em}",
    r"\setlength{\parskip}{0pt}",
    r"\emergencystretch=3em",
    r"\sloppy",
]

register_template(LatexTemplate(
    name="cn-journal-submission-v2",
    language="zh",
    document_class="ctexart",
    preamble=_CN_PREAMBLE,
    title_page_fn=_cn_title_page,
    abstract_commands=(
        r"\journalabstracttitle",
        r"\journalabstractentitle",
        r"\journalkeywordtitle",
    ),
))

register_template(LatexTemplate(
    name="cn-award-paper-v1",
    language="zh",
    document_class="ctexart",
    preamble=_CN_PREAMBLE,
    title_page_fn=_cn_title_page,
    abstract_commands=(
        r"\awardabstracttitle",
        r"\journalabstractentitle",
        r"\journalkeywordtitle",
    ),
))


# ── ieee-conference ──

def _ieee_conf_title_page(meta: dict, title: str, body: list[str]) -> None:
    body.extend([
        rf"\title{{{convert_inline(title)}}}",
    ])
    if meta.get("title_en") and meta["title_en"] != title:
        pass  # IEEE uses single title
    body.extend([
        r"\author{Author Name\\Institution\\City, Country\\email@example.com}",
        r"\maketitle",
        "",
    ])


_IEEE_CONF_PREAMBLE = [
    r"\documentclass[conference]{IEEEtran}",
    r"\usepackage{amsmath,amssymb}",
    r"\usepackage{graphicx}",
    r"\usepackage{booktabs}",
    r"\usepackage{array}",
    r"\usepackage{multirow}",
    r"\usepackage{float}",
    r"\usepackage{caption}",
    r"\usepackage{xcolor}",
    r"\usepackage{xurl}",
    r"\usepackage[hidelinks]{hyperref}",
    r"\usepackage{cite}",
]

register_template(LatexTemplate(
    name="ieee-conference",
    language="en",
    document_class="IEEEtran",
    preamble=_IEEE_CONF_PREAMBLE,
    title_page_fn=_ieee_conf_title_page,
    abstract_commands=(
        r"\begin{abstract}",
        r"",  # no separate English abstract
        r"\end{abstract}",
    ),
))


# ── ieee-journal ──

def _ieee_journal_title_page(meta: dict, title: str, body: list[str]) -> None:
    body.extend([
        rf"\title{{{convert_inline(title)}}}",
        r"\author{Author Name\\Institution\\City, Country\\email@example.com}",
        r"\markboth{IEEE Transactions on \emph{Field}, Vol.~XX, No.~XX, Month~Year}",
        r"\maketitle",
        "",
    ])


_IEEE_JOURNAL_PREAMBLE = [
    r"\documentclass[journal]{IEEEtran}",
    r"\usepackage{amsmath,amssymb}",
    r"\usepackage{graphicx}",
    r"\usepackage{booktabs}",
    r"\usepackage{array}",
    r"\usepackage{multirow}",
    r"\usepackage{float}",
    r"\usepackage{caption}",
    r"\usepackage{xcolor}",
    r"\usepackage{xurl}",
    r"\usepackage[hidelinks]{hyperref}",
    r"\usepackage{cite}",
    r"\usepackage{algorithmic}",
    r"\usepackage{algorithm}",
]

register_template(LatexTemplate(
    name="ieee-journal",
    language="en",
    document_class="IEEEtran",
    preamble=_IEEE_JOURNAL_PREAMBLE,
    title_page_fn=_ieee_journal_title_page,
    abstract_commands=(
        r"\begin{abstract}",
        r"",
        r"\end{abstract}",
    ),
))


# ── elsevier-journal ──

def _elsevier_title_page(meta: dict, title: str, body: list[str]) -> None:
    body.extend([
        r"\begin{frontmatter}",
        rf"\title{{{convert_inline(title)}}}",
        r"\author{Author Name\corref{cor1}}",
        r"\cortext[cor1]{Corresponding author.}",
        r"\address{Institution, City, Country}",
    ])
    if meta.get("title_en"):
        pass  # Elsevier handles via \title[en]{...}
    body.extend([
        r"\end{frontmatter}",
        "",
    ])


_ELSEVIER_PREAMBLE = [
    r"\documentclass[review,3p,twocolumn]{elsarticle}",
    r"\usepackage{amsmath,amssymb}",
    r"\usepackage{graphicx}",
    r"\usepackage{booktabs}",
    r"\usepackage{array}",
    r"\usepackage{multirow}",
    r"\usepackage{float}",
    r"\usepackage{caption}",
    r"\usepackage{xcolor}",
    r"\usepackage{xurl}",
    r"\usepackage[hidelinks]{hyperref}",
    r"\usepackage{lineno}",
    r"\linenumbers",
]

register_template(LatexTemplate(
    name="elsevier-journal",
    language="en",
    document_class="elsarticle",
    preamble=_ELSEVIER_PREAMBLE,
    title_page_fn=_elsevier_title_page,
    abstract_commands=(
        r"\begin{abstract}",
        r"",
        r"\end{abstract}",
    ),
))


# ── springer-journal ──

def _springer_title_page(meta: dict, title: str, body: list[str]) -> None:
    body.extend([
        rf"\title{{{convert_inline(title)}}}",
        r"\author{Author Name \and Co-Author Name}",
        r"\institute{Institution, City, Country \email{email@example.com}}",
        r"\maketitle",
        "",
    ])


_SPRINGER_PREAMBLE = [
    r"\documentclass[smallextended]{svjour3}",
    r"\usepackage{amsmath,amssymb}",
    r"\usepackage{graphicx}",
    r"\usepackage{booktabs}",
    r"\usepackage{array}",
    r"\usepackage{multirow}",
    r"\usepackage{float}",
    r"\usepackage{caption}",
    r"\usepackage{xcolor}",
    r"\usepackage{xurl}",
    r"\usepackage[hidelinks]{hyperref}",
]

register_template(LatexTemplate(
    name="springer-journal",
    language="en",
    document_class="svjour3",
    preamble=_SPRINGER_PREAMBLE,
    title_page_fn=_springer_title_page,
    abstract_commands=(
        r"\begin{abstract}",
        r"",
        r"\end{abstract}",
    ),
))


# ──────────────────────────────────────────────────────────
# Main render function
# ──────────────────────────────────────────────────────────

def render(md_path: Path, tex_path: Path, manifest_path: Path) -> None:
    root = md_path.parent
    text = md_path.read_text(encoding="utf-8", errors="replace")
    source_hash = sha256(md_path)
    first_heading = ""
    body: list[str] = []
    table_lines: list[str] = []
    pending_table_caption = ""
    in_math = False
    manifest = {
        "source": str(md_path),
        "source_hash": source_hash,
        "template": "",
        "title": "",
        "headings": [],
        "figures": [],
        "tables": 0,
        "references": 0,
    }

    lines = text.splitlines()
    ref_entries: dict[int, str] = {}  # {ref_number: raw_text}
    in_references_section = False

    for line_index, raw in enumerate(lines):
        line = raw.rstrip()

        # Track if we're in the references section
        if re.match(r"^#{1,6}\s+.*(?:参考文献|References|Bibliography)", line.strip()):
            in_references_section = True

        # Collect reference entries: [N] Author. Title. Journal, Year. DOI: ...
        ref_match = re.match(r"^\[(\d+)\]\s+(.+)$", line.strip())
        if ref_match and in_references_section:
            ref_num = int(ref_match.group(1))
            ref_entries[ref_num] = ref_match.group(2).strip()
            continue  # Don't add to body; we'll generate thebibliography block

        if line.strip() == "---":
            continue
        leading_caption = re.match(r"^\*?(表\s*\d+.+?)\*?\s*$", line.strip())
        next_line = ""
        for lookahead in lines[line_index + 1:]:
            next_line = lookahead.strip()
            if next_line:
                break
        next_is_table = next_line.startswith("|") and next_line.endswith("|")
        if leading_caption and not table_lines and next_is_table:
            pending_table_caption = leading_caption.group(1)
            continue
        if line.strip().startswith("|") and line.strip().endswith("|"):
            table_lines.append(line)
            continue
        if table_lines:
            caption_match = re.match(r"^\*?(表\s*\d+.+?)\*?\s*$", line.strip())
            if caption_match:
                flush_table(table_lines, body, manifest, caption_match.group(1))
                pending_table_caption = ""
                continue
            flush_table(table_lines, body, manifest, pending_table_caption)
            pending_table_caption = ""

        if not line.strip():
            body.append("")
            continue
        if line.strip() == "$$":
            body.append(r"\[" if not in_math else r"\]")
            in_math = not in_math
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            raw_heading = heading.group(2).strip()
            clean_heading = strip_heading_number(raw_heading)
            manifest["headings"].append(raw_heading)
            if not first_heading:
                first_heading = clean_heading
                if clean_heading == "摘要":
                    continue

            if clean_heading in {"摘要", "中文摘要"}:
                body.append(r"\awardabstracttitle")
                continue
            if clean_heading == "Abstract":
                body.append(r"\journalabstractentitle")
                body.append(r"% Abstract")
                continue
            if clean_heading in {"关键词 Keywords", "关键词"}:
                body.append(r"\journalkeywordtitle")
                continue

            if level == 1:
                body.append(rf"\section{{{convert_inline(clean_heading)}}}")
                continue

            command = "subsection" if level == 2 else "subsubsection"
            body.append(rf"\{command}{{{convert_inline(clean_heading)}}}")
            continue

        figure = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", line)
        if figure:
            caption, target = figure.groups()
            manifest["figures"].append({"caption": caption, "target": target})
            body.extend([
                r"\begin{figure}[H]",
                r"\centering",
                rf"\includegraphics[width=0.88\linewidth]{{{escape_plain(target)}}}",
                rf"\caption{{{convert_inline(caption)}}}",
                r"\end{figure}",
                "",
            ])
            continue

        # Regular body line — convert citations and escape for LaTeX
        body.append(convert_inline(line))

    flush_table(table_lines, body, manifest, pending_table_caption)
    metadata = read_metadata(root, first_heading)
    title = metadata["title_cn"]
    template_name = metadata.get("latex_template", "cn-journal-submission-v2")
    template = TEMPLATES.get(template_name, TEMPLATES["cn-journal-submission-v2"])
    manifest["template"] = template.name
    manifest["title"] = title

    # Build tex output based on selected template
    tex: list[str] = [
        "% Generated from full-paper.md. Do not edit manuscript content here.",
        f"% Source full-paper sha256: {source_hash}",
        f"% Template: {template.name}",
    ]

    # Base preamble from the selected template (packages + geometry),
    # with meta-driven documentclass options (font size / two-side layout).
    font_size = str(metadata.get("font_size") or "12pt")
    class_opts = f"UTF8,a4paper,{font_size}"
    if str(metadata.get("two_side", "")).lower() in ("1", "true", "yes"):
        class_opts += ",twoside"
    tex.extend(
        line.replace(
            r"\documentclass[UTF8,a4paper,12pt]{ctexart}",
            rf"\documentclass[{class_opts}]{{ctexart}}",
        )
        for line in template.preamble
    )

    if template.language == "zh":
        # Chinese template: premium setup — dynamic per-chapter headers,
        # colored hyperlinks + PDF metadata, meta-driven spacing/captions.
        meta_link = str(metadata.get("link_color") or "1F3864")
        meta_url = str(metadata.get("url_color") or meta_link)
        meta_spacing = str(metadata.get("line_spacing") or "1.5")
        tex.extend([
            rf"\definecolor{{pclink}}{{HTML}}{{{meta_link}}}",
            rf"\definecolor{{pcurl}}{{HTML}}{{{meta_url}}}",
            r"\hypersetup{colorlinks=true,linkcolor=pclink,citecolor=pclink,urlcolor=pcurl}",
            rf"\hypersetup{{pdftitle={{{convert_inline(title)}}},pdfauthor={{{convert_inline(str(metadata.get('author_line', '') or '匿名'))}}}}}",
            rf"\setstretch{{{meta_spacing}}}",
            r"\setlist{nosep}",
            r"\fancyhead[R]{\zihao{-5}\leftmark}",
            r"\newcommand{\awardabstracttitle}{\begin{center}{\heiti\zihao{3}摘\quad 要}\end{center}}",
            r"\newcommand{\journalabstracttitle}{\begin{center}{\heiti\zihao{3}摘\quad 要}\end{center}}",
            r"\newcommand{\journalabstractentitle}{\begin{center}{\bfseries\zihao{3}Abstract}\end{center}}",
            r"\newcommand{\journalkeywordtitle}{\vspace{0.4em}{\heiti 关键词：}}",
        ])
        if str(metadata.get("draft_watermark", "")).lower() in ("1", "true", "yes"):
            tex.extend([
                r"\usepackage{draftwatermark}",
                r"\SetWatermarkText{草\quad 稿}",
                r"\SetWatermarkScale{0.32}",
                r"\SetWatermarkLightness{0.94}",
            ])

    tex.append(r"\begin{document}")

    # Title page (template-specific)
    template.title_page_fn(metadata, title, tex)

    # 每章起新页:除首个 \section 外,每个一级节前插入 \clearpage
    # (meta.chapter_new_page 默认开启;置 0 恢复连续排版)。
    new_page_on = str(metadata.get("chapter_new_page", "1")).lower() not in ("0", "false", "no")
    if template.language == "zh" and new_page_on:
        seen_first = False
        new_body: list[str] = []
        for line in body:
            if line.startswith(r"\section{"):
                if seen_first:
                    new_body.append(r"\clearpage")
                seen_first = True
            new_body.append(line)
        body = new_body

    # Body content
    tex.extend(body)

    # Bibliography block — generate from collected reference entries
    if ref_entries:
        manifest["references"] = len(ref_entries)
        max_ref = max(ref_entries.keys())
        tex.append("")
        tex.append(rf"\begin{{thebibliography}}{{{max_ref}}}")
        tex.append(r"\small")
        for ref_num in sorted(ref_entries.keys()):
            key = f"src{ref_num:02d}"
            ref_text = escape_latex(ref_entries[ref_num])
            tex.append(rf"\bibitem{{{key}}} {ref_text}")
        tex.append(r"\end{thebibliography}")

    tex.append(r"\end{document}")
    tex.append("")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text("\n".join(tex), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_path")
    parser.add_argument("--tex-out")
    parser.add_argument("--manifest-out")
    args = parser.parse_args()
    root = Path(args.project_path).resolve()
    md_path = root / "full-paper.md"
    if not md_path.exists():
        raise SystemExit(f"missing full-paper.md: {md_path}")
    tex_out = Path(args.tex_out).resolve() if args.tex_out else root / "main.tex"
    manifest_out = Path(args.manifest_out).resolve() if args.manifest_out else root / "plan" / "latex-render-manifest.json"
    render(md_path, tex_out, manifest_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
