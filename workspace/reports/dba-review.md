# DBA Review: Oracle-to-PostgreSQL Migration Agent System

**검토자**: Senior Oracle/PostgreSQL DBA (20+ years experience)
**검토일**: 2026-04-09
**검토 대상**: Kiro Agent System 전체 (skills, steering, prompts, fixtures)

---

## 1. Oracle 함수 커버리지 (oracle-pg-rules.md)

**평가: 부분적 -- 핵심 함수는 커버하나, 실무에서 흔히 쓰이는 상당수 함수가 빠져 있음**

### 1.1 현재 커버되는 함수 (22개)

NVL, NVL2, DECODE, SYSDATE, SYSTIMESTAMP, LISTAGG, ROWNUM, SUBSTR, INSTR,
TO_DATE, TO_CHAR, TO_NUMBER, TRUNC(date), ADD_MONTHS, MONTHS_BETWEEN, LAST_DAY,
sequence.NEXTVAL/CURRVAL, FROM DUAL, (+) outer join, MINUS, Oracle hints

### 1.2 빠진 중요 함수/구문 (우선순위별)

#### P0 -- 거의 모든 운영 시스템에서 발견됨
| 빠진 함수/구문 | Oracle 용법 | PostgreSQL 변환 | 비고 |
|---------------|------------|----------------|------|
| `REGEXP_LIKE` | `WHERE REGEXP_LIKE(col, pattern)` | `WHERE col ~ pattern` | 정규식 필터, 매우 빈번 |
| `REGEXP_SUBSTR` | `REGEXP_SUBSTR(str, pattern, 1, n)` | `(regexp_matches(str, pattern))[n]` 또는 `substring(str from pattern)` | 위치/발생횟수 인자 처리 복잡 |
| `REGEXP_REPLACE` | `REGEXP_REPLACE(str, pattern, repl)` | `regexp_replace(str, pattern, repl)` | 기본 호환이나 6번째 인자(match_parameter) 차이 |
| `REGEXP_INSTR` | `REGEXP_INSTR(str, pattern)` | 직접 대응 없음, PL/pgSQL 함수 필요 | |
| `REGEXP_COUNT` | `REGEXP_COUNT(str, pattern)` | `array_length(regexp_split_to_array(str, pattern), 1) - 1` 또는 커스텀 함수 | 12c+ |
| `TRIM(LEADING/TRAILING/BOTH)` | `TRIM(LEADING '0' FROM col)` | `LTRIM(col, '0')` | 문법 차이 주의 |
| `LPAD / RPAD` | `LPAD(col, 10, '0')` | `LPAD(col, 10, '0')` | PG도 지원하지만 멀티바이트에서 동작 차이 |
| `REPLACE` | `REPLACE(str, old, new)` | `REPLACE(str, old, new)` | 호환이지만 명시적 문서화 필요 |
| `GREATEST / LEAST` | `GREATEST(a, b, c)` | `GREATEST(a, b, c)` | NULL 처리 차이: Oracle은 NULL 무시, PG는 NULL 반환 |
| `COALESCE` (이미 있지만) | | | Oracle COALESCE는 short-circuit, PG도 동일이지만 명시 필요 |
| `CASE WHEN` 내 NULL 비교 | `DECODE(col, NULL, ...)` | | DECODE-NULL 패턴만 있고 일반 CASE NULL 비교 가이드 부족 |
| `WM_CONCAT` (비표준이지만 실무에서 빈번) | `WM_CONCAT(col)` | `STRING_AGG(col, ',')` | 정렬 보장 안 됨, 레거시 시스템에서 매우 빈번 |

#### P1 -- 중급 빈도 (데이터 분석/리포팅 쿼리에서 자주 발견)
| 빠진 함수/구문 | Oracle 용법 | PostgreSQL 변환 |
|---------------|------------|----------------|
| `EXTRACT(YEAR/MONTH/DAY FROM date)` | 동일하지만 Oracle DATE vs TIMESTAMP 타입 차이로 결과 다를 수 있음 | |
| `NUMTODSINTERVAL / NUMTOYMINTERVAL` | `NUMTODSINTERVAL(n, 'DAY')` | `make_interval(days => n)` 또는 `n * INTERVAL '1 day'` |
| `INTERVAL 표현식` | `INTERVAL '5' DAY` (Oracle 전용 문법) | `INTERVAL '5 days'` (PostgreSQL 문법) |
| `NEXT_DAY(date, 'MON')` | 다음 월요일 | 직접 대응 없음, 커스텀 함수 필요 |
| `ROUND(date)` | `ROUND(SYSDATE, 'MM')` | 직접 대응 없음, `DATE_TRUNC + 조건부 올림` |
| `CEIL(date)` | `CEIL(SYSDATE - date)` | 컨텍스트별 다름 |
| `CAST(MULTISET(...))` | 컬렉션 변환 | PG는 ARRAY로 대체, 구조적 재설계 필요 |
| `XMLTABLE` | XML 파싱 | `XMLTABLE` (PG 지원하지만 문법 차이) |
| `XMLQUERY / XMLELEMENT / XMLFOREST` | XML 생성/조회 | PG 지원하지만 함수명/문법 차이 |
| `JSON_TABLE` (12c+) | JSON 파싱 | `jsonb_to_recordset` 등 |
| `BITAND` | `BITAND(a, b)` | `a & b` |
| `LENGTHB / SUBSTRB` | 바이트 단위 연산 | `octet_length()` / `substring(str::bytea from pos for len)` |
| `ASCII / CHR` | 호환이지만 인코딩 차이 주의 | |
| `TRANSLATE` | `TRANSLATE(str, from, to)` | `translate(str, from, to)` 호환 |
| `DUMP` | 디버깅용이지만 일부 쿼리에 포함 | 직접 대응 없음 |

