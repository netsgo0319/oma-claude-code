#!/usr/bin/env bash
# Batch parallel processor for Phase 1 (split+parse+convert)
#
# Usage:
#   bash tools/batch-process.sh --parse                    # Phase 1: split + parse all
#   bash tools/batch-process.sh --convert                  # Phase 1 (Convert): convert all
#   bash tools/batch-process.sh --all                      # Phase 1 + 2
#   bash tools/batch-process.sh --all --parallel 16        # Custom parallelism

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INPUT_DIR="${INPUT_DIR:-$PROJECT_DIR/workspace/input}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/workspace/output}"
RESULTS_DIR="${RESULTS_DIR:-$PROJECT_DIR/workspace/results}"

DO_PARSE=false
DO_CONVERT=false
DO_ANALYZE=false
PARALLEL=8

while [[ $# -gt 0 ]]; do
    case $1 in
        --parse) DO_PARSE=true; shift ;;
        --convert) DO_CONVERT=true; shift ;;
        --analyze) DO_ANALYZE=true; shift ;;
        --all) DO_PARSE=true; DO_CONVERT=true; DO_ANALYZE=true; shift ;;
        --parallel) PARALLEL="$2"; shift 2 ;;
        *) shift ;;
    esac
done

if [ "$DO_PARSE" = false ] && [ "$DO_CONVERT" = false ] && [ "$DO_ANALYZE" = false ]; then
    echo "Usage: bash tools/batch-process.sh [--parse] [--analyze] [--convert] [--all] [--parallel N]"
    exit 1
fi

mkdir -p "$OUTPUT_DIR" "$RESULTS_DIR"

XML_COUNT=$(find "$INPUT_DIR" -name "*.xml" -type f 2>/dev/null | wc -l | tr -d ' ')
echo "Input files: $XML_COUNT"
echo "Parallelism: $PARALLEL"
echo ""

# Worker function for parse (called per file)
_parse_one() {
    local f="$1"
    local base
    base=$(basename "$f")
    local resdir="$RESULTS_DIR/${base}/v1"
    local chunks="$resdir/chunks"
    local parsed="$resdir/parsed.json"

    if [ -f "$parsed" ]; then
        return 0
    fi

    mkdir -p "$chunks"
    python3 "$SCRIPT_DIR/xml-splitter.py" "$f" "$chunks" >/dev/null 2>&1
    python3 "$SCRIPT_DIR/parse-xml.py" "$chunks/" "$parsed" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo -n "."
    else
        echo -n "X"
    fi
}
export -f _parse_one
export SCRIPT_DIR RESULTS_DIR

# Worker function for analyze (called per parsed.json)
_analyze_one() {
    local parsed="$1"
    local resdir
    resdir=$(dirname "$parsed")

    if [ -f "$resdir/complexity-scores.json" ]; then
        return 0
    fi

    python3 "$SCRIPT_DIR/query-analyzer.py" "$parsed" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo -n "."
    else
        echo -n "X"
    fi
}
export -f _analyze_one

# Worker function for convert (called per file)
_convert_one() {
    local f="$1"
    local base
    base=$(basename "$f")
    local outfile="$OUTPUT_DIR/${base}"
    local report="$RESULTS_DIR/${base}/v1/conversion-report.json"
    local tracking="$RESULTS_DIR/${base}/v1"

    if [ -f "$outfile" ]; then
        return 0
    fi

    mkdir -p "$RESULTS_DIR/${base}/v1"
    python3 "$SCRIPT_DIR/oracle-to-pg-converter.py" "$f" "$outfile" \
        --report "$report" --tracking-dir "$tracking" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo -n "."
    else
        echo -n "X"
    fi
}
export -f _convert_one
export OUTPUT_DIR

