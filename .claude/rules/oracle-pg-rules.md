---
inclusion: always
---

# Oracle → PostgreSQL 변환 룰셋

> Converter 에이전트가 rule-convert 스킬 실행 시 참조.
> 반복 패턴 발견 시 여기에 룰 추가.

## 함수 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| NVL(a, b) | COALESCE(a, b) | |
| NVL2(a, b, c) | CASE WHEN a IS NOT NULL THEN b ELSE c END | |
| DECODE(a,b,c,...) | CASE a WHEN b THEN c ... END | 마지막 홀수 인자 = ELSE |
| SYSDATE | CURRENT_TIMESTAMP | DATE 컨텍스트면 CURRENT_DATE |
| SYSTIMESTAMP | CURRENT_TIMESTAMP | |
| LISTAGG(col, sep) WITHIN GROUP (ORDER BY ...) | STRING_AGG(col, sep ORDER BY ...) | WITHIN GROUP 제거 |
| ROWNUM | ROW_NUMBER() OVER() | 서브쿼리 래핑 필요할 수 있음 |
| sequence.NEXTVAL | nextval('sequence') | 따옴표 필수 |
| sequence.CURRVAL | currval('sequence') | |
| SUBSTR(s, pos, len) | SUBSTRING(s FROM pos FOR len) | 또는 SUBSTR 그대로 (PG 지원) |
| INSTR(s, sub) | POSITION(sub IN s) | 3번째 인자 있으면 별도 처리 |
| TO_DATE(s, fmt) | TO_DATE(s, fmt) | 포맷 문자열 변환 필요 |
| TO_CHAR(d, fmt) | TO_CHAR(d, fmt) | 포맷 문자열 변환 필요 |
| TO_NUMBER(s) | CAST(s AS NUMERIC) | 또는 s::NUMERIC |
| TRUNC(date_expr) | DATE_TRUNC('day', date_expr)::DATE | 복잡 표현식도 처리 (TRUNC(MAX(o.DATE)), TRUNC(o.COL) 등). 숫자 TRUNC(n, p)과 구별: 인자 1개=날짜, 2개=숫자 |
| SYSDATE - 30 | CURRENT_TIMESTAMP - INTERVAL '30 days' | Oracle date-number 연산 → PG INTERVAL 필수. timestamp - integer는 PG에서 에러 |
| SYSDATE + 7 | CURRENT_TIMESTAMP + INTERVAL '7 days' | 위와 동일 |
| DATE_LITERAL + numeric | DATE_LITERAL + numeric::INTEGER | PG에서 DATE + numeric 불가, DATE + integer 필요. ::INTEGER 캐스트 |
| date_column - N | date_column - N::INTEGER | 일반 date 컬럼 산술. **converter.py 자동 변환 구현됨** |
| LPAD(numeric, N, '0') | LPAD(expr::TEXT, N, '0') | PG LPAD는 TEXT만 허용. **converter.py 자동 변환 구현됨** |
| TO_CLOB(expr) | expr::TEXT | PG에 TO_CLOB 없음. **converter.py 자동 변환 구현됨** |
| TO_DATE(expr) 단일 인자 | TO_DATE(expr, 'YYYYMMDD') | PG는 포맷 필수. **converter.py 자동 변환 구현됨** |
| ADD_MONTHS(d, n) | d + INTERVAL 'n months' | |
| MONTHS_BETWEEN(d1, d2) | EXTRACT(YEAR FROM AGE(d1,d2))*12 + EXTRACT(MONTH FROM AGE(d1,d2)) | **interval 타입 혼용 주의**: d1-d2는 interval 반환 → COALESCE(interval, integer) 타입 불일치 오류. 일수 기반 대안: EXTRACT(DAY FROM (d1-d2))::INTEGER 또는 EXTRACT(EPOCH FROM (d1-d2))/86400 |
| LAST_DAY(d) | (DATE_TRUNC('month', d) + INTERVAL '1 month - 1 day')::DATE | |

