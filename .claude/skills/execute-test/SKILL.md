---
name: execute-test
description: PostgreSQL 실제 실행 검증. validate-and-fix 에이전트가 EXPLAIN 통과한 SQL을 실제 실행하여 런타임 에러를 확인할 때 사용합니다. BEGIN/ROLLBACK 내에서 안전하게 실행합니다.
---

## 입력
- workspace/results/{filename}/v{n}/validated.json (explain 결과 포함)
- workspace/results/{filename}/v{n}/converted.json (SQL 원문)

## 처리 절차

1. validated.json에서 explain.status == "pass"인 쿼리만 필터

2. 파라미터 더미 바인딩 (explain-test와 동일 전략)

3. 쿼리 타입별 실행 전략:
   - SELECT:
     ```sql
     SET statement_timeout = '30s';
     {변환된_SQL_with_dummy_params}
     ```
     결과 행 수, 컬럼 구조, 실행 시간 기록

   - INSERT/UPDATE/DELETE:
     ```sql
     SET statement_timeout = '30s';
     BEGIN;
     {변환된_SQL_with_dummy_params}
     -- 영향받은 행 수 기록
     ROLLBACK;
     ```

4. 결과 분류:
   - pass: 정상 실행 완료
   - fail: 런타임 에러
     - RUNTIME_ERROR: 타입 불일치, 함수 미존재 등
     - INFINITE_RECURSION: WITH RECURSIVE 무한 루프
     - TIMEOUT: statement_timeout 초과
     - PERMISSION: 권한 부족

5. validated.json의 execute 섹션에 기록:
   ```json
   {
     "query_id": "selectUserById",
     "execute": {
       "status": "pass",
       "rows": 15,
       "columns": ["id", "name", "email"],
       "duration_ms": 23
     }
   }
   ```

## Oracle vs PostgreSQL 비교 실행 (--compare 모드)

validate-queries.py --compare 사용 시 SELECT과 DML 모두 양쪽에서 실행:

- **SELECT**: Oracle과 PG 양쪽에서 실행, row count + 값 비교
- **INSERT/UPDATE/DELETE**: Oracle(ROLLBACK) + PG(BEGIN/ROLLBACK), affected rows 비교
- DML affected rows가 다르면 WHERE 조건 변환 오류 의심

## 주의사항
- DML은 반드시 BEGIN/ROLLBACK으로 감싸기 — 데이터 변경 방지 (Oracle/PG 모두)
- statement_timeout 30초 — 무한 재귀 방지
- 실행 결과 데이터는 저장하지 않음 (행 수/컬럼 구조만)
- Oracle 접속 불가 시 PG만 실행 (비교 불가 안내)

## 체크리스트

```
Execute 검증:
- [ ] 1. EXPLAIN 통과 쿼리만 대상
- [ ] 2. BEGIN 트랜잭션 내 실행
- [ ] 3. SELECT COUNT(*) 형태로 행수 확인
- [ ] 4. DML은 SELECT COUNT(*) WHERE로 대체
- [ ] 5. statement_timeout 30초
- [ ] 6. ROLLBACK
```

## 참조 문서

- [검증 스키마](../../schemas/validated.schema.json)
- [안전 규칙](../../rules/guardrails.md)