#### P2 -- 분석함수 관련 (보고서/대시보드 쿼리에서 필수)
| 빠진 함수/구문 | 비고 |
|---------------|------|
| `RATIO_TO_REPORT` | `val / SUM(val) OVER()` 로 변환 |
| `PERCENTILE_CONT / PERCENTILE_DISC` | PG도 지원하나 문법 차이 (WITHIN GROUP) |
| `CUME_DIST / PERCENT_RANK` | PG 지원, 문서화 필요 |
| `NTILE` | PG 지원, 호환 |
| `FIRST_VALUE / LAST_VALUE` | PG 지원하나 IGNORE NULLS 미지원 (PG 16 이전) |
| `NTH_VALUE` | PG 지원 |
| `KEEP (DENSE_RANK FIRST/LAST)` | PG 미지원, `DISTINCT ON` 또는 윈도우 서브쿼리로 변환 필요 |
| `LISTAGG WITHIN GROUP ... ON OVERFLOW` (12c R2+) | PG STRING_AGG에는 overflow 처리 없음 |

### 1.3 날짜 포맷 빠진 항목
| Oracle 포맷 | PostgreSQL 대응 | 비고 |
|------------|----------------|------|
| `IW` | `IW` | ISO 주차 |
| `W` | `W` | 월 내 주차 |
| `J` | `J` | 율리우스일 |
| `SSSSS` | `SSSS` | 자정 이후 초수, 이름 차이 |
| `TZH:TZM` | `TZH:TZM` | 타임존 오프셋 |
| `TZR / TZD` | 직접 대응 없음 | Oracle 타임존 약어/리전 |
| `X` (소수점 구분자) | `없음` | 밀리초 앞의 구분자 |
| `FM` (fill mode) | `FM` | 호환이지만 동작 미세 차이 |
| `FX` (exact matching) | `FX` | PG 미지원 |

### 1.4 데이터 타입 빠진 항목
| Oracle | PostgreSQL | 비고 |
|--------|-----------|------|
| `BINARY_FLOAT` | `REAL` | |
| `BINARY_DOUBLE` | `DOUBLE PRECISION` | |
| `INTERVAL YEAR TO MONTH` | `INTERVAL` | PG interval은 통합형 |
| `INTERVAL DAY TO SECOND` | `INTERVAL` | |
| `BFILE` | 대응 없음 (외부 파일) | 구조 재설계 필요 |
| `ROWID / UROWID` | `ctid` (비권장) | 현재 문서에 ROWID 있으나 UROWID 없음 |
| `LONG RAW` | `BYTEA` | LONG만 있고 LONG RAW 없음 |
| `SDO_GEOMETRY` | `geometry` (PostGIS) | GIS 시스템에서 중요 |
| `SYS.ANYDATA` | 대응 없음 | |

---

## 2. CONNECT BY 변환 (connect-by-patterns.md)

**평가: 충분 -- 주요 5개 패턴을 모두 커버하며, 실무 대부분을 처리할 수 있음**

### 2.1 커버된 패턴 (5개)
1. 기본 CONNECT BY / START WITH / LEVEL -- OK
2. NOCYCLE (순환 방지) -- OK, ARRAY path 방식 사용
3. SYS_CONNECT_BY_PATH -- OK
4. CONNECT_BY_ROOT -- OK
5. ORDER SIBLINGS BY -- OK, sort_path 배열 방식

### 2.2 추가로 필요한 패턴/보완 사항

#### P0 -- 실무에서 자주 만나는 변형
| 패턴 | 현황 | 문제 |
|------|------|------|
| **CONNECT_BY_ISLEAF** | **미커버** | 리프 노드 판별. PG에서는 LEFT JOIN 자기 참조로 구현 필요 |
| **다중 CONNECT BY 조건** | **미커버** | `CONNECT BY PRIOR a = b AND c = d` 복수 조건 JOIN |
| **CONNECT BY에 함수 포함** | **미커버** | `CONNECT BY PRIOR UPPER(name) = UPPER(parent_name)` |
| **START WITH 서브쿼리** | **미커버** | `START WITH id IN (SELECT ...)` |
| **CONNECT BY + ROWNUM 조합** | 부분 커버 | complex-query-decomposer에 언급되나 상세 패턴 없음 |
| **PRIOR가 오른쪽에 있는 경우** | **미커버** | `CONNECT BY parent_id = PRIOR id` (일반적) vs `CONNECT BY PRIOR id = parent_id` (현재 예제) |

#### P1 -- 덜 빈번하지만 실무에서 발생
| 패턴 | 설명 |
|------|------|
| **CONNECT BY LEVEL <= N (다른 테이블 기반)** | `CONNECT BY LEVEL <= (SELECT max_depth FROM config)` |
| **CONNECT BY ROWNUM** | `SELECT ROWNUM FROM DUAL CONNECT BY ROWNUM <= 100` (generate_series와 미묘한 차이) |
| **계층 쿼리 + 분석함수** | `SYS_CONNECT_BY_PATH + GROUP BY + HAVING` 조합 |

#### P2 -- NOCYCLE 패턴의 잠재적 문제

현재 NOCYCLE 변환에서 `UNION` (UNION ALL 대신)을 사용하는데, 이는 **의미론적으로 정확하지 않을 수 있다**:

```sql
-- 현재 구현: UNION으로 중복 제거
UNION  -- UNION ALL이 아닌 UNION으로 중복 제거
-- 문제: 같은 노드가 다른 경로로 방문 가능한 DAG에서 결과가 달라짐
-- Oracle NOCYCLE은 동일 경로의 순환만 방지, 다른 경로로의 재방문은 허용
```

