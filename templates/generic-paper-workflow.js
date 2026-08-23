export const meta = {
  name: 'generic-paper-writing',
  description: 'LEGACY/UNSAFE example only: disabled because it is not evidence-bound',
  phases: [
    { title: 'Phase 1 Front Matter', model: 'sonnet' },
    { title: 'Phase 2 Core Chapters' },
    { title: 'Phase 3 Experiments & Results' },
    { title: 'Phase 4 Discussion & Conclusion' },
    { title: 'Phase 5 References & Figures' },
    { title: 'Phase 6 Fix & Compile' },
  ],
}

throw new Error('This generic legacy workflow is disabled. It is not evidence-bound and may generate unverified results. Use papers/paper-v10-workflow.js or a workflow that calls strict gates and render_latex.py.')

// ============================================================
// CONFIGURATION - Edit this section for each new paper
// ============================================================
const CONFIG = {
  // Paper info
  TOPIC_CN: '论文中文题目',
  TOPIC_EN: 'Paper English Title',

  // Output directory
  OUTPUT_DIR: '/path/to/paper/output',

  // Chapter structure (modify as needed)
  CHAPTERS: {
    abstract: { enabled: true, words: '200-300字摘要+英文摘要' },
    introduction: { enabled: true, words: '1500-2000字', refs: '5-8篇' },
    literature: { enabled: true, words: '2000-2500字', refs: '15-20篇' },
    methodology: { enabled: true, words: '2500-3000字', formulas: true },
    experiments: { enabled: true, words: '1500-2000字' },
    results: { enabled: true, words: '2500-3000字', figures: true },
    discussion: { enabled: true, words: '1500-2000字', refs: '5-8篇' },
    conclusion: { enabled: true, words: '800-1000字' },
    references: { enabled: true, count: '20-25篇', ratio: '中英文6:4' },
  },

  // Domain-specific guidance
  DOMAIN: '学科领域（如：计算机科学、医学、管理学等）',
  JOURNAL: '目标期刊/会议（如：《烟草科技》、IEEE Trans等）',

  // Key data points for abstract/results
  KEY_RESULTS: {
    primary_metric: '主要指标及数值',
    secondary_metric: '次要指标及数值',
    improvement: '相比基线的提升幅度',
  },

  // Figure count
  FIGURE_COUNT: 8,
}

const O = CONFIG.OUTPUT_DIR
const T_CN = CONFIG.TOPIC_CN
const T_EN = CONFIG.TOPIC_EN

// ============================================================
// Phase 1: Front matter
// ============================================================
phase('Phase 1 Front Matter')
await agent(
  'Write the front matter for a research paper.\n\n' +
  'Paper title (CN): ' + T_CN + '\n' +
  'Paper title (EN): ' + T_EN + '\n' +
  'Domain: ' + CONFIG.DOMAIN + '\n' +
  'Target journal: ' + CONFIG.JOURNAL + '\n\n' +
  'Save to: ' + O + '/chapters/00-abstract.md\n\n' +
  'Requirements:\n' +
  '1. Chinese abstract: 200-300 words, structured with Purpose/Methods/Results/Conclusion\n' +
  '2. English abstract: corresponding to Chinese version\n' +
  '3. Chinese keywords: 5-8 terms\n' +
  '4. English keywords: matching Chinese\n' +
  '5. Author placeholder with institution, fund project info\n\n' +
  'Key results for abstract: ' + JSON.stringify(CONFIG.KEY_RESULTS) + '\n\n' +
  'Writing style: academic, concise, no empty phrases. Follow ' + CONFIG.JOURNAL + ' format.',
  { label: 'abstract-writer', phase: 'Phase 1 Front Matter' }
)

