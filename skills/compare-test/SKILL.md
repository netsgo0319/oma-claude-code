---
name: compare-test
description: 동일 파라미터로 Oracle과 PostgreSQL에 쿼리를 실행하여 결과를 비교한다. execute-test 통과한 SELECT 쿼리만 대상으로 한다.
---

## 입력
- workspace/results/{filename}/v{n}/validated.json (explain + execute 결과)
- workspace/results/{filename}/v{n}/converted.json (PostgreSQL SQL)
- workspace/results/{filename}/v{n}/parsed.json (원본 Oracle SQL)

## 처리 절차

1. validated.json에서 execute.status == "pass" 이고 type == "select"인 쿼리 필터

2. 동일 더미 파라미터로 양쪽 실행:
   - Oracle: parsed.json의 원본 SQL + 더미 파라미터
   - PostgreSQL: converted.json의 변환 SQL + 더미 파라미터

3. 결과 비교 항목:

   a. **행 수** — 정확히 일치해야 함
   b. **컬럼명** — 대소문자 무시하고 비교 (Oracle은 대문자, PG는 소문자 기본)
   c. **컬럼 타입** — 호환 매핑 허용:
      - Oracle DATE ↔ PostgreSQL TIMESTAMP
      - Oracle NUMBER ↔ PostgreSQL NUMERIC/INTEGER
      - Oracle VARCHAR2 ↔ PostgreSQL VARCHAR
   d. **데이터 값** — 허용 오차 적용:
      - 숫자: 절대 오차 1e-10 이내
      - 날짜: 포맷 차이 허용 (시간 부분 무시 옵션)
      - 문자열: 정확히 일치
      - NULL: 양쪽 모두 NULL이면 일치
   e. **정렬 순서** — ORDER BY가 있는 쿼리만 비교

4. 결과 분류:
   - pass: 모든 항목 일치
   - warn: 사소한 차이 (날짜 포맷, NULL vs 빈 문자열)
   - fail: 실질적 차이 (행 수 불일치, 값 불일치)

5. validated.json의 compare 섹션에 기록:
   ```json
   {
     "query_id": "selectUserById",
     "compare": {
       "status": "pass",
       "oracle_rows": 15,
       "pg_rows": 15,
       "match": true,
       "differences": []
     }
   }
   ```
   차이 발견 시:
   ```json
   {
     "compare": {
       "status": "warn",
       "oracle_rows": 15,
       "pg_rows": 15,
       "match": false,
       "differences": [
         {
           "row": 3,
           "column": "created_at",
           "oracle_value": "2024-01-15",
           "pg_value": "2024-01-15 00:00:00",
           "type": "date_format"
         }
       ]
     }
   }
   ```

## Result Integrity Guard (Step 4: 결과 신뢰성 종합 검증)

compare-test 결과가 pass여도 결과의 신뢰성을 다각도로 검증한다.
"양쪽 같음 = 변환 성공"이라는 가정의 허점을 찾아낸다.

### A. 행 수 신뢰성

| 코드 | 심각도 | 조건 |
|------|--------|------|
| WARN_ZERO_BOTH | high | 운영 바인드 값인데 양쪽 0건 |
| WARN_ZERO_ALL_CASES | critical | 모든 테스트 케이스가 0건 |
| WARN_BELOW_EXPECTED | high | expected_rows_hint 대비 10% 미만 |
| WARN_SAME_COUNT_DIFF_ROWS | critical | 행 수 동일하지만 행 내용 해시 불일치 |

행 내용 해시 비교 방법:
1. 양쪽 결과를 전 컬럼으로 정렬
2. 각 행을 JSON 직렬화 → SHA256
3. 해시 집합 비교 → 불일치 행 식별

### B. 값 수준

| 코드 | 심각도 | 조건 |
|------|--------|------|
| WARN_NULL_NON_NULLABLE | medium | NOT NULL 컬럼에서 NULL |
| WARN_EMPTY_VS_NULL | medium | Oracle '' vs PG NULL (또는 반대) |
| WARN_WHITESPACE_DIFF | medium | CHAR 패딩 차이 ('ABC   ' vs 'ABC') |
| WARN_NUMERIC_SCALE | medium | 후행 0 차이 (1.10 vs 1.1) |

trailing space 감지:
1. CHAR 타입 컬럼 식별 (ALL_TAB_COLUMNS)
2. Oracle/PG LENGTH 비교
3. TRIM 후 동일하면 → 패딩 경고

### C. 타입/정밀도

| 코드 | 심각도 | 조건 |
|------|--------|------|
| WARN_DATE_PRECISION | medium | Oracle DATE(초) vs PG TIMESTAMP(마이크로초) |
| WARN_IMPLICIT_CAST | high | 바인드 타입 vs 컬럼 타입 불일치 (Oracle 암묵적 변환) |
| WARN_CLOB_TRUNCATION | high | TEXT 값 길이가 Oracle CLOB과 다름 |
| WARN_BOOLEAN_REPR | medium | Oracle 'Y'/'N'/1/0 vs PG boolean |

### D. 정렬/구조

| 코드 | 심각도 | 조건 |
|------|--------|------|
| WARN_NULL_SORT_ORDER | medium | ORDER BY에서 NULL 행 위치 차이 |
| WARN_CASE_SENSITIVITY | high | 대소문자 비교 동작 차이 |

### severity별 후속 처리
- `critical` → Reviewer 자동 에스컬레이션 (compare pass여도)
- `high` → migration-guide.md 수동 검토 항목
- `medium` → conversion-report.md 경고 기록

## 주의사항
- Oracle과 PostgreSQL 양쪽 모두 읽기 전용 실행
- INSERT/UPDATE/DELETE는 비교 대상 아님 (execute-test에서 이미 검증)
- 대량 결과 시 상위 100행만 비교 (성능)
- 비교 불가 시 (Oracle 접속 실패 등) → status: "skipped", reason 기록