**권장**: UNION ALL + path 배열 기반 순환 감지가 Oracle NOCYCLE 의미에 더 가까움. 현재 구현은 path 배열과 UNION 둘 다 사용하고 있어 이중 보호이긴 하나, UNION으로 인한 의도치 않은 행 누락 가능성 있음.

---

## 3. ROWNUM 페이징 (rownum-pagination-patterns.md)

**평가: 충분 -- 7개 패턴이 실무 페이징의 90% 이상을 커버**

### 3.1 커버된 패턴 (7개)
1. 단순 ROWNUM 제한 -- OK
2. 2중 서브쿼리 페이징 -- OK
3. 3중 서브쿼리 페이징 (가장 일반적) -- OK
4. 3중 페이징 + 동적 SQL -- OK (핵심 패턴, 잘 설계됨)
5. ROW_NUMBER() OVER() 사용 패턴 -- OK
6. ROWNUM = 1 단일 행 -- OK
7. ROWNUM in UPDATE/DELETE -- OK

### 3.2 빠진/보완 필요 패턴

#### P0
| 패턴 | 설명 | 예시 |
|------|------|------|
| **ROWNUM in INSERT ... SELECT** | 배치 INSERT에서 ROWNUM 사용 | `INSERT INTO target SELECT * FROM source WHERE ROWNUM <= 1000` |
| **ROWNUM as column alias 재사용** | rn을 이후 조건에서 재사용 | `WHERE rn BETWEEN #{start} AND #{end}` (BETWEEN 패턴) |
| **FETCH FIRST N ROWS ONLY (12c+)** | 현대적 Oracle 페이징 | `ORDER BY id FETCH FIRST 10 ROWS ONLY` → `LIMIT 10` |
| **OFFSET N ROWS FETCH NEXT M ROWS ONLY (12c+)** | Oracle 12c 네이티브 페이징 | 직접 LIMIT/OFFSET 대응 |
| **ROWNUM + UNION ALL 조합** | | `SELECT ... UNION ALL SELECT ... WHERE ROWNUM <= N` |

#### P1
| 패턴 | 설명 |
|------|------|
| **keyset pagination (커서 기반)** | `WHERE id > #{lastId} AND ROWNUM <= 10` -- LIMIT만으로 충분하지만 패턴 인식 필요 |
| **ROWNUM in HAVING** | `HAVING ROWNUM <= N` -- 매우 드물지만 존재 |
| **ORA_ROWSCN** | 행 단위 SCN, PG 대응 없음 (xmin으로 부분 대체) |

### 3.3 ROWNUM + ORDER BY 순서 경고

현재 문서에 이 경고가 포함되어 있어 좋다:
```sql
-- Oracle: WHERE ROWNUM <= 10 ORDER BY name → 먼저 10행 → 정렬
-- PostgreSQL: ORDER BY name LIMIT 10 → 정렬 후 10행
```
이 차이는 실무에서 매우 빈번하게 버그를 유발하므로, **자동 감지 + 경고**가 중요하다.

---

## 4. 복합 쿼리 분해 (complex-query-decomposer)

**평가: 부분적 -- Inside-Out 전략의 설계는 좋으나, 실전 L4 시나리오에서 한계가 있음**

### 4.1 잘 설계된 부분
- 4개 분해 패턴 (ROWNUM 페이징, 인라인 CONNECT BY, 동적 SQL 분기, 복합 중첩)
- Inside-Out 전략 (안쪽부터 변환)
- transform-plan.json 산출물 구조
- 동적 SQL 태그 보존 원칙

### 4.2 실전에서 문제가 될 시나리오

#### 시나리오 A: ROWNUM + CONNECT BY + 동적SQL + 서브쿼리 + (+) 조인
```xml
<select id="nightmare">
  SELECT * FROM (
    SELECT a.*, ROWNUM rn FROM (
      SELECT u.id, u.name,
             NVL(d.dept_name, 'N/A') AS dept_name,
             (SELECT LISTAGG(r.role_name, ',') WITHIN GROUP (ORDER BY r.role_name)
              FROM user_roles ur, roles r
              WHERE ur.user_id = u.id AND ur.role_id = r.id(+)) AS role_names
      FROM users u, departments d
      WHERE u.dept_id = d.id(+)
      <if test="orgId != null">
        AND u.org_id IN (
          SELECT org_id FROM org_tree
          START WITH org_id = #{orgId}
          CONNECT BY PRIOR org_id = parent_id
        )
      </if>
      <choose>
        <when test="sortType == 'name'">ORDER BY u.name</when>
        <when test="sortType == 'date'">ORDER BY u.created_at DESC</when>
        <otherwise>ORDER BY u.id</otherwise>
      </choose>
    ) a WHERE ROWNUM &lt;= #{pageEnd}
  ) WHERE rn > #{pageStart}
</select>
```

**현재 분해기의 문제점**:
1. 인라인 스칼라 서브쿼리 내 `(+)` 조인 + LISTAGG는 Step 2 (RULE_CONVERT_BRANCHES)에서 처리해야 하는데, 스칼라 서브쿼리 자체가 (+) 조인을 포함하는 구조적 변환이 필요
2. `<if>` 분기 안에 있는 CONNECT BY 서브쿼리는 CTE로 추출 시 `<if>` 태그 바깥으로 나가야 하는데, 동적 SQL 태그 보존 원칙과 충돌
3. CONNECT BY가 조건부(if 안)인 경우, CTE를 항상 생성하면 불필요한 성능 저하, 생성하지 않으면 조건 미충족 시 SQL 에러

**현재 설계에서 이 문제를 해결하는 명확한 지침이 없다.**

