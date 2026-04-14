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
Validator + Fixer를 하나로 통합한 에이전트.

## Setup: Load Knowledge

작업 시작 전 반드시 Read:
1. `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
2. `.claude/rules/edge-cases.md` — 에지케이스

## 입력

메인 에이전트가 전달:
- 대상 파일 목록 또는 쿼리 ID
- workspace/results/ 경로
- max_retries (기본 5)

## 수행 절차

### 1. 초기 검증

**반드시 `--files`로 할당된 파일만 검증하라. 전체 파일을 한번에 돌리지 마라.**
리더가 파일을 나눠서 여러 에이전트에 분배한다. 네가 받은 파일만 처리.

**금지 행동:**
- "결과가 분산되어 있어 전체 통합 검증하겠다" → **금지.** 통합은 reporter가 한다.
- "전체 EXPLAIN 먼저 돌리고 그다음 Execute" → **금지.** --full 하나로 끝.
- 할당되지 않은 파일을 검증하는 것 → **금지.** 네 배치만 처리하라.

```bash
# MyBatis 렌더링 (할당 파일만)
bash tools/run-extractor.sh --validate

# 검증 (--full, 할당 파일만, output 디렉토리 분리)
python3 tools/validate-queries.py --full \
  --files {할당된 파일1},{할당된 파일2},{할당된 파일3} \
  --extracted workspace/results/_extracted_pg/ \
  --output workspace/results/{배치별 output 디렉토리}/ \
  --tracking-dir workspace/results/
```

`--full`은 EXPLAIN → Execute → Compare → 결과 파싱을 **원자적으로** 수행.
**개별 단계(EXPLAIN만 → Execute만)를 따로 실행하지 마라. --full 하나로 끝.**
**전체 파일을 한번에 넣지 마라. 할당된 파일만 --files에 넣어라.**

**SQL 로딩 우선순위:** MyBatis 렌더링 SQL → 빈 SQL이면 static XML에서 자동 보충.
동적 SQL(`<if test="param != null">`)이 전체를 감싸서 MyBatis가 빈 SQL을 반환하면,
output XML에서 `#{param}` 패턴의 원본 SQL을 추출하여 더미 바인딩으로 검증한다.

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

**DBA 3종 외의 모든 FAIL은 반드시 수정을 시도하라.**
- 분석만 하고 "어떻게 할까요?" 질문하지 마라. 직접 수정하라.
- 에러를 보고만 하고 멈추지 마라. output XML을 Edit하고 재검증하라.
- 커버리지가 낮다고 조기 중단하지 마라. 할당된 파일의 모든 FAIL을 처리하라.

### 3. 수정 루프 (쿼리당 최대 5회) — 반드시 실행

**수정 전 반드시 query-tracking.json의 `conversion_history`를 읽어라.**
converter가 어떤 패턴을 어떻게 변환했는지(CONNECT BY→WITH RECURSIVE 등) 알아야
에러 원인을 빠르게 진단할 수 있다. conversion_history가 없으면 룰 변환으로 간주.

```
for attempt in 1..5:
  1) 에러 원인 분석 (conversion_history 참조 + 이전 시도와 반드시 다른 접근)
  2) output XML 수정 전 백업:
     cp workspace/output/{file} workspace/output/{file}.v{attempt}.bak
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

### 3b. NOT_TESTED_NO_RENDER 쿼리 재시도

검증 후 NOT_TESTED_NO_RENDER 쿼리가 있으면 — MyBatis가 빈 SQL을 반환한 것.
원인: `<if test="param != null">`이 전체를 감싸고 null 파라미터로 렌더링.

**재시도 절차:**
1. 해당 쿼리의 TC에서 실값이 있는 TC를 확인 (custom, sample_row, default)
2. 실값 TC가 없으면: query-tracking.json에서 파라미터 이름 확인 → 추론값 생성
3. merged-tc.json을 해당 쿼리의 실값으로 갱신:
   ```bash
   python3 -c "
   import json
   tc = json.load(open('workspace/results/_test-cases/merged-tc.json'))
   tc['{query_id}'] = [{'param1': 'value1', 'param2': 'value2'}]
   json.dump(tc, open('workspace/results/_test-cases/merged-tc.json', 'w'), ensure_ascii=False, indent=2)
   "
   ```
4. MyBatis 재렌더링 + 재검증:
   ```bash
   bash tools/run-extractor.sh --skip-build --validate
   python3 tools/validate-queries.py --full \
     --files {file} \
     --extracted workspace/results/_extracted_pg/ \
     --output workspace/results/{배치별 output}/ \
     --tracking-dir workspace/results/
   ```
5. 여전히 빈 SQL → static fallback이 자동 적용됨 (validate-queries.py 내부)

**이 재시도는 수정 루프 5회와 별개.** 렌더링 문제는 SQL 수정이 아니라 TC 보강으로 해결.

### 4. 시도 기록 (필수)

**모든 시도를 query-tracking.json의 attempts 배열에 기록:**

```json
{
  "query_id": "selectUser",
  "attempts": [
    {
      "attempt": 1,
      "ts": 1713100860,
      "error_category": "syntax_error",
      "error_detail": "syntax error at or near \"NVL\"",
      "fix_applied": "NVL→COALESCE 변환 누락 수정",
      "result": "fail",
      "tc_used": {"userId": "42", "status": "ACTIVE"}
    },
    {
      "attempt": 2,
      "ts": 1713100920,
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

메인 에이전트에게 한 줄 요약 (수정 시도 건수 필수 포함):
```
{file}: N resolved, M escalated, K skipped(DBA), L fix_attempted
```

**fix_attempted가 0이면 리더가 재위임한다.** 분석만 하고 수정을 안 했다는 뜻이므로.
