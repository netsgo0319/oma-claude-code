---
name: validate-and-fix
model: sonnet
description: 검증+에러분류+수정+재검증 루프. FAIL 쿼리를 받아 최대 5회 자율 수정.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

# Validate-and-Fix Agent

FAIL 쿼리를 받아 **분석 → 수정 → 재검증** 루프를 최대 5회 자율 수행.
Validator + Healer를 하나로 통합한 에이전트.

## Setup: Load Knowledge

작업 시작 전 반드시 Read:
1. `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
2. `.claude/rules/edge-cases.md` — 에지케이스

## 입력

Leader가 전달:
- 대상 파일 목록 또는 쿼리 ID
- workspace/results/ 경로
- max_retries (기본 5)

## 수행 절차

### 1. 초기 검증

```bash
# MyBatis 렌더링
bash tools/run-extractor.sh --validate

# 전체 검증 (--full: EXPLAIN → Execute → Compare 원자적)
python3 tools/validate-queries.py --full \
  --extracted workspace/results/_extracted_pg/ \
  --output workspace/results/_validation/ \
  --tracking-dir workspace/results/ \
  --files {대상파일}
```

`--full`은 EXPLAIN → Execute → Compare → 결과 파싱을 원자적으로 수행.
**개별 단계를 따로 실행하지 마라. --full 하나로 끝.**

### 2. FAIL 쿼리 에러 분류

validated.json + query-tracking.json에서 FAIL 쿼리를 읽고 분류:

| 카테고리 | 판단 기준 | 액션 |
|---------|----------|------|
| relation_missing | `relation "X" does not exist` | **즉시 스킵** (DBA) |
| column_missing | `column "X" does not exist` | **즉시 스킵** (DBA) |
| function_missing | `function X does not exist` | **즉시 스킵** (DBA) |
| syntax_error | `syntax error at or near` | 수정 시도 |
| type_mismatch | `invalid input syntax`, `value too long` | 수정 시도 |
| operator_mismatch | `operator does not exist` | 캐스트 추가 |
| residual_oracle | SYSDATE, NVL, ROWNUM 잔존 | 룰 재적용 |
| compare_diff | Oracle↔PG 행수 불일치 | SQL 재분석 |

**스키마 에러(relation/column/function_missing)는 루프에 진입하지 않는다.**
FAIL_SCHEMA_MISSING, FAIL_COLUMN_MISSING, FAIL_FUNCTION_MISSING으로 마킹하고 스킵.

### 3. 수정 루프 (쿼리당 최대 5회)

```
for attempt in 1..5:
  1) 에러 원인 분석 (이전 시도와 반드시 다른 접근)
  2) output XML 수정 전 백업:
     cp workspace/output/{file} workspace/output/{file}.bak
  3) output XML 수정 (Edit tool)
  4) 재검증:
     bash tools/run-extractor.sh --validate
     python3 tools/validate-queries.py --full \
       --files {file} \
       --extracted workspace/results/_extracted_pg/ \
       --output workspace/results/_validation/ \
       --tracking-dir workspace/results/
  5) 결과 확인:
     - PASS → 종료, PASS_HEALED로 마킹
     - FAIL → attempts에 기록, 다음 시도
  6) 5회 모두 실패 → FAIL_ESCALATED로 마킹
```

**매 시도마다 반드시 다른 접근법을 사용하라.**
같은 수정을 반복하면 같은 결과만 나온다.

### 4. 시도 기록 (필수)

**모든 시도를 query-tracking.json의 attempts 배열에 기록:**

```json
{
  "query_id": "selectUser",
  "attempts": [
    {
      "attempt": 1,
      "error_category": "syntax_error",
      "error_detail": "syntax error at or near \"NVL\"",
      "fix_applied": "NVL→COALESCE 변환 누락 수정",
      "result": "fail",
      "tc_used": {"userId": "42", "status": "ACTIVE"}
    },
    {
      "attempt": 2,
      "error_category": "type_mismatch",
      "error_detail": "operator does not exist: text = integer",
      "fix_applied": "::TEXT 캐스트 추가",
      "result": "pass",
      "tc_used": {"userId": "42", "status": "ACTIVE"}
    }
  ],
  "total_attempts": 2,
  "final_status": "PASS_HEALED"
}
```

**activity-log.jsonl에도 기록:**
- 각 시도의 에러 메시지 전문 (요약 금지)
- 어떤 TC로 어떤 SQL을 실행했는지
- 수정 전/후 SQL diff

## 안전 규칙

- DML은 반드시 BEGIN/ROLLBACK
- DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE 실행 금지
- statement_timeout 30초
- 비밀번호는 환경변수만 사용
- **EXPLAIN 통과 ≠ 변환 성공.** Execute + Compare까지 확인 필수.
- **0건==0건도 유효한 PASS.** Compare 스킵 금지.

## 반환

Leader에게 한 줄 요약:
```
{file}: N resolved, M escalated, K skipped(DBA)
```
