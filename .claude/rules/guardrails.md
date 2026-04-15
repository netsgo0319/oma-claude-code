---
inclusion: always
---

# OMA 가드레일 (모든 에이전트 필수 적용)

## 절대 금지 행동

### SQL 안전
- **DML은 PG: BEGIN/ROLLBACK + 5s timeout, Oracle: SELECT COUNT(*) WHERE**
- DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE 실행 금지
- statement_timeout 30초 설정 필수

### 파일 안전
- **workspace/ 아래에 임시 .py/.sh 파일을 만들지 마라.** 기존 도구만 사용
- output XML 수정 전 반드시 버저닝: `cp file file.v{N}.bak`

### MyBatis 파라미터
- **`#{param}`은 MyBatis 바인드 파라미터.** Oracle 구문이 아님. 변환 금지
- `#{sysdate}` → 그대로 유지. bare `SYSDATE`만 CURRENT_TIMESTAMP로 변환

### 검증 원칙
- **EXPLAIN 통과 ≠ 변환 성공.** Execute + Compare까지 필수
- **0건==0건도 유효한 PASS.** Compare를 스킵하지 마라
- **Compare mismatch(Oracle≠PG)도 FAIL이다.** EXPLAIN+Execute PASS여도 Compare 불일치면 수정 루프 대상
- 스키마 에러(relation/column/function_missing)만 수정 루프 면제. 나머지 전부 수정 시도

### PG 환경
- **search_path 필수 확인.** 스키마가 public이 아니면 `SET search_path TO {schema}, public;`
- pgcrypto extension 확인 (PKG_CRYPTO 변환에 필수)

## 보고서 생성 게이트

**reporter 체크리스트를 통과해야만 보고서를 생성할 수 있다:**
- 2c: FAIL인데 수정 루프 0회인 쿼리 → BLOCK
- 2d: DBA 3종 외 Compare 미실행 쿼리 → BLOCK
- BLOCK이면 보고서 생성 금지. validate-and-fix 재위임 후 다시 reporter 호출.

## 산출물 필수 규칙

**모든 최종 단계(수정, 재검증, 보고서)는 아래 3개 산출물을 반드시 갱신해야 한다:**
1. `workspace/reports/query-matrix.csv` — flat CSV
2. `workspace/reports/query-matrix.json` — 상세 JSON (sql_before/after, attempts, test_cases, conversion_history)
3. `workspace/reports/migration-report.html` — HTML 리포트

수정 루프 완료 후, TC 보강 후, 어떤 재검증이든 끝나면 → **반드시 reporter에 위임하여 3개 파일 재생성.**
query-matrix.json에 필수 필드(query_id, original_file, sql_before, sql_after, final_state, test_cases, attempts, conversion_history)가 없으면 불완전.

## 대량 unconverted 패턴 처리

(+) outer join, MERGE INTO 등 대량 unconverted 패턴이 있을 때:
- **새 변환 스크립트를 만들지 마라.** `oracle-to-pg-converter.py`에 룰을 추가하라.
- LLM 개별 변환이 비효율적이면 → **converter 에이전트가 output XML을 직접 Edit**하라.
- 한 파일 안의 동일 패턴은 한번에 일괄 Edit. 쿼리별로 따로 하지 마라.

## 리더 전용 금지

- 리더가 직접 validate-queries.py를 실행하는 것 → **validate-and-fix에 위임**
- 리더가 직접 generate-report.py를 실행하는 것 → **reporter에 위임**
- "결과가 분산되어 있어 전체 통합 검증하겠다" → **reporter가 glob으로 통합**
- "전체 EXPLAIN 먼저 돌리고 그다음 Execute" → **--full 원자적 실행만**
- 배치 에이전트 결과를 무시하고 단일 재실행 → **기존 결과 덮어씌워짐**
