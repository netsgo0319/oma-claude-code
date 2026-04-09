---
name: explain-test
description: 변환된 PostgreSQL 쿼리에 EXPLAIN을 실행하여 문법 오류를 검증한다. 실제 실행 없이 쿼리 플랜 생성 가능 여부만 확인한다.
---

## 입력
- workspace/results/{filename}/v{n}/converted.json

## 처리 절차

1. converted.json 로드 → 변환된 SQL 목록 추출

2. 동적 SQL의 파라미터를 테스트용 더미 값으로 바인딩:
   - VARCHAR/TEXT 파라미터 → 'test'
   - INTEGER/NUMERIC 파라미터 → 1
   - DATE/TIMESTAMP 파라미터 → '2024-01-01'
   - 파라미터 타입은 parsed.json의 parameterType 및 jdbcType 참조
   - #{param} → 더미 값으로 직접 치환하여 실행 가능한 SQL 생성

3. 각 쿼리에 대해 PostgreSQL EXPLAIN 실행:
   ```sql
   EXPLAIN {변환된_SQL_with_dummy_params}
   ```

4. 결과 분류:
   - pass: EXPLAIN 플랜 정상 생성
   - fail: 문법 오류 (에러 메시지 전문 기록)

5. validated.json의 explain 섹션에 기록:
   ```json
   {
     "query_id": "selectUserById",
     "explain": {
       "status": "pass",
       "plan": "Seq Scan on users..."
     }
   }
   ```
   실패 시:
   ```json
   {
     "query_id": "getOrgHierarchy",
     "explain": {
       "status": "fail",
       "error": "ERROR: syntax error at or near \"CONNECT\""
     }
   }
   ```

6. 실패한 쿼리는 execute-test, compare-test 스킵 대상으로 표시

## 주의사항
- EXPLAIN만 실행 (EXPLAIN ANALYZE 아님) — 실제 실행 없이 플랜만 확인
- DML (INSERT/UPDATE/DELETE)도 EXPLAIN 가능
- 테이블/컬럼이 존재하지 않으면 EXPLAIN도 실패함 — 이 경우 에러를 기록하고 별도 분류 (MISSING_OBJECT)