# ========== Phase 1: Split + Parse ==========
if [ "$DO_PARSE" = true ]; then
    echo "=== Phase 1: Split + Parse (parallel $PARALLEL) ==="
    START_TIME=$(date +%s)

    # Count already done
    DONE_BEFORE=$(find "$RESULTS_DIR" -maxdepth 3 -name parsed.json 2>/dev/null | wc -l | tr -d ' ')
    REMAINING=$((XML_COUNT - DONE_BEFORE))
    echo "  Already parsed: $DONE_BEFORE, Remaining: $REMAINING"

    if [ "$REMAINING" -gt 0 ]; then
        # Use find + xargs with null delimiter (handles any filename)
        find "$INPUT_DIR" -name "*.xml" -type f -print0 | \
            xargs -0 -P "$PARALLEL" -I{} bash -c '_parse_one "$@"' _ {}
        echo ""
    fi

    PARSED_COUNT=$(find "$RESULTS_DIR" -maxdepth 3 -name parsed.json 2>/dev/null | wc -l | tr -d ' ')
    END_TIME=$(date +%s)
    ELAPSED=$((END_TIME - START_TIME))

    echo "  Parsed: $PARSED_COUNT / $XML_COUNT ($ELAPSED sec)"

    # Count total queries
    TOTAL_QUERIES=$(python3 -c "
import json, glob
total = 0
for f in glob.glob('$RESULTS_DIR/*/v1/parsed.json'):
    try:
        d = json.load(open(f))
        total += len(d.get('queries', []))
    except: pass
print(total)
" 2>/dev/null || echo "?")
    echo "  Total queries: $TOTAL_QUERIES"
    echo ""
fi

# ========== Phase 1.5: Analyze ==========
if [ "$DO_ANALYZE" = true ]; then
    echo "=== Phase 1.5: Dependency Analysis + Complexity (parallel $PARALLEL) ==="
    START_TIME=$(date +%s)

    DONE_BEFORE=$(find "$RESULTS_DIR" -maxdepth 3 -name complexity-scores.json 2>/dev/null | wc -l | tr -d ' ')
    echo "  Already analyzed: $DONE_BEFORE"

    # Find all parsed.json that don't have complexity-scores.json yet
    find "$RESULTS_DIR" -maxdepth 3 -name parsed.json -print0 | \
        xargs -0 -P "$PARALLEL" -I{} bash -c '_analyze_one "$@"' _ {}
    echo ""

    ANALYZED_COUNT=$(find "$RESULTS_DIR" -maxdepth 3 -name complexity-scores.json 2>/dev/null | wc -l | tr -d ' ')
    END_TIME=$(date +%s)
    ELAPSED=$((END_TIME - START_TIME))

    echo "  Analyzed: $ANALYZED_COUNT / $XML_COUNT ($ELAPSED sec)"

    # Complexity distribution
    echo ""
    echo "  === Complexity Distribution ==="
    python3 -c "
import json, glob, collections
L = collections.Counter()
total = 0
for f in glob.glob('$RESULTS_DIR/*/v1/complexity-scores.json'):
    try:
        d = json.load(open(f))
        for q in d.get('queries', d.get('scores', [])):
            if isinstance(q, dict):
                level = q.get('level', 'L0')
                L[level] += 1
                total += 1
            elif isinstance(d, dict) and not isinstance(d.get('queries'), list):
                # Old format: {qid: {level: 'L1'}}
                for qid, info in d.items():
                    if isinstance(info, dict) and 'level' in info:
                        L[info['level']] += 1
                        total += 1
                break
    except: pass
for level in ['L0','L1','L2','L3','L4']:
    cnt = L.get(level, 0)
    pct = cnt*100//total if total>0 else 0
    print(f'  {level}: {cnt} ({pct}%)')
print(f'  Total: {total}')
rule_ok = L.get('L0',0)+L.get('L1',0)+L.get('L2',0)
llm_need = L.get('L3',0)+L.get('L4',0)
print(f'  Rule convertible (L0~L2): {rule_ok}')
print(f'  LLM needed (L3~L4): {llm_need}')
" 2>/dev/null || true
    echo ""
fi

# ========== Phase 1 (Convert): Rule-based Convert ==========
if [ "$DO_CONVERT" = true ]; then
    echo "=== Phase 1 (Convert): Rule-based Convert (parallel $PARALLEL) ==="
    START_TIME=$(date +%s)

    DONE_BEFORE=$(find "$OUTPUT_DIR" -name "*.xml" -type f 2>/dev/null | wc -l | tr -d ' ')
    REMAINING=$((XML_COUNT - DONE_BEFORE))
    echo "  Already converted: $DONE_BEFORE, Remaining: $REMAINING"

    if [ "$REMAINING" -gt 0 ]; then
        find "$INPUT_DIR" -name "*.xml" -type f -print0 | \
            xargs -0 -P "$PARALLEL" -I{} bash -c '_convert_one "$@"' _ {}
        echo ""
    fi

    CONVERTED_COUNT=$(find "$OUTPUT_DIR" -name "*.xml" -type f 2>/dev/null | wc -l | tr -d ' ')
    END_TIME=$(date +%s)
    ELAPSED=$((END_TIME - START_TIME))

    echo "  Converted: $CONVERTED_COUNT / $XML_COUNT ($ELAPSED sec)"

    # Summary
    echo ""
    echo "  === Conversion Summary ==="
    python3 -c "
import json, glob, collections
rules = collections.Counter()
unconverted = collections.Counter()
residual = 0
for f in glob.glob('$RESULTS_DIR/*/v1/conversion-report.json'):
    try:
        d = json.load(open(f))
        for r, c in d.get('rules_applied', {}).items():
            rules[r] += c
        for u in d.get('unconverted', []):
            unconverted[u.get('pattern', 'unknown')] += 1
        residual += len(d.get('residual_oracle_patterns', []))
    except: pass
print(f'  Rules applied: {sum(rules.values())} ({len(rules)} types)')
for r, c in rules.most_common(5):
    print(f'    {r}: {c}')
if unconverted:
    print(f'  Unconverted: {sum(unconverted.values())} ({len(unconverted)} types)')
    for u, c in unconverted.most_common(5):
        print(f'    {u}: {c}')
if residual:
    print(f'  Residual patterns: {residual}')
" 2>/dev/null || true
    echo ""
fi

echo "=== Done ==="
