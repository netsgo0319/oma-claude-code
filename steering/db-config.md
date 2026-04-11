---
inclusion: manual
---

# DB 접속 설정

> 사용법: 채팅에서 #db-config 으로 호출

## Oracle (소스)

- Host: ${ORACLE_HOST}
- Port: ${ORACLE_PORT}
- SID/Service: ${ORACLE_SID}
- User: ${ORACLE_USER}
- Password: (환경변수 ORACLE_PASSWORD 참조)

## PostgreSQL (타겟)

- Host: ${PG_HOST}
- Port: ${PG_PORT}
- Database: ${PG_DATABASE}
- Schema: ${PG_SCHEMA}
- User: ${PG_USER}
- Password: (환경변수 PG_PASSWORD 참조)

## 테스트 설정

- statement_timeout: 30s
- 트랜잭션 모드: 읽기 전용 (SELECT), 롤백 (DML)
- 결과 비교 허용 오차: 소수점 1e-10, 날짜 포맷 차이 허용

## 환경변수 설정 예시

```bash
export ORACLE_HOST=oracle.example.com
export ORACLE_PORT=1521
export ORACLE_SID=ORCL
export ORACLE_USER=migration_user
export ORACLE_PASSWORD=****
export PG_HOST=pg.example.com
export PG_PORT=5432
export PG_DATABASE=target_db
export PG_SCHEMA=public
export PG_USER=migration_user
export PG_PASSWORD=****
```
