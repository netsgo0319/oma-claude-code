---
name: tc-pipeline
description: Step 2 TC 생성 파이프라인 — generate-test-cases → merge → handoff. tc-generator 에이전트가 사용.
allowed-tools:
  - Bash
  - Read
---

# TC Pipeline

Step 2 TC 생성의 전체 파이프라인.

## 실행 순서

### 1. TC 생성
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/run-tc-generate.sh
```
고객 바인드(custom-binds.json) > 샘플 데이터 > Java VO > V$SQL_BIND_CAPTURE > 추론.

### 2. TC 병합
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/merge-tc.sh
```
per-file test-cases.json → merged-tc.json (MyBatis extractor용).

### 3. 결과 검증
```bash
python3 -c "
import json
tc = json.load(open('pipeline/step-2-tc-generate/output/merged-tc.json'))
print(f'TC: {len(tc)} queries, {sum(len(v) for v in tc.values())} total cases')
"
```

### 4. Handoff 생성
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/generate-handoff.sh
```
