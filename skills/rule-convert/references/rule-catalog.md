# Rule Catalog — 변환 룰 상세 가이드

## 1. NVL → COALESCE

### 단순 케이스
```sql
-- Oracle
SELECT NVL(name, 'Unknown') FROM users
-- PostgreSQL
SELECT COALESCE(name, 'Unknown') FROM users
```

### 중첩 케이스
```sql
-- Oracle
SELECT NVL(NVL(nickname, name), 'Unknown') FROM users
-- PostgreSQL
SELECT COALESCE(nickname, name, 'Unknown') FROM users
```
> COALESCE는 다중 인자 지원하므로 중첩 NVL은 단일 COALESCE로 평탄화 가능

## 2. DECODE → CASE

### 단순 분기
```sql
-- Oracle
SELECT DECODE(status, 'A', 'Active', 'I', 'Inactive', 'Unknown') FROM users
-- PostgreSQL
SELECT CASE status WHEN 'A' THEN 'Active' WHEN 'I' THEN 'Inactive' ELSE 'Unknown' END FROM users
```

### NULL 비교
```sql
-- Oracle
SELECT DECODE(col, NULL, 'null', 'not null') FROM t
-- PostgreSQL
SELECT CASE WHEN col IS NULL THEN 'null' ELSE 'not null' END FROM t
```
> DECODE의 첫 비교값이 NULL이면 CASE WHEN ... IS NULL 형태로 변환

## 3. ROWNUM → ROW_NUMBER() / LIMIT

### WHERE ROWNUM 필터
```sql
-- Oracle
SELECT * FROM users WHERE ROWNUM <= 10
-- PostgreSQL
SELECT * FROM users LIMIT 10
```

### 서브쿼리 페이징
```sql
-- Oracle
SELECT * FROM (
  SELECT a.*, ROWNUM rn FROM (SELECT * FROM users ORDER BY id) a
  WHERE ROWNUM <= 20
) WHERE rn > 10
-- PostgreSQL
SELECT * FROM users ORDER BY id LIMIT 10 OFFSET 10
```

### SELECT 절의 ROWNUM
```sql
-- Oracle
SELECT ROWNUM, name FROM users
-- PostgreSQL
SELECT ROW_NUMBER() OVER() AS rownum, name FROM users
```

## 4. (+) 아우터 조인 → ANSI JOIN

### LEFT JOIN
```sql
-- Oracle
SELECT a.name, b.dept_name
FROM employees a, departments b
WHERE a.dept_id = b.dept_id(+)
-- PostgreSQL
SELECT a.name, b.dept_name
FROM employees a
LEFT JOIN departments b ON a.dept_id = b.dept_id
```

### 복수 조건
```sql
-- Oracle
WHERE a.dept_id = b.dept_id(+) AND a.loc_id = b.loc_id(+)
-- PostgreSQL
LEFT JOIN departments b ON a.dept_id = b.dept_id AND a.loc_id = b.loc_id
```

## 5. 시퀀스

```sql
-- Oracle
SELECT SEQ_USER.NEXTVAL FROM DUAL
INSERT INTO users (id) VALUES (SEQ_USER.NEXTVAL)
-- PostgreSQL
SELECT nextval('seq_user')
INSERT INTO users (id) VALUES (nextval('seq_user'))
```
> 시퀀스명은 소문자 + 따옴표로 감싸기

## 6. FROM DUAL 제거

```sql
-- Oracle
SELECT SYSDATE FROM DUAL
SELECT 1 + 1 FROM DUAL
-- PostgreSQL
SELECT CURRENT_TIMESTAMP
SELECT 1 + 1
```

## 7. 빈 문자열과 NULL

Oracle에서 `'' = NULL`이지만 PostgreSQL에서는 다름.

```sql
-- Oracle
SELECT * FROM users WHERE name IS NOT NULL  -- 빈 문자열도 제외됨
-- PostgreSQL (동일 동작을 위해)
SELECT * FROM users WHERE name IS NOT NULL AND name != ''
```

> 이 패턴은 컨텍스트에 따라 판단 필요. 자동 변환 시 warn 태그 추가.

## 8. selectKey 변환

```xml
<!-- Oracle (MyBatis) -->
<selectKey keyProperty="id" resultType="int" order="BEFORE">
  SELECT SEQ_USER.NEXTVAL FROM DUAL
</selectKey>

<!-- PostgreSQL (MyBatis) -->
<selectKey keyProperty="id" resultType="int" order="BEFORE">
  SELECT nextval('seq_user')
</selectKey>
```

```xml
<!-- Oracle (iBatis) -->
<selectKey keyProperty="id" resultClass="int" type="pre">
  SELECT SEQ_USER.NEXTVAL FROM DUAL
</selectKey>

<!-- PostgreSQL (iBatis → 그대로 iBatis 문법 유지) -->
<selectKey keyProperty="id" resultClass="int" type="pre">
  SELECT nextval('seq_user')
</selectKey>
```
