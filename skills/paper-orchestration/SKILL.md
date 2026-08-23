---
name: paper-orchestration
description: Use when a research-writing task spans multiple sections, medium-sized revisions, full-paper drafting, or repeated quality failures
---

# Paper Orchestration

This skill controls the workflow around the writing skills. It prevents "one prompt writes the paper" behavior by forcing stage detection, task packets, review gates, and a capability-use audit.

## Hard Gate

For any medium task or full-paper task, do not write manuscript text until these exist or are created:

- `plan/project-overview.md`
- `plan/outline.md`
- `plan/progress.md`
- a task packet for the current section or deliverable
- for full-paper drafting or redrafting, `plan/chapter-architecture.md`

For review/framework papers, "no experiments" does not mean "no data or figures". Do not draft the final manuscript until these review assets exist or are explicitly created:

- `plan/review-framework-asset-plan.md`
- `figures/data-manifest.md`
- at least one source-backed CSV/JSON file under `data/` or `figures/data/`
- at least one generated figure script under `figures/`
- at least one referenced figure in the manuscript plan, with PNG and SVG outputs expected
- at least two evidence/industry tables planned for `full-paper.md`

These assets may be literature-derived or source-derived, but they must not be mock/synthetic planning data in a final submission.

Medium task means any request that affects more than one paragraph, one subsection, one chapter, one figure/table set, or any claim tied to references or experiments.

## Full-Paper Redraft Gate

For a full-paper draft, the controller must first lock the chapter architecture. Do not inherit an old chapter split if the user, target venue, or paper type implies a different structure.

For computer science / engineering SCI papers, use this body structure unless the user or target template explicitly requires otherwise:

1. Introduction, with related work integrated into the motivation and research-gap argument.
2. Methodology.
3. Dataset and Experimental Setting, either standalone or integrated into Methodology/Results when short.
4. Experimental Results and Analysis.
5. Discussion.

Abstract, Conclusion, and References may be generated as supporting files, but they must not hide weak body chapters or inflate the chapter count. A standalone Related Work chapter is only allowed when the target outline explicitly demands it.

Create `plan/chapter-architecture.md` before drafting. It must list the exact required chapter files, target role, minimum body length, owner agent, and whether the chapter may use planning placeholders.

```markdown
## Required chapter files
- chapters/01_Introduction.md | min_chars=4500 | agent=required | placeholders=no
- chapters/02_Methodology.md | min_chars=4500 | agent=required | placeholders=no
```

If this file exists, the quality gate must treat extra or missing chapter files as failures.

## Multi-Agent Chapter Gate

For any full-paper draft or redraft, the controller must not write all chapters itself. It must:

- create one task packet per major chapter;
- dispatch a separate fresh agent for each major chapter;
- give each agent only the relevant task packet, source excerpts, evidence map, experiment protocol, and hard rejection checks;
- assign disjoint write ownership so that two agents never edit the same chapter file;
- record the agent, prompt summary, inputs, output path, and review status in `plan/chapter-agent-provenance.md`;
- perform a controller review after agent output before claiming progress.

Subagent / multi-role delegation is authorized by default for this project. Do not stop to ask for a fixed authorization sentence before dispatching chapter agents. If the runtime truly has no subagent facility, continue with bounded single-agent execution only when the task can still preserve separate task packets, disjoint file ownership, provenance records, and controller review; otherwise mark `MANUAL_REQUIRED` with the missing runtime capability. Do not silently fall back to one-pass generation.

## Stage Detection

Classify the current work before acting:

| Stage | Trigger | Required next skill |
|---|---|---|
| S0 Scope | topic, target, structure unclear | `brainstorming-research` |
| S1 Evidence | references, Introduction, Related Work | `evidence-driven-writing` + `literature-review` |
| S1A Review Assets | review/framework paper, industry analysis, conceptual framework, no experiment chapter | `figures-python` or `figures-diagram` + `verification` |
| S2 Method | model, algorithm, system, method section | `writing-chapters` with method flow gate |
| S3 Experiments | setup, results, tables, charts | `experiment-results-planning` + `figures-python` |
| S4 Drafting | section text | `writing-chapters` |
| S5 Review | quality, consistency, submission risk | `peer-review` + `verification` |

