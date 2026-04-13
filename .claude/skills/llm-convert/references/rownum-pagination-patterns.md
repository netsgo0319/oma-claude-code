# ROWNUM Pagination → LIMIT/OFFSET 변환 패턴

## Pattern 1: 단순 ROWNUM 제한

```sql
-- Oracle
SELECT * FROM users WHERE ROWNUM <= 10
-- PostgreSQL
SELECT * FROM users LIMIT 10
```

## Pattern 2: ROWNUM 페이징 (2중 서브쿼리)

```sql
-- Oracle
SELECT * FROM (
  SELECT a.*, ROWNUM rn FROM users a
  WHERE ROWNUM <= 20
) WHERE rn > 10

-- PostgreSQL
SELECT * FROM users LIMIT 10 OFFSET 10
```
> pageEnd=20, pageStart=10 → LIMIT (20-10) OFFSET 10

## Pattern 3: ROWNUM 페이징 (3중 서브쿼리, ORDER BY 포함)

이것이 가장 일반적인 Oracle 페이징 패턴.

```sql
-- Oracle
SELECT * FROM (
  SELECT a.*, ROWNUM rn FROM (
    SELECT u.id, u.name, u.email
    FROM users u
    WHERE u.status = 'ACTIVE'
    ORDER BY u.created_at DESC
  ) a
  WHERE ROWNUM <= #{pageEnd}
) WHERE rn > #{pageStart}

-- PostgreSQL
SELECT u.id, u.name, u.email
FROM users u
WHERE u.status = 'ACTIVE'
ORDER BY u.created_at DESC
LIMIT (#{pageEnd} - #{pageStart}) OFFSET #{pageStart}
```

### 3중 구조 인식 방법
```
최외곽: SELECT * FROM (...) WHERE rn > #{pageStart}
  중간: SELECT a.*, ROWNUM rn FROM (...) a WHERE ROWNUM <= #{pageEnd}
    내부: 실제 쿼리 (SELECT ... FROM ... WHERE ... ORDER BY ...)
```

변환 시:
1. 내부 쿼리를 추출
2. 중간/외곽 래퍼 제거
3. 내부 쿼리 끝에 LIMIT/OFFSET 추가

## Pattern 4: 3중 페이징 + 동적 SQL

```xml
<!-- Oracle -->
<select id="pagedSearch">
  SELECT * FROM (
    SELECT a.*, ROWNUM rn FROM (
      SELECT u.id, u.name
      FROM users u
      <where>
        <if test="name != null">AND u.name LIKE '%' || #{name} || '%'</if>
        <if test="status != null">AND u.status = #{status}</if>
      </where>
      ORDER BY u.created_at DESC
    ) a WHERE ROWNUM &lt;= #{pageEnd}
  ) WHERE rn > #{pageStart}
</select>

<!-- PostgreSQL -->
<select id="pagedSearch">
  SELECT u.id, u.name
  FROM users u
  <where>
    <if test="name != null">AND u.name LIKE '%' || #{name} || '%'</if>
    <if test="status != null">AND u.status = #{status}</if>
  </where>
  ORDER BY u.created_at DESC
  LIMIT (#{pageEnd} - #{pageStart}) OFFSET #{pageStart}
</select>
```

핵심: 동적 SQL 태그(<where>, <if>)를 보존하면서 ROWNUM 래퍼만 제거.

## Pattern 5: ROW_NUMBER() OVER() 사용 패턴

LIMIT/OFFSET 대신 ROW_NUMBER()를 유지하고 싶은 경우:

```sql
-- Oracle
SELECT * FROM (
  SELECT a.*, ROWNUM rn FROM (
    SELECT u.* FROM users u ORDER BY u.created_at DESC
  ) a WHERE ROWNUM <= 20
) WHERE rn > 10

-- PostgreSQL (ROW_NUMBER 방식)
SELECT * FROM (
  SELECT u.*, ROW_NUMBER() OVER (ORDER BY u.created_at DESC) AS rn
  FROM users u
) sub
WHERE rn > 10 AND rn <= 20
```

이 방식은 복잡한 ORDER BY가 있거나 rn을 결과에 포함해야 할 때 유용.

## Pattern 6: ROWNUM = 1 (단일 행 제한)

```sql
-- Oracle
SELECT * FROM users WHERE status = 'ACTIVE' AND ROWNUM = 1
-- PostgreSQL
SELECT * FROM users WHERE status = 'ACTIVE' LIMIT 1
```

## Pattern 7: ROWNUM in UPDATE/DELETE

```sql
-- Oracle
DELETE FROM logs WHERE log_date < SYSDATE - 30 AND ROWNUM <= 1000
-- PostgreSQL
DELETE FROM logs WHERE ctid IN (
  SELECT ctid FROM logs WHERE log_date < CURRENT_TIMESTAMP - INTERVAL '30 days' LIMIT 1000
)
```

## 주의사항

### ROWNUM + ORDER BY 순서 문제
Oracle에서 `WHERE ROWNUM <= 10 ORDER BY name`은 **먼저 10행을 가져온 후 정렬**한다.
PostgreSQL에서 `ORDER BY name LIMIT 10`은 **정렬 후 10행을 가져온다**.

```sql
-- Oracle (잘못된 변환 — 결과가 다를 수 있음!)
SELECT * FROM users WHERE ROWNUM <= 10 ORDER BY name
-- PostgreSQL (정확한 변환)
SELECT * FROM (SELECT * FROM users LIMIT 10) sub ORDER BY name
```

단, 3중 페이징 패턴에서는 내부에 ORDER BY가 있으므로 이 문제 없음.

### MyBatis에서 &lt; 이스케이프
XML에서 `<`는 태그로 인식되므로 `&lt;`로 이스케이프 필요:
```xml
WHERE ROWNUM &lt;= #{pageEnd}
```
변환 시 이 이스케이프를 유지해야 함.

## Pattern 8: FETCH FIRST N ROWS ONLY (Oracle 12c+)

```sql
-- Oracle 12c+
SELECT id, name FROM users ORDER BY id FETCH FIRST 10 ROWS ONLY
-- PostgreSQL
SELECT id, name FROM users ORDER BY id LIMIT 10
```

## Pattern 9: OFFSET N ROWS FETCH NEXT M ROWS ONLY (Oracle 12c+)

```sql
-- Oracle 12c+
SELECT id, name FROM users ORDER BY id OFFSET 10 ROWS FETCH NEXT 10 ROWS ONLY
-- PostgreSQL
SELECT id, name FROM users ORDER BY id LIMIT 10 OFFSET 10
```

## Pattern 10: FETCH FIRST WITH TIES

```sql
-- Oracle 12c+
SELECT id, name, salary FROM employees ORDER BY salary DESC FETCH FIRST 5 ROWS WITH TIES
-- PostgreSQL (FETCH WITH TIES는 PG 13+에서 지원)
SELECT id, name, salary FROM employees ORDER BY salary DESC FETCH FIRST 5 ROWS WITH TIES
```
> PG 13 이상에서는 동일 문법 지원. PG 12 이하에서는 윈도우 함수로 대체 필요.
