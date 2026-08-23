# 科研写作助手 (Research Writing Assistant)

本项目包含科研论文写作技能集。当用户提出与论文写作相关的任务时，请调用相应技能。

> **注意**：本文件是技能集的简明指引。完整的 subagent 行为规范（包括状态契约、反编造规则、去AI化规则、结构化输出格式等）请参见仓库根目录 `AGENTS.md`。

## 技能列表

| 技能名称 | 路径 | 用途 |
|----------|------|------|
| using-research-writing | skills/using-research-writing/SKILL.md | 入口技能，定义规则和路由 |
| paper-orchestration | skills/paper-orchestration/SKILL.md | 中型/整篇任务编排、任务包和能力使用审计 |
| brainstorming-research | skills/brainstorming-research/SKILL.md | 头脑风暴，确定论文类型和结构 |
| evidence-driven-writing | skills/evidence-driven-writing/SKILL.md | 文献驱动的引言、相关工作和背景段落 |
| writing-chapters | skills/writing-chapters/SKILL.md | 章节写作 |
| experiment-results-planning | skills/experiment-results-planning/SKILL.md | 实验协议、结果表格、mock 数据边界 |
| latex-output | skills/latex-output/SKILL.md | LaTeX 输出 |
| literature-review | skills/literature-review/SKILL.md | 文献综述 |
| figures-python | skills/figures-python/SKILL.md | Python 图表（450 DPI，顶刊配色） |
| figures-diagram | skills/figures-diagram/SKILL.md | 流程图/架构图 |
| peer-review | skills/peer-review/SKILL.md | 自审检查 |
| writing-core | skills/writing-core/SKILL.md | 去AI化规范、段落构建、排版 |
| prompts-collection | skills/prompts-collection/SKILL.md | 翻译/润色/去AI化/扩写缩写 |
| verification | skills/verification/SKILL.md | 声称完成前必须验证 |
| statistical-analysis | skills/statistical-analysis/SKILL.md | 统计分析 |
| environment-setup | skills/environment-setup/SKILL.md | 环境配置 |
| writing-humanities | skills/writing-humanities/SKILL.md | 文科论文写作 |
| writing-medical | skills/writing-medical/SKILL.md | 医学论文写作 |
| writing-law | skills/writing-law/SKILL.md | 法学论文写作 |

## 使用方式

1. 用户提出论文写作任务
2. 调用 `using-research-writing` 技能确定流程
3. 中型或整篇任务先调用 `paper-orchestration`
4. 按技能指引完成头脑风暴、证据映射、章节写作和验证

## 核心规则

- 任何写作任务前必须完成头脑风暴
- 中型任务必须有任务包、两阶段 review 和 capability-use audit
- 引言和相关工作必须先完成 evidence map
- 稿件交付前运行 `python3 scripts/research_quality_gate.py --project <paper-project>`
- 必须创建 plan/ 目录记录项目信息
- 每章写完必须让用户确认
- 绝不编造文献
- 绝不编造 DOI、作者、年份、数据、实验结果
- 报告中的所有数值必须来自实际文件读取或命令统计

## 去AI化硬性规则

| 禁用词/句式 | 全文上限 | 替换方式 |
|------------|---------|--------|
| "本文" | 15次 | "本研究""笔者"或被动句 |
| "通过...实现" | 5次 | "XX使YY成为可能" |
| "能够" | 3次 | 删除或替换为具体动词 |
| "首先...其次...最后..." | 0次 | 语义衔接 |
| "值得注意的是" | 0次 | 删除 |
| "针对上述研究空白" | 0次 | 删除 |
| "从表X可以看出" | 0次 | 直接陈述发现 |
| "近年来" | 0次 | 删除或改为具体年份 |
| "随着...的发展" | 0次 | 删除 |

## 段落约束

- 正文段落 150-300 字
- 单段不得超过 350 字
- 段落之间必须空一行
- 正文默认不使用加粗和斜体
- 正文段落不用项目符号

## 单一源原则

`full-paper.md` 是唯一真相源。`main.tex` 由 `full-paper.md` 单向生成。禁止在 LaTeX 阶段修改内容。
