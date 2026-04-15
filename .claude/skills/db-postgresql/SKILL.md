---
name: db-postgresql
description: PostgreSQL 쿼리 실행. psql CLI로 EXPLAIN, SELECT, DML을 실행할 때 사용합니다. 환경변수(PG_HOST 등)로 접속합니다.
---

## 접속 정보
환경변수에서 참조:
- PG_HOST, PG_PORT, PG_DATABASE, PG_SCHEMA, PG_USER, PG_PASSWORD

## 공통 접속 옵션
```bash
PGPASSWORD=${PG_PASSWORD} psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${PG_DATABASE}
```

## 쿼리 실행 방법

### EXPLAIN (문법 검증)
```bash
PGPASSWORD=${PG_PASSWORD} psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${PG_DATABASE} \
  -c "SET statement_timeout = '30s'; EXPLAIN {sql}"
```

### SELECT (결과 출력)
```bash
PGPASSWORD=${PG_PASSWORD} psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${PG_DATABASE} \
  -c "SET statement_timeout = '30s'; {sql}"
```

### SELECT (CSV 형식)
```bash
PGPASSWORD=${PG_PASSWORD} psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${PG_DATABASE} \
  --csv -c "SET statement_timeout = '30s'; {sql}"
```

### DML (트랜잭션 내 실행 + ROLLBACK)
```bash
PGPASSWORD=${PG_PASSWORD} psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${PG_DATABASE} \
  -c "BEGIN; SET statement_timeout = '30s'; {sql}; ROLLBACK;"
```

### EXPLAIN ANALYZE (실행 계획 + 실제 실행 통계)
```bash
PGPASSWORD=${PG_PASSWORD} psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${PG_DATABASE} \
  -c "SET statement_timeout = '30s'; EXPLAIN ANALYZE {sql}"
```

## 안전 규칙
- DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE 절대 실행 금지
- DELETE, INSERT, UPDATE는 반드시 BEGIN/ROLLBACK 내에서만 실행
- statement_timeout 30초 필수 설정 (무한 재귀 방지)
- 접속 비밀번호는 환경변수(PGPASSWORD)만 사용
- 쿼리 실행 전 반드시 SQL 내용을 검토하여 파괴적 구문이 없는지 확인
