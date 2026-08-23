"""
deai_constants.py — 去AI化禁用词单一权威源

所有组件必须从此文件导入，禁止维护本地副本。
权威源合并自：
  - skill-native-runner.py AUTO_DEAI_WORDS_ABSOLUTE / AUTO_DEAI_WORDS_LIMITED（最全版本）
  - strict_quality_gate.py ABSOLUTE_PATTERNS / LIMITED_PATTERNS
  - agent-stage-executor.py DEAI_RULES
  - CLAUDE.md 六、去AI化硬性规则
  - AGENTS.md 五、去AI化规则

维护规则：
  - 新增禁用词只在此文件添加
  - 下游组件通过 import 使用，不得复制
  - 变更需同步更新 CLAUDE.md 和 AGENTS.md 的规则表
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 绝对禁用模式（出现即 FAIL，允许 0 次）
# 支持纯文本和正则表达式
# ---------------------------------------------------------------------------
ABSOLUTE_PATTERNS: list[str] = [
    # --- 空壳强调句 ---
    "值得注意的是",
    "需要指出的是",
    "需要说明的是",
    # --- 研究空白套路 ---
    "针对上述研究空白",
    # --- 成果堆砌 ---
    "总体来看",
    "综合上述实验结果",
    "基于上述局限性",
    "近年来",
    "取得了显著成效",
    "取得了显著进展",
    "具有重要意义",
    "越来越多的研究",
    "本文的主要贡献",
    # --- 反大白话 ---
    "说白了",
    "说白了就是",
    "其实就是",
    "实际上就是",
    "简单来说",
    "简单来讲",
    "简单地说",
    "换句话说",
    "举个例子来说",
    "大家都知道",
    "众所周知",
    "很好的效果",
    "不错的结果",
    "挺好的",
    "越来越重要",
    "越来越受到重视",
    "挺多的",
    "比较少",
    "不是很多",
    "做了很多工作",
    "取得了不少成果",
    "做了一些工作",
    "做了一件事",
    # --- 反空泛表述 ---
    "具有深远意义",
    "产生了深远影响",
    "产生了重要影响",
    "得到了广泛关注",
    "引起了广泛关注",
    "发挥了重要作用",
    "扮演着重要角色",
    "取得了长足进步",
    "取得了突破性进展",
    "日益凸显",
    "日趋严峻",
    # --- 扩展：高频 AI 标记 ---
    "在此基础上",
    "在此背景下",
    "在此前提下",
    "不可忽视的作用",
    "起着举足轻重的作用",
    "具有重要意义",
    "有着广泛的应用前景",
    "提供了新的思路",
    "提供了有力的支撑",
    "取得了显著的成效",
    "取得了丰硕的成果",
    "具有较高的准确率",
    "具有良好的性能",
    "在实际应用中",
    "在工程实践中",
    "为理论依据",
    "奠定了基础",
    "提供了理论依据",
    "奠定了坚实的基础",
    "为解决这一问题",
    "为该领域",
    "指明了方向",
    "打开了新的大门",
    "开辟了新的途径",
    "提供了有益的启示",
    "做出了重要贡献",
    "引发了广泛讨论",
    "受到了越来越多的关注",
    "得到了长足的发展",
    "展现出了巨大的潜力",
]

# ---------------------------------------------------------------------------
# 绝对禁用正则模式（regex 版本，用于 re.findall）
# ---------------------------------------------------------------------------
ABSOLUTE_PATTERNS_REGEX: list[str] = [
    r"随着.*的发展",
    r"首先.*其次.*最后",
    r"说白了.*",
    r"其实就是.*",
    r"简单来说.*",
    r"比如说.*",
]

# ---------------------------------------------------------------------------
# 限量禁用模式（超过阈值即 FAIL）
# 格式：(pattern, max_allowed)
# ---------------------------------------------------------------------------
LIMITED_PATTERNS: list[tuple[str, int]] = [
    (r"本文", 15),
    (r"通过.*实现", 5),
    (r"能够", 3),
    (r"综上所述", 2),
    (r"总之", 2),
    (r"具体而言", 2),
    (r"具体来说", 2),
    (r"从表.*可以看出", 0),
    (r"如表.*所示", 0),
    (r"如图.*所示", 0),
    (r"有效地", 3),
    (r"显著地", 3),
    (r"在一定程度上", 2),
    (r"实验结果表明", 3),
    (r"提出了一种", 2),
    (r"研究表明", 4),
    (r"研究发现", 3),
    (r"实验结果", 5),
    (r"仿真结果", 3),
    (r"在此基础上", 1),
    (r"与此同时", 2),
    (r"值得注意", 0),
]

# ---------------------------------------------------------------------------
# 段落约束
# ---------------------------------------------------------------------------
PARAGRAPH_MIN_CHARS = 150
PARAGRAPH_WARN_CHARS = 350      # Warning threshold (auto-fixable)
PARAGRAPH_MAX_CHARS = 500       # Hard fail threshold

# ---------------------------------------------------------------------------
# 兼容性导出：dict 格式（供 agent-stage-executor.py 使用）
# ---------------------------------------------------------------------------
DEAI_WORDS_ABSOLUTE: list[str] = list(ABSOLUTE_PATTERNS)

DEAI_WORDS_LIMITED_DICTS: list[dict] = [
    {"word": pattern, "max_total": max_val}
    if pattern not in (r"本文", r"提出了一种")
    else {"word": pattern, "max_per_chapter": 3 if pattern == r"本文" else 1, "max_total": max_val}
    for pattern, max_val in LIMITED_PATTERNS
]

DEAI_PATTERNS_ABSOLUTE: list[tuple[str, str]] = [
    (pat, pat) for pat in ABSOLUTE_PATTERNS_REGEX
]

# ---------------------------------------------------------------------------
# 英文绝对禁用模式（English AI-slop patterns, 0 occurrences allowed）
# Sourced from research-writing-skill/skills/prompts-collection/SKILL.md
# ---------------------------------------------------------------------------
EN_ABSOLUTE_PATTERNS: list[str] = [
    # Original 10
    "leverage",
    "delve into",
    "tapestry",
    "underscore",
    "pivotal",
    "nuanced",
    "foster",
    "elucidate",
    "intricate",
    "paramount",
    # Expanded: filler adjectives/adverbs
    "groundbreaking",
    "aforementioned",
    "cutting-edge",
    "robust",
    "seamless",
    "holistic",
    "paradigm shift",
    "game-changing",
    "state-of-the-art",
    "comprehensive overview",
    "in the realm of",
    "in light of",
    "shed light on",
    "it goes without saying",
    "needless to say",
    "it is important to note",
    "as a matter of fact",
    "by and large",
    "at the end of the day",
    "in the grand scheme",
    "rests on the shoulders",
    "stands as a testament",
    "serves as a reminder",
    "cannot be overstated",
    "plays a crucial role",
    "has gained significant attention",
    "has attracted considerable interest",
    "is of paramount importance",
    "the rapid advancement of",
    "the ever-increasing",
    "a growing body of literature",
    # Expanded: domain-specific AI-generated patterns
    "this paper proposes a novel framework",
    "extensive experiments demonstrate",
    "the experimental results show that",
    "our method achieves state-of-the-art",
    "comprehensive experiments validate",
    "ablation studies confirm",
    "outperforms all baselines",
    "significant improvements over",
    "the effectiveness of our approach",
    "it is worth noting that",
    "notably",
    "remarkably",
    "fundamentally",
    "essentially",
    "arguably",
    "interestingly",
    "surprisingly",
    "importantly",
    "significantly",
    "effectively",
    "efficiently",
    "considerably",
    "substantially",
]

# ---------------------------------------------------------------------------
# 英文禁用过渡/强调短语（English banned transitions, 0 occurrences allowed）
# Sourced from style_check.sh — merged here as single authority
# ---------------------------------------------------------------------------
EN_BANNED_TRANSITIONS: list[str] = [
    "first and foremost",
    "to begin with",
    "moreover",
    "furthermore",
    "last but not least",
    "it is worth noting that",
    "importantly",
    # Expanded
    "on the other hand",
    "having said that",
    "be that as it may",
    "in a similar vein",
    "as previously mentioned",
    "as discussed earlier",
    "it should be noted",
    "it bears mentioning",
    "taken together",
    "to sum up",
    "in summary",
    "to conclude",
    "all things considered",
]

# ---------------------------------------------------------------------------
# 主观第一人称禁用短语（0 occurrences allowed）
# Sourced from style_check.sh — merged here as single authority
# ---------------------------------------------------------------------------
SUBJECTIVE_FIRST_PERSON: list[str] = [
    "我认为",
    "我觉得",
    "我个人认为",
    "我个人看法",
    "我的研究",
    "in my opinion",
    "i believe",
]
