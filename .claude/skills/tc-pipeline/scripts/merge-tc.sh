#!/bin/bash
# tc-pipeline: per-file TC → merged-tc.json 병합
set -e
echo "=== TC Merge ==="

python3 -c "
import json, glob
merged = {}
for f in sorted(glob.glob('pipeline/step-2-tc-generate/output/per-file/*/v1/test-cases.json')):
    with open(f) as fh:
        data = json.load(fh)
    for qid, cases in data.items():
        if isinstance(cases, list) and cases:
            merged[qid] = [tc.get('params', tc) for tc in cases if isinstance(tc, dict)]
with open('pipeline/step-2-tc-generate/output/merged-tc.json', 'w') as fh:
    json.dump(merged, fh, ensure_ascii=False, indent=2)
print(f'Merged: {len(merged)} queries')
"

echo "=== TC Merge 완료 ==="