#### 시나리오 B: 다중 CTE가 필요한 복합 쿼리
```sql
SELECT u.*, 
       org.path,
       (SELECT COUNT(*) FROM audit_log a 
        WHERE a.user_id = u.id 
        AND a.log_date >= ADD_MONTHS(SYSDATE, -6)) AS recent_actions
FROM users u
LEFT JOIN (
    SELECT org_id, SYS_CONNECT_BY_PATH(org_name, '/') AS path
    FROM org_tree
    START WITH parent_id IS NULL
    CONNECT BY PRIOR org_id = parent_id
) org ON u.org_id = org.org_id
WHERE u.dept_id IN (
    SELECT dept_id FROM dept_tree
    START WITH dept_id = #{rootDeptId}
    CONNECT BY PRIOR dept_id = parent_dept_id
)
```

**문제**: 두 개의 독립적인 CONNECT BY가 있을 때, 분해기가 두 개의 WITH RECURSIVE CTE를 올바르게 생성하고 조합할 수 있는지 명시되어 있지 않다.

#### 시나리오 C: `<foreach>` 안에 복잡한 Oracle 구문
```xml
<foreach collection="queries" item="q" separator="UNION ALL">
  SELECT #{q.id} AS query_id,
         NVL(
           (SELECT LISTAGG(col_name, ',') WITHIN GROUP (ORDER BY col_name)
            FROM all_tab_columns
            WHERE table_name = #{q.tableName}),
           'NO_COLUMNS'
         ) AS columns
  FROM DUAL
</foreach>
```

**문제**: `<foreach>`가 런타임에 전개되므로, 내부 SQL을 정적으로 분석할 때 반복 횟수를 알 수 없다. 분해기는 이 경우를 다루는 패턴이 없다.

### 4.3 개선 권장사항
1. **조건부 CTE 패턴** 추가 -- `<if>` 안의 CONNECT BY를 CTE로 변환할 때의 전략
2. **다중 CTE 조합** 패턴 추가 -- 같은 쿼리에 여러 CONNECT BY가 있는 경우
3. **스칼라 서브쿼리 내 구조적 변환** 패턴 추가
4. **`<foreach>` 내 복합 구문** 처리 지침 추가

---

## 5. 동적 SQL + Oracle 구문 조합

**평가: 부분적 -- 기본적인 분기별 변환은 설계되어 있으나, 엣지케이스가 많음**

### 5.1 잘 설계된 부분
- rule-convert가 `<if>`, `<choose>`, `<foreach>` 내부를 각각 변환
- complex-query-decomposer Pattern 3이 분기별 복잡도 분류
- Converter가 분기별 독립 변환 원칙을 명시

### 5.2 문제 시나리오

#### 문제 1: 동적 SQL이 SQL 구조를 변경하는 경우
```xml
<select id="dynamicJoin">
  SELECT u.id, u.name
  FROM users u
  <if test="includeDept == true">
    , departments d
  </if>
  WHERE 1=1
  <if test="includeDept == true">
    AND u.dept_id = d.id(+)
  </if>
</select>
```
`(+)` 조인을 ANSI JOIN으로 변환하려면 FROM 절과 WHERE 절을 동시에 수정해야 하는데, 두 `<if>` 블록이 분리되어 있다. 단순 텍스트 치환으로는 처리 불가.

#### 문제 2: `${}`(dollar substitution) 안에 숨은 Oracle 구문
```xml
<select id="dynamicTable">
  SELECT * FROM ${schemaName}.${tableName}
  WHERE ROWNUM &lt;= 100
</select>
```
`${schemaName}` 내에 Oracle 스키마 참조가 있을 수 있으나 정적 분석 불가. 현재 parse-xml이 `dollar_substitution` 플래그를 추가하고 WARNING을 남기는 것은 좋으나, **변환 전략이 없다**.

#### 문제 3: `<bind>` 변수가 Oracle 함수를 사용하는 경우
```xml
<bind name="today" value="SYSDATE"/>  <!-- Java에서 평가되므로 문제없을 수 있으나... -->
<bind name="pattern" value="'%' + name + '%'"/>
<if test="startDate != null">
  AND created_at >= TO_DATE(#{startDate}, 'YYYYMMDD')
</if>
```
`<bind>`의 value 속성은 OGNL 표현식이므로 SQL이 아니다. 그러나 일부 개발자가 SQL 함수를 `<bind>`에 넣는 실수를 하는 경우가 있다. 현재 이에 대한 감지/경고가 없다.

#### 문제 4: 중첩 동적 SQL에서 Oracle 구문이 부분적으로만 존재
```xml
<trim prefix="WHERE" prefixOverrides="AND">
  <if test="status != null">
    AND status = DECODE(#{statusType}, 'CODE', #{status}, 
                        'NAME', (SELECT code FROM status_master WHERE name = #{status}), 
                        #{status})
  </if>
  <foreach collection="filters" item="f">
    AND ${f.column} ${f.operator} #{f.value}
  </foreach>
</trim>
```
`<foreach>` 내의 `${f.column}`과 `${f.operator}`는 런타임 값이므로 Oracle 구문이 동적으로 주입될 수 있다.

### 5.3 권장사항
1. **구조적 변환이 필요한 동적 SQL** 패턴 카탈로그 추가 (FROM/WHERE 분리된 (+) 조인 등)
2. **`${}`로 인한 미검출 Oracle 구문** 경고를 migration-guide에 구체적으로 기록
3. **`<bind>` 속성 내 SQL 함수 감지** 추가

---

## 6. 빠진 Oracle 패턴

**평가: 부족 -- 실제 마이그레이션에서 문제가 되는 주요 패턴이 상당수 누락**

### 6.1 DBMS_* 패키지 (가장 큰 갭)

운영 시스템에서 MyBatis XML 통해 호출되는 DBMS 패키지:

| 패키지 | 용도 | 빈도 | 현재 커버 |
|--------|------|------|----------|
| `DBMS_LOB` | LOB 조작 (SUBSTR, GETLENGTH, APPEND) | 매우 높음 | 미커버 |
| `DBMS_OUTPUT` | 디버깅 출력 | 높음 | 미커버 |
| `DBMS_SQL` | 동적 SQL 실행 | 중간 | 미커버 |
| `DBMS_CRYPTO` | 암호화/해시 | 중간 | 미커버 |
| `DBMS_RANDOM` | 난수 생성 | 중간 | 미커버 |
| `DBMS_LOCK` | 잠금 관리 | 낮음 | 미커버 |
| `DBMS_JOB / DBMS_SCHEDULER` | 작업 스케줄링 | 중간 | 미커버 |
| `DBMS_XMLGEN` | XML 생성 | 중간 | 미커버 |
| `DBMS_UTILITY` | 유틸리티 (COMMA_TO_TABLE 등) | 중간 | 미커버 |

**PostgreSQL 대응 예시**:
```sql
-- Oracle: DBMS_LOB.SUBSTR(clob_col, 4000, 1)
-- PostgreSQL: SUBSTRING(text_col FROM 1 FOR 4000)

-- Oracle: DBMS_LOB.GETLENGTH(clob_col)
-- PostgreSQL: LENGTH(text_col)  -- 또는 octet_length()

-- Oracle: DBMS_CRYPTO.HASH(input, DBMS_CRYPTO.HASH_SH256)
-- PostgreSQL: digest(input, 'sha256')  -- pgcrypto 확장 필요

-- Oracle: DBMS_RANDOM.VALUE(1, 100)
-- PostgreSQL: floor(random() * 100 + 1)
```

### 6.2 UTL_* 유틸리티

| 패키지 | 용도 | PostgreSQL 대응 |
|--------|------|----------------|
| `UTL_RAW` | RAW 데이터 조작 | `encode()`/`decode()` |
| `UTL_HTTP` | HTTP 호출 | `http` 확장 또는 외부 처리 |
| `UTL_FILE` | 파일 I/O | `pg_read_file()` (제한적) |
| `UTL_MAIL` | 메일 발송 | 외부 처리 필요 |
| `UTL_ENCODE` | Base64 등 인코딩 | `encode(data, 'base64')` |

### 6.3 Oracle 정규식 (Section 1에서 이미 언급)

REGEXP_LIKE, REGEXP_SUBSTR, REGEXP_REPLACE, REGEXP_INSTR, REGEXP_COUNT -- 모두 미커버.
이들은 검색/유효성 검사 쿼리에서 **매우 빈번**하게 사용됨.

### 6.4 XMLTABLE / XML 관련

```sql
-- 실무에서 자주 보는 패턴
SELECT x.name, x.value
FROM xml_data d,
     XMLTABLE('/root/item' PASSING d.xml_content
       COLUMNS
         name  VARCHAR2(100) PATH 'name',
         value NUMBER        PATH 'value'
     ) x
```
현재 llm-convert가 "XMLTYPE 조작"을 "llm" 태그로 분류하지만, 구체적인 변환 패턴이 없다.

### 6.5 MODEL 절

```sql
SELECT product, year, sales
FROM sales_data
MODEL
  PARTITION BY (product)
  DIMENSION BY (year)
  MEASURES (amount AS sales)
  RULES (
    sales[2026] = sales[2025] * 1.1
  )
```
MODEL 절은 PostgreSQL에 직접 대응이 없으며, LATERAL JOIN + 윈도우 함수로 재작성 필요.
빈도는 낮지만, 사용하는 시스템에서는 핵심 로직에 포함됨.

### 6.6 기타 빠진 중요 패턴

| 패턴 | 설명 | 빈도 |
|------|------|------|
| **Global Temporary Table (GTT)** | `ON COMMIT DELETE/PRESERVE ROWS` | 높음 |
| **Materialized View** | `CREATE MATERIALIZED VIEW ... REFRESH` | 중간 |
| **DB Link** | `SELECT * FROM table@dblink` | 중간 |
| **Oracle 시노님** | `SELECT * FROM synonym_name` | 높음 |
| **FLASHBACK 쿼리** | `AS OF TIMESTAMP` | 낮음 |
| **Analytic: KEEP (DENSE_RANK)** | `MAX(col) KEEP (DENSE_RANK FIRST ORDER BY ...)` | 중간 |
| **RETURNING 절** | `INSERT ... RETURNING id INTO :var` | 중간 |
| **BULK COLLECT** | PL/SQL 배치 처리 | 중간 |
| **TABLE() 함수 (컬렉션 테이블화)** | `SELECT * FROM TABLE(fn_get_list())` | 중간 |
| **PIPELINED 함수** | `SELECT * FROM TABLE(PIPELINED_FN())` | 중간 |
| **AUTONOMOUS_TRANSACTION** | 독립 트랜잭션 | 낮음 |
| **Oracle 힌트 세부 변환** | `/*+ PARALLEL(4) */` 등 힌트별 대응 | 중간 |

---

## 7. 테스트 fixture 충분성

**평가: 부족 -- 3개 fixture는 스모크 테스트 수준이며, 실제 운영 쿼리 복잡도를 대표하지 못함**

### 7.1 현재 fixture 커버리지

| fixture | 쿼리 수 | 커버하는 패턴 | 복잡도 |
|---------|---------|-------------|--------|
| mybatis3-basic.xml | ~10 | NVL, SYSDATE, ROWNUM, DECODE, (+), selectKey, if/where/choose/foreach/set | L0~L2 |
| mybatis3-complex.xml | 6 | CONNECT BY NOCYCLE, SYS_CONNECT_BY_PATH, ORDER SIBLINGS, MERGE INTO, LISTAGG, ROWNUM 페이징, hints, NVL2, TO_CHAR, ADD_MONTHS | L2~L4 |
| ibatis2-sample.xml | 4 | isNotNull, isNotEmpty, isEqual, isGreaterThan, iterate, selectKey, procedure, #prop# | L1~L2 |

