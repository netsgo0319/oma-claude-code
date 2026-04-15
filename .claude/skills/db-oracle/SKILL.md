---
name: db-oracle
description: Oracle DB 쿼리 실행. sqlplus CLI로 SELECT, DML, 메타데이터를 조회할 때 사용합니다. 환경변수(ORACLE_HOST 등)로 접속합니다.
---

## 접속 정보
환경변수에서 참조:
- ORACLE_HOST, ORACLE_PORT, ORACLE_SID, ORACLE_USER, ORACLE_PASSWORD

## 쿼리 실행 방법

### SELECT (결과 출력)
```bash
echo "SET LINESIZE 32767
SET PAGESIZE 50000
SET FEEDBACK OFF
SET HEADING ON
{sql}
;" | sqlplus -S ${ORACLE_USER}/${ORACLE_PASSWORD}@${ORACLE_HOST}:${ORACLE_PORT}/${ORACLE_SID}
```

### SELECT (CSV 형식)
```bash
echo "SET COLSEP ','
SET LINESIZE 32767
SET PAGESIZE 0
SET FEEDBACK OFF
SET HEADING ON
{sql}
;" | sqlplus -S ${ORACLE_USER}/${ORACLE_PASSWORD}@${ORACLE_HOST}:${ORACLE_PORT}/${ORACLE_SID}
```

### DML (트랜잭션 내 실행 + 결과 확인 후 ROLLBACK)
```bash
echo "SET FEEDBACK ON
{sql};
ROLLBACK;
" | sqlplus -S ${ORACLE_USER}/${ORACLE_PASSWORD}@${ORACLE_HOST}:${ORACLE_PORT}/${ORACLE_SID}
```

### 딕셔너리 조회
V$SQL, ALL_TAB_COLUMNS 등 시스템 뷰 조회에 동일한 SELECT 방식 사용.
권한 오류(ORA-00942, ORA-01031) 발생 시 해당 쿼리를 스킵하고 다음으로 진행.

## 안전 규칙
- DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE 절대 실행 금지
- DML은 반드시 ROLLBACK과 함께 실행
- 접속 비밀번호는 환경변수만 사용 (하드코딩 금지)
- 쿼리 실행 전 반드시 SQL 내용을 검토하여 파괴적 구문이 없는지 확인

## 참조 문서

- [Oracle 접속 설정](../../rules/db-config.md)