// ============================================================
// Phase 2: Core chapters (parallel)
// ============================================================
phase('Phase 2 Core Chapters')
const [intro, litReview, methodology] = await parallel([
  () => agent(
    'Write the Introduction chapter for a research paper.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Domain: ' + CONFIG.DOMAIN + '\n' +
    'Save to: ' + O + '/chapters/01-introduction.md\n\n' +
    'Requirements (~' + CONFIG.CHAPTERS.introduction.words + '):\n' +
    '1. Research background - domain context, trends, importance\n' +
    '2. Research problem - limitations of current methods\n' +
    '3. Research significance - theoretical and practical\n' +
    '4. Research content - main contributions (3-4 points)\n' +
    '5. Paper structure - chapter overview\n\n' +
    'Cite ' + CONFIG.CHAPTERS.introduction.refs + ' references using [1][2] format.\n' +
    'Use specific data to support claims. Academic language, continuous paragraphs, no bullet lists.\n' +
    'Chinese writing.',
    { label: 'intro-writer', phase: 'Phase 2 Core Chapters' }
  ),
  () => agent(
    'Write the Literature Review chapter for a research paper.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Domain: ' + CONFIG.DOMAIN + '\n' +
    'Save to: ' + O + '/chapters/02-literature-review.md\n\n' +
    'Requirements (~' + CONFIG.CHAPTERS.literature.words + '):\n' +
    '1. Review 3-4 topic areas relevant to the paper\n' +
    '2. For each area: key methods, representative works, limitations\n' +
    '3. Identify research gaps that this paper addresses\n' +
    '4. Position this paper relative to existing work\n\n' +
    'Cite ' + CONFIG.CHAPTERS.literature.refs + ' references (mixed Chinese/English, [1][2] format).\n' +
    'Organized by theme, not simple listing. Point out gaps, lead to contributions.\n' +
    'Academic language, continuous paragraphs. Chinese writing.',
    { label: 'litreview-writer', phase: 'Phase 2 Core Chapters' }
  ),
  () => agent(
    'Write the Methodology chapter for a research paper.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Domain: ' + CONFIG.DOMAIN + '\n' +
    'Save to: ' + O + '/chapters/03-methodology.md\n\n' +
    'Requirements (~' + CONFIG.CHAPTERS.methodology.words + '):\n' +
    '1. System/method overview (architecture diagram reference)\n' +
    '2. Data preprocessing pipeline\n' +
    '3. Feature engineering (define ALL features with formulas)\n' +
    '4. Model design (algorithms, math formulas in LaTeX format)\n' +
    '5. Evaluation metrics and experimental design\n' +
    '6. Hyperparameter configuration\n\n' +
    'Include feature definition table (Table 1) and hyperparameter table.\n' +
    'Technical details sufficient for reproducibility.\n' +
    'Chinese writing. Cite methodology references.',
    { label: 'method-writer', phase: 'Phase 2 Core Chapters' }
  )
])

// ============================================================
// Phase 3: Experiments & Results (parallel)
// ============================================================
phase('Phase 3 Experiments & Results')
const [experiments, results] = await parallel([
  () => agent(
    'Write the Experiments section for a research paper.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Save to: ' + O + '/chapters/04-experiments.md\n\n' +
    'Requirements (~' + CONFIG.CHAPTERS.experiments.words + '):\n' +
    '1. Experimental environment (software, hardware)\n' +
    '2. Dataset description (source, size, splits, distribution)\n' +
    '3. Baseline methods\n' +
    '4. Evaluation metrics definitions\n' +
    '5. Hyperparameter configuration table\n\n' +
    'Include dataset statistics table and parameter config table.\n' +
    'Chinese writing, academic standard.',
    { label: 'experiments-writer', phase: 'Phase 3 Experiments & Results' }
  ),
  () => agent(
    'Write the Results and Analysis section for a research paper.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Save to: ' + O + '/chapters/05-results.md\n\n' +
    'Key results: ' + JSON.stringify(CONFIG.KEY_RESULTS) + '\n\n' +
    'Requirements (~' + CONFIG.CHAPTERS.results.words + '):\n' +
    '1. Model performance comparison (all metrics, statistical tests)\n' +
    '2. Main analysis results with visualizations\n' +
    '3. Additional analysis (ablation, sensitivity, etc.)\n' +
    '4. Real-world validation or case study if applicable\n\n' +
    'Each result must reference the corresponding figure/table number.\n' +
    'Data must be specific and verifiable. Analysis must explain WHY, not just describe WHAT.\n' +
    'Chinese writing.',
    { label: 'results-writer', phase: 'Phase 3 Experiments & Results' }
  )
])

