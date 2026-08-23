#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash scripts/style_check.sh <markdown_file>
#
# All patterns and thresholds are read dynamically from deai_constants.py
# (the single authoritative source). Do NOT hardcode patterns here.

FILE="${1:-}"
if [[ -z "$FILE" ]]; then
  echo "Usage: bash scripts/style_check.sh <markdown_file>"
  exit 1
fi
if [[ ! -f "$FILE" ]]; then
  echo "File not found: $FILE"
  exit 1
fi

# Resolve script directory for importing deai_constants
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FAIL=0

fail() {
  echo "FAIL: $1"
  FAIL=$((FAIL + 1))
}

pass() {
  echo "PASS: $1"
}

warn() {
  echo "WARN: $1"
}

count_regex() {
  local pattern="$1"
  grep -E -c "$pattern" "$FILE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Load all patterns from deai_constants.py as JSON
# ---------------------------------------------------------------------------
RULES_JSON=$(python3 -c "
import sys, json, re, os
sys.path.insert(0, os.environ.get('DEAI_SCRIPT_DIR', '$SCRIPT_DIR'))
from deai_constants import (
    ABSOLUTE_PATTERNS, ABSOLUTE_PATTERNS_REGEX,
    LIMITED_PATTERNS, EN_ABSOLUTE_PATTERNS,
    EN_BANNED_TRANSITIONS, SUBJECTIVE_FIRST_PERSON,
    PARAGRAPH_MAX_CHARS, PARAGRAPH_WARN_CHARS,
)

# Build grep-compatible OR-pattern from plain text list
def to_grep_pattern(items):
    # Escape regex special chars for grep -E (items are plain text)
    escaped = [re.escape(p) for p in items]
    return '|'.join(escaped)

# Build grep-compatible OR-pattern from regex list (items are already regex)
def to_grep_regex(items):
    return '|'.join(items)

json.dump({
    'absolute_text': to_grep_pattern(ABSOLUTE_PATTERNS),
    'absolute_regex': to_grep_regex(ABSOLUTE_PATTERNS_REGEX),
    'limited': [{'pattern': p, 'limit': l} for p, l in LIMITED_PATTERNS],
    'en_absolute': to_grep_pattern(EN_ABSOLUTE_PATTERNS),
    'en_transitions': to_grep_pattern(EN_BANNED_TRANSITIONS),
    'first_person': to_grep_pattern(SUBJECTIVE_FIRST_PERSON),
    'para_max': PARAGRAPH_MAX_CHARS,
    'para_warn': PARAGRAPH_WARN_CHARS,
}, sys.stdout)
")

echo "Checking: $FILE"

# ---------------------------------------------------------------------------
echo
echo "[1] Absolute banned phrases (Chinese plain-text)"
ABS_TEXT=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['absolute_text'])")
ABS_COUNT=$(count_regex "$ABS_TEXT")
if [[ "$ABS_COUNT" -eq 0 ]]; then
  pass "absolute banned phrases (text): 0"
else
  fail "absolute banned phrases (text): $ABS_COUNT"
  grep -nE "$ABS_TEXT" "$FILE" || true
fi

# ---------------------------------------------------------------------------
echo
echo "[1b] Absolute banned phrases (Chinese regex)"
ABS_REGEX=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['absolute_regex'])")
ABS_REGEX_COUNT=$(count_regex "$ABS_REGEX")
if [[ "$ABS_REGEX_COUNT" -eq 0 ]]; then
  pass "absolute banned phrases (regex): 0"
else
  fail "absolute banned phrases (regex): $ABS_REGEX_COUNT"
  grep -nE "$ABS_REGEX" "$FILE" || true
fi

# ---------------------------------------------------------------------------
echo
echo "[2] Limited phrases"
# Read limited rules as JSON array, iterate in bash
LIMITED_COUNT=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['limited']))")
for ((i=0; i<LIMITED_COUNT; i++)); do
  pattern=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['limited'][$i]['pattern'])")
  limit=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['limited'][$i]['limit'])")
  count=$(count_regex "$pattern")
  if [[ "$count" -le "$limit" ]]; then
    pass "$pattern: $count <= $limit"
  else
    fail "$pattern: $count > $limit"
    grep -nE "$pattern" "$FILE" || true
  fi
done

