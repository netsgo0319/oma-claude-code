---
name: convert-pipeline
description: Step 1 변환 파이프라인. converter 에이전트가 Oracle XML을 PostgreSQL로 변환할 때 사용합니다. batch-process.sh로 전체 룰 변환 후 unconverted만 LLM 변환. 파일을 하나씩 Edit하지 않고 반드시 이 파이프라인을 따릅니다.
allowed-tools:
  - Bash
  - Read
  - Edit
disable-model-invocation: true
---

# Convert Pipeline

Step 1 변환의 전체 파이프라인.

## 실행 순서

### 1. 파싱 + 룰 변환 (최초 1회)
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/run-batch-process.sh
```
`--all`로 parse + analyze + convert를 한번에. 이미 output이 있으면 스킵.

### 2. LLM 변환 (unconverted만)
`conversion-report.json`의 `unconverted` 목록 확인.
unconverted가 있으면 `llm-convert` 스킬 참조하여 직접 변환.
**output XML을 Edit하고 query-tracking.json 갱신 필수.**

### 3. query-tracking.json 갱신
LLM 변환한 쿼리에 대해:
- `pg_sql`: 변환된 SQL 전문
- `conversion_method`: "llm"
- `status`: "converted"
- `conversion_history[]`: pattern, approach, confidence

### 4. Handoff 생성
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/generate-handoff.sh
```

## 도구

| 도구 | 용도 |
|------|------|
| `tools/batch-process.sh` | 전체 파싱+룰변환 (v1 최초만) |
| `tools/oracle-to-pg-converter.py` | 개별 파일 룰변환 |
| `tools/xml-splitter.py` | 1000줄+ XML 분할 |
| `tools/generate-handoff.py --step 1` | handoff 생성 |
