# Part 2: Skills

## Task 3: parse-xml 스킬

**Files:**
- Create: `.kiro/skills/parse-xml/SKILL.md`
- Create: `.kiro/skills/parse-xml/references/mybatis-ibatis-tag-reference.md`
- Create: `.kiro/skills/parse-xml/assets/parsed-template.json`

- [ ] **Step 1: SKILL.md 생성**

Create: `.kiro/skills/parse-xml/SKILL.md`

```markdown
---
name: parse-xml
description: MyBatis 또는 iBatis XML 파일을 파싱하여 SQL 쿼리를 추출한다. mapper namespace, 쿼리 ID, SQL 타입(select/insert/update/delete), 동적 SQL 요소(if/choose/foreach 등), 파라미터 매핑을 식별한다.
---

## 입력
- XML 파일 경로 (단일 또는 glob 패턴)

## 처리 절차

1. XML 루트 태그로 프레임워크 판별:
   - `<mapper namespace="...">` → MyBatis 3.x (28개 태그 대상)
   - `<sqlMap namespace="...">` → iBatis 2.x (35개+ 태그 대상)
   - references/mybatis-ibatis-tag-reference.md §7 체크리스트 기준으로 전수 파싱

2. 각 쿼리 노드 추출:
   - MyBatis: `<select>`, `<insert>`, `<update>`, `<delete>`
   - iBatis: 위 + `<statement>`, `<procedure>`

3. 동적 SQL 요소 식별 및 구조화:
   - MyBatis: `<if>`, `<choose>/<when>/<otherwise>`, `<where>`, `<set>`, `<trim>`, `<foreach>`, `<bind>`
   - iBatis: `<dynamic>`, `<isNull>`, `<isNotNull>`, `<isEmpty>`, `<isNotEmpty>`, `<isEqual>`, `<isNotEqual>`, `<isGreaterThan>`, `<isGreaterEqual>`, `<isLessThan>`, `<isLessEqual>`, `<isPropertyAvailable>`, `<isNotPropertyAvailable>`, `<isParameterPresent>`, `<isNotParameterPresent>`, `<iterate>`

4. `<include refid="...">` 처리:
   - 같은 XML 내 `<sql id="...">` 를 찾아 인라인 전개
   - 여러 XML 간 cross-reference가 있으면 참조 관계만 기록 (전개하지 않음)
   - MyBatis 3.x의 `<include>` 내부 `<property>` 오버라이드 처리

5. 파라미터 매핑 추출:
   - MyBatis: `#{param}`, `#{param,jdbcType=VARCHAR}`, `${param}`
   - iBatis: `#param#`, `#param:VARCHAR#`, `$param$`
   - 자동 판별하여 통일된 형식으로 기록

6. Oracle 특유 구문 태깅:
   - 단순 패턴 → "rule" 태그:
     - NVL, NVL2, DECODE, SYSDATE, SYSTIMESTAMP
     - ROWNUM, sequence.NEXTVAL/CURRVAL
     - (+) 아우터 조인, FROM DUAL
     - TO_DATE/TO_CHAR 포맷 차이, LISTAGG, MINUS
   - 복잡 패턴 → "llm" 태그:
     - CONNECT BY / START WITH (계층 쿼리)
     - MERGE INTO
     - PIVOT / UNPIVOT
     - PL/SQL 프로시저/패키지 호출
     - Oracle 힌트 (/*+ ... */)
     - XMLTYPE 조작

7. `<selectKey>` 내부 Oracle 시퀀스 패턴 감지:
   - `SELECT SEQ.NEXTVAL FROM DUAL` → "rule" 태그

8. 결과를 `workspace/results/{filename}/v1/parsed.json` 으로 기록
   - assets/parsed-template.json 형식 참조