// ============================================================
// Phase 4: Discussion & Conclusion (parallel)
// ============================================================
phase('Phase 4 Discussion & Conclusion')
const [discussion, conclusion] = await parallel([
  () => agent(
    'Write the Discussion chapter for a research paper.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Domain: ' + CONFIG.DOMAIN + '\n' +
    'Save to: ' + O + '/chapters/06-discussion.md\n\n' +
    'Requirements (~' + CONFIG.CHAPTERS.discussion.words + '):\n' +
    '1. Key findings and their explanations\n' +
    '2. Comparison with existing methods\n' +
    '3. Theoretical contributions\n' +
    '4. Practical implications and recommendations\n' +
    '5. Limitations and threats to validity\n' +
    '6. Future work directions\n\n' +
    'Objective and thorough. Do not回避 problems.\n' +
    'Chinese writing. Cite relevant references.',
    { label: 'discussion-writer', phase: 'Phase 4 Discussion & Conclusion' }
  ),
  () => agent(
    'Write the Conclusion chapter for a research paper.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Save to: ' + O + '/chapters/07-conclusion.md\n\n' +
    'Requirements (~' + CONFIG.CHAPTERS.conclusion.words + '):\n' +
    '1. Research summary\n' +
    '2. Main contributions (3-4 points)\n' +
    '3. Future work directions\n\n' +
    'Concise and powerful. Do not introduce new information.\n' +
    'Highlight contributions. Chinese writing.',
    { label: 'conclusion-writer', phase: 'Phase 4 Discussion & Conclusion' }
  )
])

// ============================================================
// Phase 5: References & Figures (parallel)
// ============================================================
phase('Phase 5 References & Figures')
const [references, figures] = await parallel([
  () => agent(
    'Generate the reference list for a research paper.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Domain: ' + CONFIG.DOMAIN + '\n' +
    'Save to: ' + O + '/chapters/08-references.md\n\n' +
    'Requirements:\n' +
    '1. Total: ' + CONFIG.CHAPTERS.references.count + '\n' +
    '2. Chinese/English ratio: ' + CONFIG.CHAPTERS.references.ratio + '\n' +
    '3. Recent 5 years: >=60%\n' +
    '4. Format: GB/T 7714-2015 sequential numbering [1][2]...\n\n' +
    'Only use verified references from scholar_search.py output, DOI-verified BibTeX, or a user-provided bibliography.\n' +
    'Do not invent plausible author names, journal issues, years, DOIs, or titles. If verified sources are insufficient, write a gap report instead of fabricating references.\n' +
    'Cover all method domains used in the paper with traceable evidence.',
    { label: 'references-writer', phase: 'Phase 5 References & Figures' }
  ),
  () => agent(
    'Generate Python code for paper figures.\n\n' +
    'Paper title: ' + T_CN + '\n' +
    'Save to: ' + O + '/scripts/generate_figures.py\n\n' +
    'Generate ' + CONFIG.FIGURE_COUNT + ' figures:\n' +
    '- Figure 1: System/architecture diagram\n' +
    '- Figure 2-N: Performance comparison charts, ROC curves, confusion matrices, feature importance, etc.\n\n' +
    'Code requirements:\n' +
    '- Complete and runnable with matplotlib + seaborn\n' +
    '- Chinese font support (SimHei or system Chinese font)\n' +
    '- 300 DPI output\n' +
    '- Professional academic chart style\n' +
    '- Save each figure as PNG to ' + O + '/figures/\n' +
    '- Feature names and data values MUST match the paper content exactly',
    { label: 'figures-writer', phase: 'Phase 5 References & Figures' }
  )
])

// ============================================================
// Phase 6: Fix and compile
// ============================================================
phase('Phase 6 Fix & Compile')
await agent(
  'Complete final fixes for the paper at ' + O + ':\n\n' +
  '1. MERGE: Read all chapter files in ' + O + '/chapters/ (00 through 08). Merge in order to ' + O + '/full-paper.md with --- separators.\n\n' +
  '2. LATEX: Create/update ' + O + '/main.tex with:\n' +
  '   - All chapters merged into a single LaTeX document\n' +
  '   - Bilingual captions (Chinese + English) for ALL figures and tables\n' +
  '   - Proper labels (fig:X for figures, tab:X for tables)\n' +
  '   - No placeholder XXX in author info\n' +
  '   - Feature definitions matching 03-methodology.md exactly\n\n' +
  '3. COMPILE: Run xelatex (not pdflatex) for Chinese font support:\n' +
  '   cd ' + O + ' && xelatex -interaction=nonstopmode main.tex\n\n' +
  '4. QUALITY REPORT: Create/update ' + O + '/plan/quality-report.md with structure checklist, figure inventory, format compliance.\n\n' +
  '5. VALIDATE: Verify all figure references in chapters match actual figure files in ' + O + '/figures/.\n\n' +
  'Do all five tasks.',
  { label: 'final-fixer', phase: 'Phase 6 Fix & Compile' }
)

return 'Paper writing complete: ' + T_CN