**총 ~20개 쿼리, 최대 복잡도 L4 (단일 패턴)**

### 7.2 빠진 fixture 시나리오

#### 필수 추가해야 할 fixture:

1. **L4 복합 쿼리 fixture** (mybatis3-nightmare.xml)
   - ROWNUM 3중 페이징 + 내부 CONNECT BY + 동적 SQL + 스칼라 서브쿼리 + (+) 조인
   - 위 Section 4.2의 시나리오 A에 해당

2. **정규식 fixture** (mybatis3-regex.xml)
   - REGEXP_LIKE, REGEXP_SUBSTR, REGEXP_REPLACE 사용 쿼리

3. **LOB 처리 fixture** (mybatis3-lob.xml)
   - DBMS_LOB.SUBSTR, CLOB INSERT/UPDATE, jdbcType=CLOB 파라미터

4. **분석함수 fixture** (mybatis3-analytics.xml)
   - KEEP DENSE_RANK, RATIO_TO_REPORT, LISTAGG + OVER (12c), FIRST_VALUE IGNORE NULLS

5. **MERGE INTO 복합 fixture**
   - MERGE + DELETE 절 + 조건부 UPDATE + 서브쿼리 USING

6. **크로스 파일 의존성 fixture** (2개 이상의 XML)
   - association select, collection select로 다른 namespace 참조

7. **iBatis 2.x 복합 fixture**
   - 중첩 dynamic + isNull/isNotNull + iterate + CONNECT BY

8. **빈 문자열/NULL 시멘틱스 fixture**
   - Oracle '' = NULL 동작 차이가 결과에 영향을 주는 쿼리

9. **12c+ 문법 fixture**
   - FETCH FIRST N ROWS ONLY, OFFSET, IDENTITY COLUMN, JSON_TABLE

10. **대량 동적 SQL fixture**
    - 20+ 개의 `<if>` 분기, 5+ 개의 `<choose>`, 중첩 `<foreach>`

### 7.3 현재 fixture의 강점
- MyBatis 3.x / iBatis 2.x 둘 다 커버
- 기본적인 태그 인식 테스트로는 충분
- 커버하는 패턴은 정확하게 문서화되어 있음 (fixtures/README.md)

---

## 8. jdbcType 매핑 (param-type-convert)

**평가: 충분 -- 주요 매핑은 정확하며, 실무에서 가장 빈번한 변환을 커버**

### 8.1 현재 매핑 정확성 검증

| 매핑 | 정확성 | 비고 |
|------|--------|------|
| BLOB → BINARY | 정확 | PG BYTEA에 대응 |
| CLOB/NCLOB → VARCHAR | 정확 | PG TEXT에 대응, MyBatis에서는 VARCHAR 사용 |
| CURSOR → OTHER | 정확 | PG refcursor에 대응 |
| NUMBER → NUMERIC | 정확 | |
| FLOAT → DOUBLE | 정확 | |
| DATE → TIMESTAMP | 정확 | Oracle DATE = 날짜+시간 |
| RAW → BINARY | 정확 | PG BYTEA에 대응 |
| STRUCT → OTHER | 정확 | PG composite type |

### 8.2 빠진 타입 매핑

| Oracle jdbcType | PostgreSQL jdbcType | 빈도 | 설명 |
|-----------------|--------------------|----|------|
| `NCHAR` | `CHAR` | 낮음 | 유니코드 CHAR |
| `NVARCHAR` | `VARCHAR` | 중간 | 유니코드 VARCHAR |
| `LONGVARCHAR` | `VARCHAR` | 낮음 | LONG → TEXT |
| `LONGVARBINARY` | `BINARY` | 낮음 | LONG RAW → BYTEA |
| `JAVA_OBJECT` | `OTHER` | 낮음 | 사용자 정의 객체 |
| `DISTINCT` | `DISTINCT` | 매우 낮음 | 사용자 정의 타입 |
| `REF` | `OTHER` | 매우 낮음 | REF CURSOR 변형 |
| `DATALINK` | 미지원 | 매우 낮음 | URL 참조 |
| `ROWID` | `OTHER` | 낮음 | Oracle ROWID 타입 |
| `TIME` | `TIME` | 낮음 | Oracle에는 TIME 타입 없지만 jdbcType으로 올 수 있음 |
| `TIME_WITH_TIMEZONE` | `TIME_WITH_TIMEZONE` | 낮음 | |
| `TIMESTAMP_WITH_TIMEZONE` | `TIMESTAMP_WITH_TIMEZONE` | 중간 | |

### 8.3 잠재적 문제

#### DATE → TIMESTAMP 변환의 조건부 처리

현재 문서에 "순수 날짜만 사용하는 경우는 DATE 유지 가능 -- 컨텍스트에 따라 판단"이라고 되어 있으나, **자동으로 이 판단을 내리는 로직이 없다**. 모든 Oracle DATE를 TIMESTAMP으로 변환하면:

```sql
-- Oracle: WHERE created_date = TO_DATE('2024-01-01', 'YYYY-MM-DD')
-- PG (무조건 TIMESTAMP 변환 시): WHERE created_date = '2024-01-01 00:00:00'
-- 문제: 인덱스 사용 여부, 시간 부분 포함 여부에 따라 결과 차이
```

#### Oracle TypeHandler 경고 범위

현재 4가지 패턴만 감지:
- OracleXmlTypeHandler
- OracleBlobTypeHandler
- OracleArrayTypeHandler
- OracleStructTypeHandler

