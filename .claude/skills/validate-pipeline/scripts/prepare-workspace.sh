#!/bin/bash
# validate-pipeline: workspace 준비 (pipeline → workspace 복사 + merged-tc 병합)
# validate-and-fix 에이전트가 검증 전에 실행

set -e

echo "=== Workspace 준비 ==="

# 1. output XML 복사 (step-1 + step-3 fixes)
mkdir -p workspace/output
cp pipeline/step-1-convert/output/xml/*.xml workspace/output/ 2>/dev/null || true
cp pipeline/step-3-validate-fix/output/xml-fixes/*.xml workspace/output/ 2>/dev/null || true
echo "  output XML: $(ls workspace/output/*.xml 2>/dev/null | wc -l) files"

# 2. merged-tc.json 병합
mkdir -p workspace/results/_test-cases
python3 -c "
import json, glob
merged = {}
for f in sorted(glob.glob('pipeline/step-2-tc-generate/output/per-file/*/v1/test-cases.json')):
    data = json.load(open(f))
    for qid, cases in data.items():
        if isinstance(cases, list) and cases:
            merged[qid] = [tc.get('params', tc) for tc in cases if isinstance(tc, dict)]
json.dump(merged, open('workspace/results/_test-cases/merged-tc.json', 'w'), ensure_ascii=False, indent=2)
print(f'  merged-tc: {len(merged)} queries')
"

echo "=== 준비 완료 ==="