## 정규식 함수 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| REGEXP_LIKE(str, pattern) | str ~ pattern | WHERE 절에서 사용, 대소문자 무시: ~* |
| REGEXP_LIKE(str, pattern, 'i') | str ~* pattern | i=대소문자 무시 |
| REGEXP_SUBSTR(str, pattern) | substring(str from pattern) | |
| REGEXP_SUBSTR(str, pattern, 1, n) | (regexp_matches(str, pattern, 'g'))[n] | n번째 발생, 복잡한 경우 커스텀 함수 |
| REGEXP_REPLACE(str, pattern, repl) | regexp_replace(str, pattern, repl) | 기본 호환 |
| REGEXP_REPLACE(str, pattern, repl, 1, 0, 'i') | regexp_replace(str, pattern, repl, 'gi') | 플래그 문법 차이 |
| REGEXP_INSTR(str, pattern) | (SELECT s FROM regexp_matches(str, pattern) LIMIT 1) 또는 커스텀 함수 | 직접 대응 없음 |
| REGEXP_COUNT(str, pattern) | (SELECT count(*) FROM regexp_matches(str, pattern, 'g')) | 12c+ |

## 조인 변환

| Oracle | PostgreSQL |
|--------|-----------|
| WHERE a.col = b.col(+) | a LEFT JOIN b ON a.col = b.col |
| WHERE a.col(+) = b.col | a RIGHT JOIN b ON a.col = b.col |
| 복수 (+) 조건 | 복수 ON 조건으로 변환 |

## 데이터 타입 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| VARCHAR2(n) | VARCHAR(n) | |
| NVARCHAR2(n) | VARCHAR(n) | |
| CHAR(n) | CHAR(n) | |
| NUMBER | NUMERIC | |
| NUMBER(p) | NUMERIC(p) | |
| NUMBER(p,s) | NUMERIC(p,s) | |
| INTEGER | INTEGER | |
| FLOAT | DOUBLE PRECISION | |
| DATE | TIMESTAMP | Oracle DATE = 날짜+시간 |
| TIMESTAMP | TIMESTAMP | |
| CLOB | TEXT | |
| NCLOB | TEXT | |
| BLOB | BYTEA | |
| RAW(n) | BYTEA | |
| LONG | TEXT | |
| XMLTYPE | XML | |

## 날짜 포맷 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| RR | YY | 2자리 연도 |
| YYYY | YYYY | |
| MM | MM | |
| DD | DD | |
| HH24 | HH24 | |
| HH / HH12 | HH12 | |
| MI | MI | |
| SS | SS | |
| FF / FF3 / FF6 | MS / US | 밀리초/마이크로초 |
| AM / PM | AM / PM | |
| DAY | DAY | |
| DY | DY | |
| MON | MON | |
| MONTH | MONTH | |
| Q | Q | 분기 |
| WW | WW | 주차 |
| D | D | 요일 번호 (주의: 시작점 다름) |

## 기타 구문 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| SELECT ... FROM DUAL | SELECT ... | FROM 절 제거 |
| '' (빈 문자열) = NULL | '' ≠ NULL | COALESCE/NULLIF로 래핑 검토 |
| /*+ HINT */ | -- hint: HINT (주석 보존) | 또는 제거 (설정 가능) |
| ROWID | ctid | 직접 대응 비권장, 로직 재설계 검토 |
| MINUS | EXCEPT | |
| DELETE table WHERE ... | DELETE FROM table WHERE ... | Oracle은 FROM 생략 가능, PG는 필수 |
| UPDATE T A SET A.COL=... | UPDATE T A SET COL=... | PG SET 절에 alias 불가. **converter.py 자동 변환** |
| UPDATE T SET (C1,C2)=(SELECT...) | UPDATE T SET C1=B.C1 FROM B WHERE... | Oracle tuple SET → PG UPDATE...FROM. LLM 변환 |
| table PARTITION(name) | 파티션 문법 다름 | 케이스별 검토 |
| CONNECT BY 단순 레벨 (LEVEL ≤ N) | generate_series(1, N) | 재귀 불필요 케이스. **converter.py 자동 변환 구현됨** |
| GREATEST(a, b, c) | GREATEST(COALESCE(a,0), COALESCE(b,0), COALESCE(c,0)) | **converter.py 자동 COALESCE 래핑 구현됨** |
| LEAST(a, b, c) | LEAST(COALESCE(a,0), COALESCE(b,0), COALESCE(c,0)) | GREATEST와 동일. **converter.py 자동 COALESCE 래핑 구현됨** |
| WM_CONCAT(col) | STRING_AGG(col::text, ',') | 비표준이지만 레거시에서 빈번. 정렬 보장 안 됨 |
| RETURNING id INTO :var | RETURNING id | MyBatis에서는 selectKey 방식으로 대체 가능 |
| FROM (서브쿼리) | FROM (서브쿼리) AS alias | **서브쿼리 alias 필수**: Oracle은 alias 없이 동작하지만 PG는 syntax error. 모든 인라인 뷰에 alias 추가 필수 |

