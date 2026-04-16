#!/bin/bash
# validate-pipeline: shared-fixes를 output XML에 일괄 적용 (Step 3b)
# Scout 배치에서 발견한 수정 패턴을 나머지 파일에 적용하여 fix-loop 절감
set -e

REGISTRY="pipeline/step-3-validate-fix/shared-fixes.jsonl"
XML_DIR="pipeline/step-1-convert/output/xml"

if [ ! -f "$REGISTRY" ]; then
    echo "No shared-fixes.jsonl found — skip pre-apply"
    exit 0
fi

PATTERN_COUNT=$(wc -l < "$REGISTRY")
echo "=== Pre-apply shared fixes ==="
echo "  Registry: $REGISTRY ($PATTERN_COUNT patterns)"
echo "  Target:   $XML_DIR"

python3 tools/shared_fix_registry.py pre-apply \
    --xml-dir "$XML_DIR" \
    --registry "$REGISTRY"

echo "=== Pre-apply 완료 ==="