**빠진 패턴**:
- OracleClobTypeHandler
- OracleTimestampTypeHandler
- OracleIntervalTypeHandler
- `oracle.sql.*` 패키지의 모든 TypeHandler
- 회사 내부 Oracle 전용 TypeHandler (패턴 `*Oracle*TypeHandler*`)

---

## 9. 종합 평가 및 개선 권장사항

### 9.1 종합 점수

| 항목 | 평가 | 점수 (10점) | 실제 커버리지 추정 |
|------|------|------------|------------------|
| Oracle 함수 커버리지 | 부분적 | 6/10 | ~60% (핵심 함수는 있으나 정규식/LOB/분석함수 부재) |
| CONNECT BY 변환 | 충분 | 8/10 | ~85% (주요 5패턴 커버, CONNECT_BY_ISLEAF 등 미커버) |
| ROWNUM 페이징 | 충분 | 8/10 | ~90% (7패턴, 12c 문법 미커버) |
| 복합 쿼리 분해 | 부분적 | 7/10 | 설계 우수, 실전 엣지케이스 보완 필요 |
| 동적 SQL + Oracle 조합 | 부분적 | 6/10 | 기본은 되나 구조적 변환 시 한계 |
| 빠진 Oracle 패턴 | 부족 | 4/10 | DBMS_*/UTL_*/정규식/XML 등 대규모 미커버 |
| 테스트 fixture | 부족 | 4/10 | 스모크 테스트 수준, L4 복합 시나리오 없음 |
| jdbcType 매핑 | 충분 | 8/10 | 주요 매핑 정확, 부가 타입 소수 누락 |

**종합: 6.4/10 -- 단순~중급 운영 시스템 마이그레이션에는 적합, 복잡한 엔터프라이즈 시스템에는 보강 필요**

### 9.2 우선순위별 개선 권장사항

#### 즉시 (Sprint 1) -- 가장 큰 영향

1. **oracle-pg-rules.md에 정규식 함수 5종 추가**
   - REGEXP_LIKE, REGEXP_SUBSTR, REGEXP_REPLACE, REGEXP_INSTR, REGEXP_COUNT
   - 실무 영향: 매우 높음, 거의 모든 검색/유효성 로직에서 사용

2. **oracle-pg-rules.md에 GREATEST/LEAST NULL 처리 차이 추가**
   ```sql
   -- Oracle: GREATEST(NULL, 1, 2) = 2 (NULL 무시)
   -- PG: GREATEST(NULL, 1, 2) = NULL (하나라도 NULL이면 NULL)
   -- 변환: GREATEST(COALESCE(a,0), COALESCE(b,0), COALESCE(c,0))
   ```

3. **L4 복합 fixture 추가** (mybatis3-nightmare.xml)
   - ROWNUM + CONNECT BY + 동적 SQL + (+) 조인 + 스칼라 서브쿼리

4. **CONNECT_BY_ISLEAF 패턴 추가** (connect-by-patterns.md)
   ```sql
   -- Oracle: CONNECT_BY_ISLEAF
   -- PostgreSQL: NOT EXISTS (SELECT 1 FROM table WHERE parent = current.id)
   ```

#### 단기 (Sprint 2-3)

5. **DBMS_LOB 기본 함수 매핑 추가** (oracle-pg-rules.md)
   - DBMS_LOB.SUBSTR → SUBSTRING
   - DBMS_LOB.GETLENGTH → LENGTH
   - DBMS_LOB.INSTR → POSITION

6. **분석함수 KEEP (DENSE_RANK FIRST/LAST) 패턴 추가** (llm-convert references)
   ```sql
   -- Oracle
   SELECT dept_id, 
          MAX(salary) KEEP (DENSE_RANK FIRST ORDER BY hire_date) AS first_hire_salary
   FROM employees GROUP BY dept_id
   -- PostgreSQL
   SELECT DISTINCT ON (dept_id) dept_id, salary AS first_hire_salary
   FROM employees ORDER BY dept_id, hire_date
   ```

7. **WM_CONCAT → STRING_AGG 룰 추가**

8. **FETCH FIRST N ROWS ONLY (12c+) 패턴 추가** (rownum-pagination-patterns.md)

9. **조건부 CTE 전략 문서화** (complex-query-decomposer)
   - `<if>` 안의 CONNECT BY를 어떻게 처리할 것인가

10. **추가 fixture 4개 이상 작성**
    - 정규식, LOB, 분석함수, 크로스 파일

#### 중기 (Sprint 4-6)

11. **DBMS_* 패키지 변환 카탈로그 작성** (신규 reference 파일)
    - DBMS_LOB, DBMS_CRYPTO, DBMS_RANDOM, DBMS_OUTPUT, DBMS_UTILITY

12. **XMLTABLE 변환 패턴 추가** (llm-convert references)

13. **Global Temporary Table 변환 가이드 추가**
    - Oracle GTT → PG UNLOGGED TABLE 또는 TEMPORARY TABLE

14. **RETURNING 절 변환 패턴 추가**
    ```sql
    -- Oracle MyBatis: INSERT ... RETURNING id INTO #{id}
    -- PostgreSQL MyBatis: INSERT ... RETURNING id (selectKey 방식으로 변환)
    ```

15. **구조적 동적 SQL 변환** 패턴 문서화
    - FROM/WHERE 분리된 (+) 조인의 ANSI JOIN 변환

16. **TABLE() / PIPELINED 함수 변환 패턴 추가**

#### 장기 (Sprint 7+)

17. **MODEL 절 변환 가이드** (수동 변환 필요, 패턴 참조 문서)
18. **DB Link 변환 가이드** (postgres_fdw 등)
19. **Oracle 시노님 → PG search_path/schema 매핑**
20. **성능 비교 프레임워크** (Oracle hints 제거 후 PG 성능 검증)