## DBMS_* 패키지 함수 변환

| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| DBMS_LOB.SUBSTR(clob, len, pos) | SUBSTRING(text FROM pos FOR len) | 인자 순서 주의: Oracle은 (clob, len, pos), PG는 (FROM pos FOR len) |
| DBMS_LOB.GETLENGTH(clob) | LENGTH(text) | 또는 octet_length() for 바이트 |
| DBMS_LOB.INSTR(clob, pattern) | POSITION(pattern IN text) | |
| DBMS_LOB.APPEND(dest, src) | dest \|\| src | 문자열 연결 |
| DBMS_RANDOM.VALUE | random() | 0~1 범위 |
| DBMS_RANDOM.VALUE(low, high) | floor(random() * (high - low + 1) + low) | 범위 지정 |
| DBMS_CRYPTO.HASH(input, algo) | digest(input, 'sha256') | pgcrypto 확장 필요 |
| DBMS_OUTPUT.PUT_LINE(msg) | RAISE NOTICE '%', msg | PL/pgSQL 내에서 |
| PKG_CRYPTO.DECRYPT(input, key) | pkg_crypto$decrypt(input, key) | **converter.py 자동 변환**. PG에 래퍼 함수 필수 |
| PKG_CRYPTO.ENCRYPT(input, key) | pkg_crypto$encrypt(input, key) | **converter.py 자동 변환**. PG에 래퍼 함수 필수 |
| SCHEMA.PKG_CRYPTO.FUNC(args) | pkg_crypto_func(args) | 스키마 접두사 자동 제거 |
| PKG_* (커스텀 패키지 일반) | PL/pgSQL 함수 또는 확장 | LLM 태깅됨. 패키지 로직 분석 후 수동 변환 필요 |

**PKG_CRYPTO PG 함수 매핑 (DBA 제공):**
Oracle 패키지 `PKG_CRYPTO`는 PG에서 개별 함수로 변환됨:
| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| `PKG_CRYPTO.DECRYPT(input, key)` | `pkg_crypto$decrypt(input, key)` | 복호화 |
| `PKG_CRYPTO.ENCRYPT(input, key)` | `pkg_crypto$encrypt(input, key)` | 암호화 |
| `PKG_CRYPTO.DECRYPT_SESSION_KEY(key)` | `pkg_crypto$decrypt_session_key(key)` | 패키지 내부용 |
| `PKG_CRYPTO.ENCRYPT_SESSION_KEY(key)` | `pkg_crypto$encrypt_session_key(key)` | 패키지 내부용 |
| `PKG_CRYPTO.MASTER_KEY()` | `PG에 없음 (WARNING)` | 패키지 내부용 |
PG prerequisite: `CREATE EXTENSION IF NOT EXISTS pgcrypto;` + 위 5개 함수 DDL

## MyBatis/iBatis 특수 변환

| 대상 | Oracle 패턴 | PostgreSQL 패턴 |
|------|------------|----------------|
| selectKey | SELECT SEQ.NEXTVAL FROM DUAL | SELECT nextval('seq') |
| selectKey order | type="pre" (iBatis) | order="BEFORE" |
| 파라미터 표기 | #prop# (iBatis) | #{prop} (MyBatis) |
| 파라미터 표기 | $prop$ (iBatis) | ${prop} (MyBatis) |
| procedure 호출 | {call PKG.PROC()} | SELECT * FROM proc() |

**주의: `#{sysdate}`, `#{delyn}` 등 MyBatis 바인드 파라미터는 Oracle 패턴이 아니다.**
`#{...}` 안의 문자열은 Java 코드에서 전달되는 값이며, SQL 변환 대상이 절대 아니다.
`SYSDATE` 변환은 `#{sysdate}` 밖의 bare `SYSDATE`에만 적용된다.