Record the stage in `plan/progress.md`.

If the user provides only a broad direction or topic, use the project default scope instead of asking for confirmation: Chinese engineering review/framework paper, public literature/standards/application-scenario evidence, no invented experimental data, Markdown draft first, LaTeX/PDF later if requested, and no final/submission PASS claim.

## Task Packet

Before dispatching a section task, create a persistent packet under `plan/task-packets/`. Conversation-only packets are not acceptable for medium or full-paper work because they cannot be audited later.

```markdown
## Task Packet
- Scope:
- Files to read:
- Files allowed to edit:
- Required skills:
- Evidence/data inputs:
- Required artifacts:
- Rejection checks:
- Validation commands:
```

Subagents must receive the task packet, not the entire vague project. If subagents are available, split independent work into literature mapping, method architecture, experiment planning, figure generation, and review. Do not let multiple agents edit the same file.

For chapter-writing packets, add:

- Target chapter file and exclusive owner.
- Required argument chain, in paragraph roles rather than bullet content.
- Minimum prose length.
- Required sources and data artifacts.
- Required review/framework asset plan when the paper has no experiment chapter.
- Prohibited structure, especially bullet-like lists, process notes, and old chapter scaffolding.
- Required handoff format: status, file path changed, unresolved evidence/data gaps, and self-review.

## Review Gates

Every medium task requires an independent review board before completion. The review roles, weights, and minimum-finding requirements are defined in `papers/scripts/review_roles.py` (the single authoritative source). At minimum, the following 6 core roles must be covered:

1. **journal-editor** — editorial fitness, contribution clarity, target venue alignment
2. **methodology-statistics** — research design, statistical validity, reproducibility
3. **evidence-reproducibility** — evidence quality, data traceability, claim support
4. **skeptic** — adversarial challenge, alternative explanations, hidden assumptions
5. **reader** — readability, logical flow, accessibility to non-specialists
6. **operator** — process compliance, artifact completeness, workflow integrity

Each review must produce a structured report with evidence table, severity classification (P0/P1/P2), and quoted fragments from the manuscript. P0 findings block completion. P1 findings require a waiver record if not fixed.

For full paper production (S8 review board), all 11 roles defined in `review_roles.py` are dispatched. See `runner_auto.py:run_auto_review_board` for the execution implementation.

If any review fails, fix before moving to the next task.

## Status Contract

`STATUS: PASS` is reserved for final/submission completion. If a workspace is only a draft, if any terminal gate was skipped, or if PowerShell, LaTeX/PDF, independent review, or strict quality artifacts are missing, write `STATUS: FAIL` or `STATUS: MANUAL_REQUIRED`.

Before final completion, run:

```bash
python scripts/status_contract.py <paper-project> --submission
```

Do not write `DRAFT PASS` together with `STATUS: PASS`; downstream scripts treat that as a hard failure.

## Capability-Use Audit

At the end of every medium task, write a short audit in `plan/progress.md`:

```markdown
### Capability-use audit
- Required skills:
- Skills actually used:
- Inputs consumed:
- Inputs not used and why:
- Artifacts produced:
- Verification run:
- Remaining risk:
```

The task is not complete without this audit.

## Common Failures

- Treating user instructions as manuscript content. Convert instructions into structure or edits; never paste them into the body.
- Claiming a section is "done" when it only has headings and placeholders.
- Running style checks while skipping evidence, data, and claim checks.
- Marking a review/framework paper complete after prose-only synthesis with no source-backed data files, figure scripts, or referenced figures.
- Producing tables instead of prose to hide weak argumentation.
- Keeping an old chapter split after the user rejects it. Rebuild the chapter architecture first.
- Letting the controller write a full manuscript sequentially instead of using one independent agent per major chapter.
- Accepting short, enumerative prose because it passes keyword checks. Length, paragraph flow, evidence use, and agent provenance must all be reviewed.
