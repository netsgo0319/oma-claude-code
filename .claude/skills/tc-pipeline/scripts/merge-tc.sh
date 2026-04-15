#!/bin/bash
# tc-pipeline: per-file TC → merged-tc.json 병합
set -e
echo "=== TC Merge ==="

python3 -c "
import json, glob, re
from pathlib import Path

merged = {}
for f in sorted(glob.glob('pipeline/step-2-tc-generate/output/per-file/*/v1/test-cases.json')):
    with open(f) as fh:
        data = json.load(fh)
    for qid, cases in data.items():
        if isinstance(cases, list) and cases:
            merged[qid] = [tc.get('params', tc) for tc in cases if isinstance(tc, dict)]

# foreach collection 보정: XML에서 <foreach collection='X'> 파라미터를 찾아 리스트 보장
foreach_by_qid = {}
for xf in sorted(Path('pipeline/shared/input').glob('**/*.xml')):
    try:
        content = xf.read_text(encoding='utf-8', errors='ignore')
    except: continue
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(content)
    except: continue
    for tag in ('select','insert','update','delete'):
        for elem in root.iter(tag):
            qid = elem.get('id','')
            if not qid: continue
            xml_str = ET.tostring(elem, encoding='unicode')
            collections = re.findall(r'collection\s*=\s*[\"\\'](\w+)[\"\\']', xml_str)
            if collections:
                foreach_by_qid[qid] = list(set(collections))

patched = 0
for qid, collections in foreach_by_qid.items():
    if qid not in merged: continue
    for tc_params in merged[qid]:
        if not isinstance(tc_params, dict): continue
        for col in collections:
            val = tc_params.get(col)
            if val is None or val == '' or val == 'NULL':
                tc_params[col] = ['1', '2']
                patched += 1

with open('pipeline/step-2-tc-generate/output/merged-tc.json', 'w') as fh:
    json.dump(merged, fh, ensure_ascii=False, indent=2)
print(f'Merged: {len(merged)} queries ({patched} foreach params patched)')
"

echo "=== TC Merge 완료 ==="