## 주의사항
- 동적 SQL은 가능한 모든 분기의 SQL을 추출
- iBatis `<iterate>` 내부의 `#list[]#` 표기도 파라미터로 추출
- resultMap, parameterMap 정의는 파싱하되 SQL 변환 대상은 아님 (구조 참조용)
- `<cache>`, `<cache-ref>` 등 비SQL 태그는 메타데이터로 기록
```

- [ ] **Step 2: mybatis-ibatis-tag-reference.md 생성**

Create: `.kiro/skills/parse-xml/references/mybatis-ibatis-tag-reference.md`

> 이 파일은 사용자가 제공한 "MyBatis 3.x / iBatis 2.x XML 태그 완전 레퍼런스" 문서의 전체 내용을 그대로 사용한다. 브레인스토밍 과정에서 사용자가 제공한 원본을 복사하여 배치.

- [ ] **Step 3: parsed-template.json 생성**

Create: `.kiro/skills/parse-xml/assets/parsed-template.json`

```json
{
  "version": 1,
  "source_file": "UserMapper.xml",
  "framework": "mybatis3",
  "namespace": "com.example.mapper.UserMapper",
  "sql_fragments": [
    {
      "id": "commonColumns",
      "sql": "id, name, email, created_at"
    }
  ],
  "queries": [
    {
      "query_id": "selectUserById",
      "type": "select",
      "parameter_type": "int",
      "result_type": "com.example.model.User",
      "result_map": null,
      "statement_type": "PREPARED",
      "sql_raw": "SELECT id, name, email FROM users WHERE id = #{id} AND status = NVL(#{status}, 'ACTIVE')",
      "sql_branches": [
        {
          "condition": "always",
          "sql": "SELECT id, name, email FROM users WHERE id = ? AND status = NVL(?, 'ACTIVE')"
        }
      ],
      "dynamic_elements": [
        {
          "tag": "if",
          "test": "name != null",
          "content": "AND name = #{name}"
        }
      ],
      "parameters": [
        {
          "name": "id",
          "jdbc_type": null,
          "notation": "#{}"
        },
        {
          "name": "status",
          "jdbc_type": "VARCHAR",
          "notation": "#{}"
        }
      ],
      "oracle_tags": ["rule"],
      "oracle_patterns": ["NVL"],
      "includes": [],
      "select_key": null
    },
    {
      "query_id": "getOrgHierarchy",
      "type": "select",
      "parameter_type": "int",
      "result_type": "com.example.model.Org",
      "result_map": null,
      "statement_type": "PREPARED",
      "sql_raw": "SELECT org_id, parent_id, org_name, LEVEL FROM org_tree START WITH org_id = #{rootId} CONNECT BY PRIOR org_id = parent_id",
      "sql_branches": [
        {
          "condition": "always",
          "sql": "SELECT org_id, parent_id, org_name, LEVEL FROM org_tree START WITH org_id = ? CONNECT BY PRIOR org_id = parent_id"
        }
      ],
      "dynamic_elements": [],
      "parameters": [
        {
          "name": "rootId",
          "jdbc_type": null,
          "notation": "#{}"
        }
      ],
      "oracle_tags": ["llm"],
      "oracle_patterns": ["CONNECT BY", "START WITH", "LEVEL"],
      "includes": [],
      "select_key": null
    },
    {
      "query_id": "insertUser",
      "type": "insert",
      "parameter_type": "com.example.model.User",
      "result_type": null,
      "result_map": null,
      "statement_type": "PREPARED",
      "sql_raw": "INSERT INTO users (id, name, email) VALUES (#{id}, #{name}, #{email})",
      "sql_branches": [
        {
          "condition": "always",
          "sql": "INSERT INTO users (id, name, email) VALUES (?, ?, ?)"
        }
      ],
      "dynamic_elements": [],
      "parameters": [
        { "name": "id", "jdbc_type": null, "notation": "#{}" },
        { "name": "name", "jdbc_type": null, "notation": "#{}" },
        { "name": "email", "jdbc_type": null, "notation": "#{}" }
      ],
      "oracle_tags": ["rule"],
      "oracle_patterns": ["SEQUENCE"],
      "includes": [],
      "select_key": {
        "key_property": "id",
        "result_type": "int",
        "order": "BEFORE",
        "sql": "SELECT SEQ_USER.NEXTVAL FROM DUAL"
      }
    }
  ],
  "metadata": {
    "total_queries": 3,
    "rule_tagged": 2,
    "llm_tagged": 1,
    "has_dynamic_sql": true,
    "has_includes": false,
    "has_select_key": true,
    "ibatis_specific": false
  }
}
```

- [ ] **Step 4: 검증**

```bash
cat .kiro/skills/parse-xml/SKILL.md | head -5
python3 -c "import json; json.load(open('.kiro/skills/parse-xml/assets/parsed-template.json')); print('Valid JSON')"
ls .kiro/skills/parse-xml/references/
```

Expected: SKILL.md frontmatter 확인, JSON 유효, reference 파일 존재

- [ ] **Step 5: 커밋**

```bash
git add .kiro/skills/parse-xml/
git commit -m "feat: add parse-xml skill with tag reference and template"
```

---

## Task 4: rule-convert 스킬

**Files:**
- Create: `.kiro/skills/rule-convert/SKILL.md`
- Create: `.kiro/skills/rule-convert/references/rule-catalog.md`

- [ ] **Step 1: SKILL.md 생성**

Create: `.kiro/skills/rule-convert/SKILL.md`

```markdown
---
name: rule-convert
description: Oracle SQL을 PostgreSQL로 기계적으로 변환하는 룰셋을 적용한다. parsed.json에서 "rule" 태그된 쿼리에 대해 패턴 매칭 기반 치환을 수행한다. steering/oracle-pg-rules.md의 룰셋을 참조한다.
---

## 입력
- workspace/results/{filename}/v{n}/parsed.json

## 처리 절차

1. parsed.json 로드 후 `oracle_tags`에 "rule"이 포함된 쿼리 필터링

2. steering/oracle-pg-rules.md 룰셋 로드

3. 각 쿼리에 대해 순서대로 룰 적용:
   a. 함수 변환 (NVL → COALESCE, DECODE → CASE 등)
   b. 조인 변환 ((+) → ANSI JOIN)
   c. 데이터 타입 변환 (DDL 문이 포함된 경우)
   d. 날짜 포맷 변환 (TO_DATE/TO_CHAR 내 포맷 문자열)
   e. 기타 구문 변환 (DUAL 제거, MINUS → EXCEPT 등)
   f. MyBatis/iBatis 특수 변환 (selectKey, 파라미터 표기)

