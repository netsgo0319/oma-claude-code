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

-- PostgreSQL: UNION ALL + 방문 경로 배열
WITH RECURSIVE emp_hierarchy AS (
  SELECT emp_id, manager_id, emp_name, 1 AS level,
         ARRAY[emp_id] AS path
  FROM employees
  WHERE manager_id IS NULL

  UNION ALL  -- UNION ALL 사용 (DAG에서 다른 경로 재방문 허용)

  SELECT e.emp_id, e.manager_id, e.emp_name, h.level + 1,
         h.path || e.emp_id
  FROM employees e
  INNER JOIN emp_hierarchy h ON e.manager_id = h.emp_id
  WHERE NOT (e.emp_id = ANY(h.path))  -- path 배열로 순환만 감지 (다른 경로 재방문은 허용)
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

## CONNECT_BY_ISLEAF

```sql
-- Oracle
SELECT emp_id, emp_name, CONNECT_BY_ISLEAF AS is_leaf
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id

-- PostgreSQL: LEFT JOIN으로 자식 존재 여부 확인
WITH RECURSIVE emp_hierarchy AS (
  SELECT emp_id, manager_id, emp_name, 1 AS level
  FROM employees
  WHERE manager_id IS NULL
  UNION ALL
  SELECT e.emp_id, e.manager_id, e.emp_name, h.level + 1
  FROM employees e
  INNER JOIN emp_hierarchy h ON e.manager_id = h.emp_id
)
SELECT h.emp_id, h.emp_name,
       CASE WHEN NOT EXISTS (
         SELECT 1 FROM emp_hierarchy c WHERE c.manager_id = h.emp_id
       ) THEN 1 ELSE 0 END AS is_leaf
FROM emp_hierarchy h
```

## 다중 CONNECT BY 조건

```sql
-- Oracle
SELECT emp_id, emp_name
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id AND PRIOR dept_id = dept_id

-- PostgreSQL: 복수 JOIN 조건
WITH RECURSIVE emp_hierarchy AS (
  SELECT emp_id, manager_id, emp_name, dept_id, 1 AS level
  FROM employees
  WHERE manager_id IS NULL
  UNION ALL
  SELECT e.emp_id, e.manager_id, e.emp_name, e.dept_id, h.level + 1
  FROM employees e
  INNER JOIN emp_hierarchy h 
    ON e.manager_id = h.emp_id AND e.dept_id = h.dept_id
)
SELECT emp_id, emp_name FROM emp_hierarchy
```

## START WITH 서브쿼리

```sql
-- Oracle
SELECT org_id, org_name, LEVEL
FROM org_tree
START WITH org_id IN (SELECT root_org_id FROM config WHERE active = 'Y')
CONNECT BY PRIOR org_id = parent_id

-- PostgreSQL
WITH RECURSIVE org_hierarchy AS (
  SELECT org_id, parent_id, org_name, 1 AS level
  FROM org_tree
  WHERE org_id IN (SELECT root_org_id FROM config WHERE active = 'Y')
  UNION ALL
  SELECT o.org_id, o.parent_id, o.org_name, h.level + 1
  FROM org_tree o
  INNER JOIN org_hierarchy h ON o.parent_id = h.org_id
)
SELECT org_id, org_name, level FROM org_hierarchy
```
