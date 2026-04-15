---
name: tc-pipeline
description: Step 2 TC 생성 파이프라인. tc-generator 에이전트가 테스트 케이스를 생성할 때 사용합니다. generate-test-cases.py 실행 → merged-tc.json 병합 → handoff 생성.
allowed-tools:
  - Bash
  - Read
disable-model-invocation: true
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

## 체크리스트

```
Step 2 TC 생성:
- [ ] 1. Step 1 handoff.json 확인 (status=success)
- [ ] 2. 샘플 데이터 존재 확인
- [ ] 3. generate-test-cases.py 실행
- [ ] 4. merged-tc.json 생성/검증 (쿼리 수 확인)
- [ ] 5. handoff.json 생성
```

## 참조 문서

- [TC 스키마](../../schemas/test-cases.schema.json)