# ---------------------------------------------------------------------------
echo
echo "[3] English absolute banned patterns (AI-slop)"
EN_ABS=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['en_absolute'])")
EN_ABS_COUNT=$(grep -E -i -c "$EN_ABS" "$FILE" 2>/dev/null || true)
if [[ "$EN_ABS_COUNT" -eq 0 ]]; then
  pass "English AI-slop patterns: 0"
else
  fail "English AI-slop patterns: $EN_ABS_COUNT"
  grep -nEi "$EN_ABS" "$FILE" || true
fi

# ---------------------------------------------------------------------------
echo
echo "[3b] English banned transition/emphasis phrases"
EN_TRANS=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['en_transitions'])")
EN_TRANS_COUNT=$(grep -E -i -c "$EN_TRANS" "$FILE" 2>/dev/null || true)
if [[ "$EN_TRANS_COUNT" -eq 0 ]]; then
  pass "English banned transitions: 0"
else
  fail "English banned transitions: $EN_TRANS_COUNT"
  grep -nEi "$EN_TRANS" "$FILE" || true
fi

# ---------------------------------------------------------------------------
echo
echo "[4] Subjective first-person phrases"
FP_PATTERN=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['first_person'])")
FP_COUNT=$(grep -E -i -c "$FP_PATTERN" "$FILE" 2>/dev/null || true)
if [[ "$FP_COUNT" -eq 0 ]]; then
  pass "subjective first-person phrases: 0"
else
  fail "subjective first-person phrases: $FP_COUNT"
  grep -nEi "$FP_PATTERN" "$FILE" || true
fi

# ---------------------------------------------------------------------------
echo
echo "[5] Paragraph length"
PARA_MAX=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['para_max'])")
PARA_WARN=$(echo "$RULES_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['para_warn'])")
PARA_RESULT=$(python3 - "$FILE" "$PARA_WARN" "$PARA_MAX" <<'PY' || true
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
para_warn = int(sys.argv[2])
para_max = int(sys.argv[3])
text = re.sub(r"```.*?```", "", text, flags=re.S)
paragraph = []
start = 1
warns = []
fails = []

def flush():
    global paragraph, start
    if not paragraph:
        return
    para = "\n".join(paragraph).strip()
    compact = re.sub(r"\s+", "", para)
    if (
        compact
        and not para.startswith("#")
        and not para.startswith("|")
        and not para.startswith("![")
        and not para.startswith("- ")
        and not para.startswith("* ")
        and not re.match(r"^\d+\.", para)
    ):
        if len(compact) > para_max:
            fails.append((start, len(compact)))
        elif len(compact) > para_warn:
            warns.append((start, len(compact)))
    paragraph = []

for lineno, line in enumerate(text.splitlines(), start=1):
    if not line.strip():
        flush()
        start = lineno + 1
        continue
    if not paragraph:
        start = lineno
    paragraph.append(line)
flush()

import json
json.dump({"warns": warns, "fails": fails}, sys.stdout)
sys.exit(1 if fails else 0)
PY
)
PARA_FAILS=$(echo "$PARA_RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for line, count in d['fails']:
    print(f'{line}:{count} chars')
" 2>/dev/null || true)
PARA_WARNS=$(echo "$PARA_RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for line, count in d['warns']:
    print(f'{line}:{count} chars')
" 2>/dev/null || true)
if [[ -z "$PARA_FAILS" ]]; then
  if [[ -n "$PARA_WARNS" ]]; then
    warn "paragraphs over $PARA_WARN chars (auto-fixable)"
    printf "%s\n" "$PARA_WARNS"
  fi
  pass "paragraphs <= $PARA_MAX chars (hard limit)"
else
  fail "paragraphs over $PARA_MAX chars"
  printf "%s\n" "$PARA_FAILS"
fi

# ---------------------------------------------------------------------------
echo
echo "[6] Bold markers in prose"
BOLD_HITS=$(grep -nE '\*\*|__' "$FILE" 2>/dev/null | grep -vE '^\s*[0-9]+:.*\|' || true)
if [[ -z "$BOLD_HITS" ]]; then
  pass "no prose bold markers"
else
  fail "prose bold markers found"
  printf "%s\n" "$BOLD_HITS"
fi

# ---------------------------------------------------------------------------
echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "Style gate passed."
  exit 0
fi

echo "Style gate failed: $FAIL issue group(s)."
exit 1
