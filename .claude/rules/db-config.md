---
inclusion: manual
---

# DB 접속 설정

> 사용법: 채팅에서 #db-config 으로 호출

## Oracle (소스)

- Host: ${ORACLE_HOST}
- Port: ${ORACLE_PORT}
- SID/Service Name: ${ORACLE_SID} (PDB는 보통 Service Name)
- 접속 방식: ${ORACLE_CONN_TYPE} (`service` 또는 `sid`, 기본값: `service`)
- User: ${ORACLE_USER} (쿼리 실행/비교용)
- Schema: ${ORACLE_SCHEMA} (대상 스키마, 기본값: ORACLE_USER)
- Password: (환경변수 ORACLE_PASSWORD 참조)

## PostgreSQL (타겟)

- Host: ${PG_HOST}
- Port: ${PG_PORT}
- Database: ${PG_DATABASE}
- Schema: ${PG_SCHEMA}
- User: ${PG_USER}
- Password: (환경변수 PG_PASSWORD 참조)

## PG Prerequisites (Phase 0에서 확인)

- `CREATE EXTENSION IF NOT EXISTS pgcrypto;` — PKG_CRYPTO 변환 시 필수
- 대상 스키마의 테이블/시퀀스 존재 여부 확인

## 테스트 설정

- statement_timeout: 30s
- 트랜잭션 모드: 읽기 전용 (SELECT), 롤백 (DML)
- 결과 비교 허용 오차: 소수점 1e-10, 날짜 포맷 차이 허용

## 환경변수 설정 예시

```bash
# Oracle
export ORACLE_HOST=10.0.139.149
export ORACLE_PORT=1521
export ORACLE_SID=ORCLPDB1          # PDB Service Name
export ORACLE_CONN_TYPE=service     # 'service' (기본) 또는 'sid'
export ORACLE_USER=wmson
export ORACLE_PASSWORD=****
export ORACLE_SCHEMA=WMSON          # 딕셔너리 쿼리 대상 스키마 (admin 계정 사용 시)

# Java 소스 (VO/DTO 분석용 — 복사 불필요, 경로 참조만)
export JAVA_SRC_DIR=/path/to/app/src/main/java

# PostgreSQL
export PG_HOST=pg.example.com
export PG_PORT=5432
export PG_DATABASE=target_db
export PG_SCHEMA=public
export PG_USER=migration_user
export PG_PASSWORD=****
```

## 접속 방식 차이

| 환경변수 | Service Name (PDB) | SID (전통) |
|---------|-------------------|------------|
| ORACLE_CONN_TYPE | `service` (기본) | `sid` |
| 접속 문자열 | `user/pass@host:port/service` | TNS descriptor |
| 사용 환경 | Oracle 12c+ PDB, Cloud | 레거시 단일 인스턴스 |