4. 동적 SQL 분기별로 각각 룰 적용:
   - `<if>` 내부 SQL도 변환
   - `<choose>/<when>/<otherwise>` 각 분기 변환
   - `<foreach>` 내부 SQL 변환

5. 변환 후 Oracle 구문 잔존 검사:
   - 정규식으로 NVL\(, DECODE\(, SYSDATE, ROWNUM, \(\+\), FROM DUAL 등 스캔
   - 잔존하면 해당 쿼리를 "llm" 태그로 에스컬레이션

6. 변환된 XML 파일 생성:
   - workspace/output/{filename}.xml
   - 원본 XML 구조 유지, SQL 본문만 교체

7. 메타데이터 기록:
   - workspace/results/{filename}/v{n}/converted.json
   - 각 쿼리별 method: "rule", rules_applied 목록, confidence: "high"

8. Leader에게 한 줄 요약 반환

## 주의사항
- 하나의 쿼리에 여러 룰이 중복 적용될 수 있음 (NVL + SYSDATE + DUAL 등)
- 동적 SQL 태그의 속성(test 조건 등)은 변환하지 않음 — SQL 본문만 변환
- 룰 적용 순서: 함수 → 조인 → 타입 → 포맷 → 기타 → MyBatis 특수
- steering/edge-cases.md도 참조하여 학습된 패턴이 있으면 우선 적용
```

- [ ] **Step 2: rule-catalog.md 생성**

Create: `.kiro/skills/rule-convert/references/rule-catalog.md`

```markdown
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
```

- [ ] **Step 3: 검증**

```bash
cat .kiro/skills/rule-convert/SKILL.md | head -5
wc -l .kiro/skills/rule-convert/references/rule-catalog.md
```

Expected: frontmatter 확인, rule-catalog 100줄 이상

- [ ] **Step 4: 커밋**

```bash
git add .kiro/skills/rule-convert/
git commit -m "feat: add rule-convert skill with detailed rule catalog"
```

---

## Task 5: llm-convert 스킬

**Files:**
- Create: `.kiro/skills/llm-convert/SKILL.md`
- Create: `.kiro/skills/llm-convert/references/connect-by-patterns.md`
- Create: `.kiro/skills/llm-convert/references/merge-into-patterns.md`
- Create: `.kiro/skills/llm-convert/references/plsql-patterns.md`

- [ ] **Step 1: SKILL.md 생성**

Create: `.kiro/skills/llm-convert/SKILL.md`

```markdown
---
name: llm-convert
description: 룰셋으로 처리할 수 없는 복잡한 Oracle SQL을 LLM을 활용하여 PostgreSQL로 변환한다. CONNECT BY 계층쿼리, MERGE INTO, PIVOT/UNPIVOT, PL/SQL 호출, 복합 분석함수 등을 처리한다.
---

## 입력
- parsed.json에서 "llm" 태그된 쿼리
- 또는 rule-convert에서 에스컬레이션된 쿼리 (잔존 Oracle 구문)

## 처리 절차

1. 쿼리 분류:
   - HIERARCHY: CONNECT BY / START WITH / LEVEL / SYS_CONNECT_BY_PATH
   - MERGE: MERGE INTO ... WHEN MATCHED / NOT MATCHED
   - PIVOT: PIVOT / UNPIVOT
   - PLSQL: 프로시저/패키지 호출, PL/SQL 블록
   - ANALYTIC: 복합 분석함수 (Oracle 전용 윈도우 함수)
   - OTHER: 위 분류에 해당하지 않는 복잡 패턴

2. steering/edge-cases.md에서 동일 패턴 선례 확인:
   - 선례 있으면 → 선례 기반 변환 (confidence: high)
   - 선례 없으면 → references/ 패턴 가이드 참조하여 변환

3. 분류별 변환 실행:
   - HIERARCHY → references/connect-by-patterns.md 참조
   - MERGE → references/merge-into-patterns.md 참조
   - PLSQL → references/plsql-patterns.md 참조
   - PIVOT → 아래 인라인 가이드 참조
   - OTHER → LLM 자유 변환 (confidence: low)

4. PIVOT / UNPIVOT 변환 (인라인):
   ```sql
   -- Oracle PIVOT
   SELECT * FROM sales
   PIVOT (SUM(amount) FOR quarter IN ('Q1' AS q1, 'Q2' AS q2, 'Q3' AS q3, 'Q4' AS q4))
   -- PostgreSQL (CASE 집계)
   SELECT
     SUM(CASE WHEN quarter = 'Q1' THEN amount END) AS q1,
     SUM(CASE WHEN quarter = 'Q2' THEN amount END) AS q2,
     SUM(CASE WHEN quarter = 'Q3' THEN amount END) AS q3,
     SUM(CASE WHEN quarter = 'Q4' THEN amount END) AS q4
   FROM sales
   GROUP BY ...
   ```

   ```sql
   -- Oracle UNPIVOT
   SELECT * FROM quarterly_sales
   UNPIVOT (amount FOR quarter IN (q1 AS 'Q1', q2 AS 'Q2', q3 AS 'Q3', q4 AS 'Q4'))
   -- PostgreSQL (LATERAL + VALUES)
   SELECT qs.*, v.quarter, v.amount
   FROM quarterly_sales qs
   CROSS JOIN LATERAL (
     VALUES ('Q1', qs.q1), ('Q2', qs.q2), ('Q3', qs.q3), ('Q4', qs.q4)
   ) AS v(quarter, amount)
   ```

5. confidence 평가:
   - high: edge-cases.md에 선례 있거나 단순 패턴
   - medium: references 가이드로 변환 가능하지만 검증 필요
   - low: 자유 변환, 반드시 수동 검토 권장

6. 변환 결과를 converted.json에 기록:
   - method: "llm", pattern, confidence, notes

7. 원본 SQL을 주석으로 보존:
   ```sql
   /* Original Oracle: SELECT ... CONNECT BY PRIOR ... */
   WITH RECURSIVE ...
   ```

## 주의사항
- confidence: low인 경우 notes에 불확실 사유 상세 기록
- 동적 SQL 내 복잡 쿼리도 분기별 개별 변환
- 하나의 쿼리에 rule + llm 혼합 가능 (예: NVL + CONNECT BY)
  - rule 부분 먼저 치환 후, 나머지 복잡 부분을 llm으로 처리
```

- [ ] **Step 2: connect-by-patterns.md 생성**

Create: `.kiro/skills/llm-convert/references/connect-by-patterns.md`

```markdown
# CONNECT BY → WITH RECURSIVE 변환 패턴

## 기본 패턴

```sql
-- Oracle
SELECT emp_id, manager_id, emp_name, LEVEL
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id

-- PostgreSQL
WITH RECURSIVE emp_hierarchy AS (
  -- 앵커: START WITH 조건
  SELECT emp_id, manager_id, emp_name, 1 AS level
  FROM employees
  WHERE manager_id IS NULL

  UNION ALL

  -- 재귀: CONNECT BY 조건
  SELECT e.emp_id, e.manager_id, e.emp_name, h.level + 1
  FROM employees e
  INNER JOIN emp_hierarchy h ON e.manager_id = h.emp_id
)
SELECT emp_id, manager_id, emp_name, level FROM emp_hierarchy
```

## NOCYCLE 처리

```sql
-- Oracle
CONNECT BY NOCYCLE PRIOR emp_id = manager_id

-- PostgreSQL: UNION (중복 제거) + 방문 경로 배열
WITH RECURSIVE emp_hierarchy AS (
  SELECT emp_id, manager_id, emp_name, 1 AS level,
         ARRAY[emp_id] AS path
  FROM employees
  WHERE manager_id IS NULL

  UNION  -- UNION ALL이 아닌 UNION으로 중복 제거

  SELECT e.emp_id, e.manager_id, e.emp_name, h.level + 1,
         h.path || e.emp_id
  FROM employees e
  INNER JOIN emp_hierarchy h ON e.manager_id = h.emp_id
  WHERE NOT (e.emp_id = ANY(h.path))  -- 순환 감지
)
SELECT emp_id, manager_id, emp_name, level FROM emp_hierarchy
```

## SYS_CONNECT_BY_PATH

```sql
-- Oracle
SELECT SYS_CONNECT_BY_PATH(emp_name, '/') AS path
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id

-- PostgreSQL
WITH RECURSIVE emp_hierarchy AS (
  SELECT emp_id, manager_id, emp_name, 1 AS level,
         '/' || emp_name AS path
  FROM employees
  WHERE manager_id IS NULL

  UNION ALL

  SELECT e.emp_id, e.manager_id, e.emp_name, h.level + 1,
         h.path || '/' || e.emp_name
  FROM employees e
  INNER JOIN emp_hierarchy h ON e.manager_id = h.emp_id
)
SELECT path FROM emp_hierarchy
```

## CONNECT_BY_ROOT

```sql
-- Oracle
SELECT CONNECT_BY_ROOT emp_name AS root_name, emp_name
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id

-- PostgreSQL
WITH RECURSIVE emp_hierarchy AS (
  SELECT emp_id, manager_id, emp_name, 1 AS level,
         emp_name AS root_name  -- 앵커에서 루트 값 보존
  FROM employees
  WHERE manager_id IS NULL

  UNION ALL

  SELECT e.emp_id, e.manager_id, e.emp_name, h.level + 1,
         h.root_name  -- 재귀에서 루트 값 전달
  FROM employees e
  INNER JOIN emp_hierarchy h ON e.manager_id = h.emp_id
)
SELECT root_name, emp_name FROM emp_hierarchy
```

## ORDER SIBLINGS BY

```sql
-- Oracle
SELECT emp_id, emp_name
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id
ORDER SIBLINGS BY emp_name

-- PostgreSQL: 정렬 경로 배열 사용
WITH RECURSIVE emp_hierarchy AS (
  SELECT emp_id, manager_id, emp_name, 1 AS level,
         ARRAY[emp_name] AS sort_path
  FROM employees
  WHERE manager_id IS NULL

  UNION ALL

  SELECT e.emp_id, e.manager_id, e.emp_name, h.level + 1,
         h.sort_path || e.emp_name
  FROM employees e
  INNER JOIN emp_hierarchy h ON e.manager_id = h.emp_id
)
SELECT emp_id, emp_name FROM emp_hierarchy
ORDER BY sort_path
```

## 단순 레벨 생성 (재귀 불필요)

```sql
-- Oracle
SELECT LEVEL FROM DUAL CONNECT BY LEVEL <= 10

-- PostgreSQL
SELECT generate_series(1, 10) AS level
```
```

- [ ] **Step 3: merge-into-patterns.md 생성**

Create: `.kiro/skills/llm-convert/references/merge-into-patterns.md`

```markdown
# MERGE INTO → INSERT ... ON CONFLICT 변환 패턴

## 기본 UPSERT

```sql
-- Oracle
MERGE INTO users t
USING (SELECT #{id} AS id, #{name} AS name, #{email} AS email FROM DUAL) s
ON (t.id = s.id)
WHEN MATCHED THEN
  UPDATE SET t.name = s.name, t.email = s.email
WHEN NOT MATCHED THEN
  INSERT (id, name, email) VALUES (s.id, s.name, s.email)

-- PostgreSQL
INSERT INTO users (id, name, email)
VALUES (#{id}, #{name}, #{email})
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name, email = EXCLUDED.email
```

## 조건부 UPDATE

```sql
-- Oracle
MERGE INTO users t
USING new_data s ON (t.id = s.id)
WHEN MATCHED THEN
  UPDATE SET t.name = s.name
  WHERE t.updated_at < s.updated_at  -- 조건부 UPDATE
WHEN NOT MATCHED THEN
  INSERT (id, name) VALUES (s.id, s.name)

-- PostgreSQL
INSERT INTO users (id, name, updated_at)
SELECT id, name, updated_at FROM new_data
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name
WHERE users.updated_at < EXCLUDED.updated_at
```

## DELETE 절 포함

```sql
-- Oracle
MERGE INTO users t
USING new_data s ON (t.id = s.id)
WHEN MATCHED THEN
  UPDATE SET t.name = s.name
  DELETE WHERE t.status = 'DELETED'

-- PostgreSQL (2단계로 분리)
-- Step 1: UPSERT
INSERT INTO users (id, name, status)
SELECT id, name, status FROM new_data
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name;

-- Step 2: DELETE
DELETE FROM users WHERE status = 'DELETED'
AND id IN (SELECT id FROM new_data);
```
> MERGE의 DELETE 절은 ON CONFLICT에서 직접 지원하지 않으므로 분리 실행 필요.
> 트랜잭션 내에서 두 문장을 함께 실행하도록 안내.

## 복합 JOIN 조건

```sql
-- Oracle
MERGE INTO order_items t
USING new_items s ON (t.order_id = s.order_id AND t.item_id = s.item_id)
...

-- PostgreSQL (복합 UNIQUE 제약 필요)
INSERT INTO order_items (order_id, item_id, qty)
VALUES (#{orderId}, #{itemId}, #{qty})
ON CONFLICT (order_id, item_id) DO UPDATE
SET qty = EXCLUDED.qty
```
> ON CONFLICT에는 UNIQUE 인덱스 또는 제약이 필수.
> 대상 테이블에 적절한 UNIQUE 제약이 없으면 migration-guide.md에 기록.
```

- [ ] **Step 4: plsql-patterns.md 생성**

Create: `.kiro/skills/llm-convert/references/plsql-patterns.md`

```markdown
# PL/SQL → PL/pgSQL 변환 패턴

## 프로시저 호출 (MyBatis callable)

```xml
<!-- Oracle -->
<select id="callProc" statementType="CALLABLE">
  {call PKG_USER.GET_USER_INFO(#{userId, mode=IN}, #{result, mode=OUT, jdbcType=CURSOR})}
</select>

<!-- PostgreSQL -->
<select id="callProc" statementType="CALLABLE">
  {call get_user_info(#{userId, mode=IN}, #{result, mode=OUT, jdbcType=OTHER})}
</select>
```
> Oracle PACKAGE.PROCEDURE → PostgreSQL에서는 패키지 없이 함수명만
> OUT 파라미터의 jdbcType: CURSOR → OTHER (PostgreSQL refcursor)

## 함수 호출 (SELECT 내)

```sql
-- Oracle
SELECT PKG_UTIL.FORMAT_NAME(first_name, last_name) FROM employees
-- PostgreSQL
SELECT format_name(first_name, last_name) FROM employees
```
> 패키지명 제거, 함수명만 사용

## PACKAGE 전체 변환 가이드

Oracle PACKAGE는 PostgreSQL에 직접 대응이 없음. 변환 전략:

1. **스키마로 대체**: `PKG_USER.PROC()` → `pkg_user.proc()` (스키마.함수)
2. **함수만 마이그레이션**: 패키지 내 각 프로시저/함수를 독립 PL/pgSQL 함수로 생성
3. **패키지 변수**: 세션 변수 또는 임시 테이블로 대체

> 이 변환은 SQL 레벨에서 자동화하기 어려움. migration-guide.md에 수동 검토 항목으로 등록.

## CURSOR 변환

```sql
-- Oracle PL/SQL
OPEN cur FOR SELECT * FROM users WHERE dept_id = p_dept_id;
-- PL/pgSQL
RETURN QUERY SELECT * FROM users WHERE dept_id = p_dept_id;
```

## 예외 처리

```sql
-- Oracle
EXCEPTION
  WHEN NO_DATA_FOUND THEN ...
  WHEN TOO_MANY_ROWS THEN ...
-- PL/pgSQL
EXCEPTION
  WHEN NO_DATA_FOUND THEN ...
  WHEN TOO_MANY_ROWS THEN ...
```
> 기본 예외명은 동일. Oracle 전용 예외는 개별 매핑 필요.

## 주의사항
- MyBatis XML에서 PL/SQL 호출은 `statementType="CALLABLE"` 확인
- OUT/INOUT 파라미터의 jdbcType 변환 필요
- 패키지 레벨 변환은 XML 변환 범위를 넘어서므로 가이드 문서에 기록
```

- [ ] **Step 5: 검증**

```bash
for f in .kiro/skills/llm-convert/SKILL.md .kiro/skills/llm-convert/references/connect-by-patterns.md .kiro/skills/llm-convert/references/merge-into-patterns.md .kiro/skills/llm-convert/references/plsql-patterns.md; do echo "--- $f ---"; head -4 "$f"; done
```

Expected: 4개 파일 모두 존재, 내용 확인

- [ ] **Step 6: 커밋**

```bash
git add .kiro/skills/llm-convert/
git commit -m "feat: add llm-convert skill with CONNECT BY, MERGE, PL/SQL patterns"
```

---

## Task 6: 검증 스킬 3개

**Files:**
- Create: `.kiro/skills/explain-test/SKILL.md`
- Create: `.kiro/skills/execute-test/SKILL.md`
- Create: `.kiro/skills/compare-test/SKILL.md`

- [ ] **Step 1: explain-test SKILL.md 생성**

Create: `.kiro/skills/explain-test/SKILL.md`

```markdown
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
```

- [ ] **Step 2: execute-test SKILL.md 생성**

Create: `.kiro/skills/execute-test/SKILL.md`

```markdown
---
name: execute-test
description: 변환된 PostgreSQL 쿼리를 실제 실행하여 런타임 오류를 검증한다. EXPLAIN 통과한 쿼리만 대상으로 한다. 트랜잭션 내 실행 후 ROLLBACK.
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

## 주의사항
- DML은 반드시 BEGIN/ROLLBACK으로 감싸기 — 데이터 변경 방지
- statement_timeout 30초 — 무한 재귀 방지
- 실행 결과 데이터는 저장하지 않음 (행 수/컬럼 구조만)
```

- [ ] **Step 3: compare-test SKILL.md 생성**

Create: `.kiro/skills/compare-test/SKILL.md`

```markdown
---
name: compare-test
description: 동일 파라미터로 Oracle과 PostgreSQL에 쿼리를 실행하여 결과를 비교한다. execute-test 통과한 SELECT 쿼리만 대상으로 한다.
---

## 입력
- workspace/results/{filename}/v{n}/validated.json (explain + execute 결과)
- workspace/results/{filename}/v{n}/converted.json (PostgreSQL SQL)
- workspace/results/{filename}/v{n}/parsed.json (원본 Oracle SQL)

## 처리 절차

1. validated.json에서 execute.status == "pass" 이고 type == "select"인 쿼리 필터

2. 동일 더미 파라미터로 양쪽 실행:
   - Oracle: parsed.json의 원본 SQL + 더미 파라미터
   - PostgreSQL: converted.json의 변환 SQL + 더미 파라미터

3. 결과 비교 항목:

   a. **행 수** — 정확히 일치해야 함
   b. **컬럼명** — 대소문자 무시하고 비교 (Oracle은 대문자, PG는 소문자 기본)
   c. **컬럼 타입** — 호환 매핑 허용:
      - Oracle DATE ↔ PostgreSQL TIMESTAMP
      - Oracle NUMBER ↔ PostgreSQL NUMERIC/INTEGER
      - Oracle VARCHAR2 ↔ PostgreSQL VARCHAR
   d. **데이터 값** — 허용 오차 적용:
      - 숫자: 절대 오차 1e-10 이내
      - 날짜: 포맷 차이 허용 (시간 부분 무시 옵션)
      - 문자열: 정확히 일치
      - NULL: 양쪽 모두 NULL이면 일치
   e. **정렬 순서** — ORDER BY가 있는 쿼리만 비교

4. 결과 분류:
   - pass: 모든 항목 일치
   - warn: 사소한 차이 (날짜 포맷, NULL vs 빈 문자열)
   - fail: 실질적 차이 (행 수 불일치, 값 불일치)

5. validated.json의 compare 섹션에 기록:
   ```json
   {
     "query_id": "selectUserById",
     "compare": {
       "status": "pass",
       "oracle_rows": 15,
       "pg_rows": 15,
       "match": true,
       "differences": []
     }
   }
   ```
   차이 발견 시:
   ```json
   {
     "compare": {
       "status": "warn",
       "oracle_rows": 15,
       "pg_rows": 15,
       "match": false,
       "differences": [
         {
           "row": 3,
           "column": "created_at",
           "oracle_value": "2024-01-15",
           "pg_value": "2024-01-15 00:00:00",
           "type": "date_format"
         }
       ]
     }
   }
   ```

## Result Integrity Guard (Step 4: 결과 신뢰성 종합 검증)

compare-test 결과가 pass여도 결과의 신뢰성을 다각도로 검증한다.
"양쪽 같음 = 변환 성공"이라는 가정의 허점을 찾아낸다.

### A. 행 수 신뢰성

| 코드 | 심각도 | 조건 |
|------|--------|------|
| WARN_ZERO_BOTH | high | 운영 바인드 값인데 양쪽 0건 |
| WARN_ZERO_ALL_CASES | critical | 모든 테스트 케이스가 0건 |
| WARN_BELOW_EXPECTED | high | expected_rows_hint 대비 10% 미만 |
| WARN_SAME_COUNT_DIFF_ROWS | critical | 행 수 동일하지만 행 내용 해시 불일치 |

행 내용 해시 비교 방법:
1. 양쪽 결과를 전 컬럼으로 정렬
2. 각 행을 JSON 직렬화 → SHA256
3. 해시 집합 비교 → 불일치 행 식별

### B. 값 수준

| 코드 | 심각도 | 조건 |
|------|--------|------|
| WARN_NULL_NON_NULLABLE | medium | NOT NULL 컬럼에서 NULL |
| WARN_EMPTY_VS_NULL | medium | Oracle '' vs PG NULL (또는 반대) |
| WARN_WHITESPACE_DIFF | medium | CHAR 패딩 차이 ('ABC   ' vs 'ABC') |
| WARN_NUMERIC_SCALE | medium | 후행 0 차이 (1.10 vs 1.1) |

trailing space 감지:
1. CHAR 타입 컬럼 식별 (ALL_TAB_COLUMNS)
2. Oracle/PG LENGTH 비교
3. TRIM 후 동일하면 → 패딩 경고

### C. 타입/정밀도

| 코드 | 심각도 | 조건 |
|------|--------|------|
| WARN_DATE_PRECISION | medium | Oracle DATE(초) vs PG TIMESTAMP(마이크로초) |
| WARN_IMPLICIT_CAST | high | 바인드 타입 vs 컬럼 타입 불일치 (Oracle 암묵적 변환) |
| WARN_CLOB_TRUNCATION | high | TEXT 값 길이가 Oracle CLOB과 다름 |
| WARN_BOOLEAN_REPR | medium | Oracle 'Y'/'N'/1/0 vs PG boolean |

### D. 정렬/구조

| 코드 | 심각도 | 조건 |
|------|--------|------|
| WARN_NULL_SORT_ORDER | medium | ORDER BY에서 NULL 행 위치 차이 |
| WARN_CASE_SENSITIVITY | high | 대소문자 비교 동작 차이 |

### severity별 후속 처리
- `critical` → Reviewer 자동 에스컬레이션 (compare pass여도)
- `high` → migration-guide.md 수동 검토 항목
- `medium` → conversion-report.md 경고 기록

## 주의사항
- Oracle과 PostgreSQL 양쪽 모두 읽기 전용 실행
- INSERT/UPDATE/DELETE는 비교 대상 아님 (execute-test에서 이미 검증)
- 대량 결과 시 상위 100행만 비교 (성능)
- 비교 불가 시 (Oracle 접속 실패 등) → status: "skipped", reason 기록
```

- [ ] **Step 4: 검증**

```bash
for skill in explain-test execute-test compare-test; do
  echo "--- $skill ---"
  head -4 ".kiro/skills/$skill/SKILL.md"
done
```

Expected: 3개 스킬 모두 frontmatter 확인

- [ ] **Step 5: 커밋**

```bash
git add .kiro/skills/explain-test/ .kiro/skills/execute-test/ .kiro/skills/compare-test/
git commit -m "feat: add validation skills (explain-test, execute-test, compare-test)"
```

---

## Task 7: report + learn-edge-case 스킬

**Files:**
- Create: `.kiro/skills/report/SKILL.md`
- Create: `.kiro/skills/learn-edge-case/SKILL.md`

- [ ] **Step 1: report SKILL.md 생성**

Create: `.kiro/skills/report/SKILL.md`

```markdown
---
name: report
description: 변환 완료 후 전체 결과를 취합하여 conversion-report.md와 migration-guide.md를 생성한다. workspace/progress.json과 각 파일의 최종 버전 결과를 데이터 소스로 사용한다.
---

## 입력
- workspace/progress.json
- workspace/results/{filename}/v{최종}/converted.json
- workspace/results/{filename}/v{최종}/validated.json

## 산출물 1: workspace/reports/conversion-report.md

```markdown
# 변환 리포트

## 요약
- 총 파일 수: N
- 총 쿼리 수: N
- 성공: N (N%)
- 실패: N (N%)
- 수동 검토 필요: N
- 평균 재시도 횟수: N.N

## 파일별 결과

| 파일명 | 쿼리 수 | 성공 | 실패 | 재시도 | 최종 상태 |
|--------|---------|------|------|--------|----------|
| UserMapper.xml | 50 | 48 | 2 | 3회 | success |
| OrderMapper.xml | 80 | 80 | 0 | 0 | success |
| ... | | | | | |

## 실패 건 상세

### UserMapper.xml#getOrgHierarchy
- 실패 원인: CONNECT BY NOCYCLE → WITH RECURSIVE 순환 탈출 조건 차이
- 시도 이력:
  - v1: RUNTIME_ERROR (infinite recursion)
  - v2: RUNTIME_ERROR (UNION 변경 후에도 재귀)
  - v3: 사용자 에스컬레이션 → 수동 해결 → success
- 최종 상태: success (v4)

## 변환 방법 통계

| 방법 | 쿼리 수 | 비율 |
|------|---------|------|
| 룰 기반 | N | N% |
| LLM 기반 | N | N% |
| 수동 | N | N% |
```

## 산출물 2: workspace/reports/migration-guide.md

```markdown
# 마이그레이션 가이드

## 수동 검토 필요 항목
- [ ] {파일명}#{쿼리ID} — confidence: low, 사유: {notes}
- [ ] {파일명}#{쿼리ID} — compare: warn, 차이: {differences}

## 알려진 제약사항
- Oracle 빈 문자열 = NULL 동작 차이: 관련 쿼리 N건
- Oracle 힌트 제거됨: 관련 쿼리 N건
- PL/SQL 패키지 호출: 별도 함수 마이그레이션 필요 N건

## 이번 변환에서 새로 발견된 에지케이스
- {패턴명}: {설명} (edge-cases.md에 등록됨)

## 권장 후속 작업
1. confidence: low 쿼리 수동 검토
2. compare: warn 쿼리 데이터 검증
3. 인덱스 재검토 (Oracle 힌트 제거에 따른 성능 확인)
4. 부하 테스트
```

## 처리 절차

1. workspace/progress.json 로드 → 전체 현황 파악
2. 각 파일의 최종 버전 결과 수집
3. 통계 집계 (성공/실패/재시도/변환방법)
4. conversion-report.md 생성
5. 수동 검토 대상 식별 (confidence: low, compare: warn, escalated)
6. migration-guide.md 생성
```

- [ ] **Step 2: learn-edge-case SKILL.md 생성**

Create: `.kiro/skills/learn-edge-case/SKILL.md`

```markdown
---
name: learn-edge-case
description: 변환 과정에서 발견된 새 패턴과 에지케이스를 steering에 축적하고 자동으로 PR 또는 Issue를 생성한다. 반복 패턴은 룰셋에, 새 패턴은 에지케이스에 등록한다.
---

## 학습 트리거

### 1. 반복 실패 → 성공
- review.json에서 fix_applied 분석
- 동일 패턴이 3회 이상 다른 파일에서 Reviewer를 거쳤으면 → 룰셋 추가 후보

### 2. 새로운 LLM 변환 패턴
- converted.json에서 method: "llm"인 변환 중
- steering/edge-cases.md에 없는 새 패턴 → 에지케이스 등록

### 3. 사용자 에스컬레이션 후 해결
- progress.json에서 status가 "escalated" → "success"로 변한 건
- 사용자의 수동 수정 내역을 분석하여 학습

## 처리 절차

1. workspace/results/ 전체 스캔

2. 학습 대상 식별 및 분류:
   - rule_candidate: 반복 패턴 (3회 이상)
   - edge_case: 새로운 복잡 패턴
   - manual_resolved: 사용자 해결 건

3. steering 파일 갱신:
   - rule_candidate → steering/oracle-pg-rules.md에 새 룰 추가
   - edge_case, manual_resolved → steering/edge-cases.md에 항목 추가

   edge-cases.md 항목 형식:
   ```markdown
   ### {패턴 이름}
   - **Oracle**: 원본 SQL 패턴/예시
   - **PostgreSQL**: 변환 결과/예시
   - **주의**: 변환 시 주의사항
   - **발견일**: {YYYY-MM-DD}
   - **출처**: {파일명}#{쿼리ID}
   - **해결 방법**: rule | llm | manual
   ```

4. Git 커밋:
   ```bash
   git add .kiro/steering/edge-cases.md .kiro/steering/oracle-pg-rules.md
   git commit -m "chore: add learned edge case - {패턴 요약}"
   ```

5. PR 생성 (steering 변경):
   ```bash
   git checkout -b learn/{date}-{pattern-slug}
   gh pr create \
     --title "chore: add edge case - {패턴 요약}" \
     --body "## 학습된 패턴\n\n- Oracle: ...\n- PostgreSQL: ...\n- 출처: {파일}#{쿼리}\n- 해결: {방법}"
   ```

6. Issue 생성 (사용자 에스컬레이션 해결 건):
   ```bash
   gh issue create \
     --title "edge case: {패턴 요약}" \
     --label "learned-pattern" \
     --body "## 에스컬레이션 해결\n\n- 원본: ...\n- 해결: ...\n- 파일: {파일}#{쿼리}"
   ```

7. Leader에게 요약 반환

## 주의사항
- steering 파일 변경 시 기존 내용을 훼손하지 않도록 append만 수행
- PR 브랜치명: learn/{date}-{pattern-slug} (예: learn/2026-04-09-nocycle-recursion)
- edge-cases.md에 이미 동일 패턴이 있으면 중복 등록하지 않음
```

- [ ] **Step 3: 검증**

```bash
head -4 .kiro/skills/report/SKILL.md
head -4 .kiro/skills/learn-edge-case/SKILL.md
```

Expected: 2개 스킬 frontmatter 확인

- [ ] **Step 4: 커밋**

```bash
git add .kiro/skills/report/ .kiro/skills/learn-edge-case/
git commit -m "feat: add report and learn-edge-case skills"
```