---

## 부록: 실제 운영에서 문제될 시나리오 (예시 SQL)

### A. 정규식이 포함된 검색 쿼리 (현재 변환 불가)
```sql
-- Oracle
SELECT id, name, email 
FROM users 
WHERE REGEXP_LIKE(email, '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
  AND REGEXP_SUBSTR(phone, '\d{3}', 1, 1) = '010'

-- 필요한 PostgreSQL 변환
SELECT id, name, email 
FROM users 
WHERE email ~ '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
  AND (regexp_matches(phone, '\d{3}'))[1] = '010'
```

### B. DBMS_LOB + CLOB 처리 (현재 변환 불가)
```sql
-- Oracle
SELECT id, 
       DBMS_LOB.SUBSTR(content, 200, 1) AS preview,
       DBMS_LOB.GETLENGTH(content) AS content_len
FROM articles 
WHERE DBMS_LOB.INSTR(content, #{keyword}) > 0

-- 필요한 PostgreSQL 변환
SELECT id, 
       SUBSTRING(content FROM 1 FOR 200) AS preview,
       LENGTH(content) AS content_len
FROM articles 
WHERE POSITION(#{keyword} IN content) > 0
```

### C. KEEP DENSE_RANK (현재 변환 불가)
```sql
-- Oracle
SELECT dept_id,
       MIN(salary) KEEP (DENSE_RANK FIRST ORDER BY hire_date) AS earliest_salary,
       MAX(salary) KEEP (DENSE_RANK LAST ORDER BY hire_date) AS latest_salary
FROM employees
GROUP BY dept_id

-- 필요한 PostgreSQL 변환 (서브쿼리 방식)
SELECT dept_id,
       (SELECT salary FROM employees e2 
        WHERE e2.dept_id = e1.dept_id 
        ORDER BY hire_date ASC LIMIT 1) AS earliest_salary,
       (SELECT salary FROM employees e2 
        WHERE e2.dept_id = e1.dept_id 
        ORDER BY hire_date DESC LIMIT 1) AS latest_salary
FROM employees e1
GROUP BY dept_id
```

### D. 다중 CONNECT BY + 동적 SQL (현재 분해 전략 불명확)
```xml
<select id="orgUserReport">
  SELECT u.name, org.path, dept.name AS dept_name
  FROM users u
  LEFT JOIN (
    SELECT org_id, SYS_CONNECT_BY_PATH(org_name, ' > ') AS path
    FROM org_tree START WITH parent_id IS NULL
    CONNECT BY PRIOR org_id = parent_id
  ) org ON u.org_id = org.org_id
  LEFT JOIN (
    SELECT dept_id, CONNECT_BY_ROOT dept_name AS root_dept
    FROM dept_tree START WITH parent_dept_id IS NULL
    CONNECT BY PRIOR dept_id = parent_dept_id
  ) dept ON u.dept_id = dept.dept_id
  <where>
    <if test="orgId != null">
      AND u.org_id IN (
        SELECT org_id FROM org_tree
        START WITH org_id = #{orgId}
        CONNECT BY PRIOR org_id = parent_id
      )
    </if>
  </where>
</select>
```
이 쿼리에는 **3개의 독립적인 CONNECT BY**가 있으며, 하나는 `<if>` 조건부이다. 현재 분해기가 이를 올바르게 3개의 WITH RECURSIVE CTE로 변환하고 조합할 수 있는 명시적 지침이 없다.

### E. Oracle '' = NULL 시멘틱스가 결과를 바꾸는 경우
```sql
-- Oracle ('' = NULL이므로 이 조건은 name이 NULL인 행도 반환)
SELECT * FROM users WHERE NVL(name, '') = ''
-- Oracle 결과: name IS NULL인 행들

-- PostgreSQL ('' != NULL이므로 결과가 달라짐)
SELECT * FROM users WHERE COALESCE(name, '') = ''
-- PostgreSQL 결과: name = '' 또는 name IS NULL인 행들 (빈 문자열 행도 포함)
```
이 미묘한 차이가 현재 oracle-pg-rules.md의 "빈 문자열 = NULL" 섹션에 언급되어 있지만, **자동 감지 및 변환 전략이 구체적이지 않다**.

---

## 총평

이 Kiro 에이전트 시스템은 **아키텍처적으로 매우 잘 설계**되어 있다. 6-Phase 파이프라인, Inside-Out 분해 전략, 레이어별 변환, Result Integrity Guard, 자동 학습 루프 등의 설계는 엔터프라이즈 마이그레이션 도구로서 높은 수준이다.

그러나 **Oracle SQL 커버리지의 깊이**에서 보강이 필요하다. 현재 상태로는 NVL/DECODE/SYSDATE/ROWNUM/CONNECT BY/MERGE INTO 중심의 "전형적인 OLTP 쿼리"를 잘 처리할 수 있지만, 정규식, LOB 처리, 분석함수 고급 패턴, DBMS_* 패키지 등이 포함된 "실제 10년 이상 운영된 엔터프라이즈 시스템"에서는 상당수 쿼리가 LLM 자유 변환(confidence: low)이나 수동 에스컬레이션으로 빠질 것으로 예상된다.

**우선적으로 정규식 함수 5종, GREATEST/LEAST NULL 처리, CONNECT_BY_ISLEAF, DBMS_LOB 기본 함수 4종만 추가해도 커버리지가 크게 향상**될 것이다.

테스트 fixture는 현재 스모크 테스트 수준이므로, 실제 운영 쿼리 수준의 L4 복합 fixture를 반드시 추가해야 분해기와 변환기의 실전 대응력을 검증할 수 있다.
