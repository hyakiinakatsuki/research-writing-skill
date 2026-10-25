# Outline Library — 综述/论文结构先验(P1-6)

借鉴来源:SurveyForge db_survey 大纲库 + LongWriter 字数配额
(`docs/writing-agent-benchmark.md` 路线图 P1-6)。

用途:`skill-native-runner.run_stage_bootstrap` 在 S0 按论文类型选取匹配小节,
写入 `<project>/plan/outline-prior.md`,作为章节架构与写作配额的结构参照。
本文件是确定性文本资产;修改走正常工作流提交,运行中论文消费的是只读快照副本。

## review-framework 综述/框架型

标准七章骨架(与 DEFAULT_REVIEW_CHAPTER_LINES 对齐),字数配比为 target 配额参考:

| 章 | 功能 | 配额占比 |
|---|---|---|
| 00-abstract | 背景-问题-方法-发现-意义五要素 | 固定 ~600 字 |
| 01-introduction | 现象切入 → 研究空白 → 本文综述范围与组织逻辑 | ~12% |
| 02-literature-framework | 按主题聚类(非流水账):每簇内按时间/方法谱系展开,簇末给批判性小结 | ~25% |
| 03-framework-construction | 框架主体:组件、维度、算子或坐标;每组件给出设计理由与文献映射 | ~22% |
| 04-analysis-discussion | 用框架横向比较文献:一致性、分歧、反例 | ~20% |
| 05-conclusion | 结论、局限(必写)、未来方向 | ~8% |
| 08-references | 参考文献(≥25 篇,50 篇常见) | 剩余 |

批判性综合最低要求:全文至少出现 3 处"文献间矛盾/方法局限互证/演化脉络转折"
的显式分析段,这是评审区分 70 分与 80 分的主要观测点。

## empirical 实证型

摘要 → 引言(问题+贡献清单) → 相关工作(对比定位) → 方法(可复现细节) →
实验设置 → 结果与分析(表格驱动,每个数字有来源) → 讨论(威胁有效性必写) →
结论。数字一律走 [[Fxxx|值]] 锚定协议。

## 通用

无法判定类型时的保守骨架:摘要 → 引言 → 背景与相关工作 → 主体分析(2-3 章) →
讨论 → 结论。遵守全部 DEAI 与证据锚点规则。
