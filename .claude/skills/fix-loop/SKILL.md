---
name: fix-loop
description: FAIL 쿼리 수정 루프. validate-and-fix 에이전트가 검증 실패(EXPLAIN 에러, Compare 불일치) 쿼리를 수정할 때 사용합니다. 에러 분석 → XML Edit → 재검증 최대 3회. DBA 3종(relation/column/function missing)은 스킵합니다.
allowed-tools:
  - Bash
  - Read
  - Edit
disable-model-invocation: true
---

# Fix Loop

FAIL 쿼리를 받아 **분석 → 수정 → 재검증** 루프를 최대 3회 자율 수행.

## FAIL 정의

**아래 중 하나라도 해당하면 FAIL:**
- EXPLAIN 실패 (syntax error, missing object)
- Execute 실패 (런타임 에러)
- Compare 불일치 (Oracle ≠ PG 행수)

## 에러 분류

| 카테고리 | 판단 기준 | 액션 |
|---------|----------|------|
| relation_missing | `relation "X" does not exist` | **즉시 스킵** (DBA) |
| column_missing | `column "X" does not exist` | **즉시 스킵** (DBA) |
| function_missing | `function X does not exist` | **즉시 스킵** (DBA) |
| syntax_error | `syntax error at or near` | 수정 시도 |
| type_mismatch | `invalid input syntax`, `value too long` | 수정 시도 |
| operator_mismatch | `operator does not exist` | 캐스트 추가 |
| residual_oracle | SYSDATE, NVL, ROWNUM 잔존 | 룰 재적용 |
| compare_diff | Oracle↔PG 행수 불일치 | SQL 수정 + 재검증 |

**DBA 3종 외 모든 FAIL은 반드시 수정 시도.**

## 루프 절차 (쿼리당 최대 3회)

```
for attempt in 1..3:
  1) 에러 분석 (conversion_history 참조 + 이전과 다른 접근)
  2) 수정 전 백업:
     cp pipeline/step-1-convert/output/xml/{file}.xml \
        pipeline/step-3-validate-fix/output/xml-fixes/{file}.v{attempt}.bak
  3) output XML 수정 (Edit tool)
  4) 재검증: validate-pipeline 스킬의 1~2단계 재실행
  5) PASS → 종료 / FAIL → 시도 기록, 다음
  6) 3회 실패 → FAIL_ESCALATED
```

## 시도 기록

매 시도마다 반드시 기록:
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/record-attempt.sh \
  "pipeline/step-1-convert/output/results/{file}/v1" \
  "{query_id}" \
  "SYNTAX_ERROR" \
  "syntax error near NVL" \
  "NVL→COALESCE 변환 누락 수정" \
  "fail"
```

또는 Python으로:
```python
from tracking_utils import TrackingManager
tm = TrackingManager('pipeline/step-1-convert/output/results/{file}/v1')
tm.add_attempt('{query_id}', error_category='...', error_detail='...', fix_applied='...', result='pass')
```

## 핵심 원칙

- **매 시도마다 다른 접근.** 같은 수정 반복 금지.
- **conversion_history 먼저 읽어라.** converter가 뭘 바꿨는지 알아야 진단이 빠르다.
- **분석만 하고 멈추지 마라.** output XML을 Edit하고 재검증하라.
