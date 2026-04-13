---
name: complex-query-decomposer
description: L3~L4 복잡도 쿼리를 변환 가능한 서브 태스크 DAG로 분해한다. ROWNUM 페이징 구조 변환, 인라인 CONNECT BY의 CTE 추출, 동적 SQL 분기별 변환 등 구조적 변환이 필요한 경우 변환 계획을 생성한다.
---

## 개요

L0~L2 쿼리는 텍스트 치환(rule-convert)이나 단일 패턴 변환(llm-convert)으로 충분하다.
L3~L4 쿼리는 **쿼리 구조 자체를 변경**해야 하므로, 변환을 서브 태스크로 분해하고 순서를 정한다.

## 입력
- workspace/results/{filename}/v{n}/parsed.json (해당 쿼리)
- workspace/results/{filename}/v{n}/complexity-scores.json (L3, L4 쿼리 식별)

## 대상
complexity-scores.json에서 level이 L3 또는 L4인 쿼리만 대상.
L0~L2 쿼리는 이 스킬을 사용하지 않는다.

## 분해 패턴

### Pattern 1: ROWNUM 페이징 구조 변환
```
입력:
  SELECT * FROM (
    SELECT a.*, ROWNUM rn FROM (
      {내부_쿼리}
      ORDER BY {정렬}
    ) a WHERE ROWNUM <= #{pageEnd}
  ) WHERE rn > #{pageStart}

분해:
  Step 1: 내부 쿼리 추출 ({내부_쿼리} + ORDER BY 부분)
  Step 2: 내부 쿼리의 Oracle 구문 변환 (NVL, DECODE 등)
  Step 3: ROWNUM 외부 구조 제거
  Step 4: LIMIT/OFFSET으로 재구성:
    {변환된_내부_쿼리}
    ORDER BY {정렬}
    LIMIT (#{pageEnd} - #{pageStart}) OFFSET #{pageStart}
  
  주의: 동적 SQL 태그가 내부 쿼리에 있으면 태그를 보존한 채 구조 변환
```

### Pattern 2: 인라인 CONNECT BY → CTE 추출
```
입력:
  SELECT u.*, dept.name FROM users u
  LEFT JOIN (
    SELECT org_id, org_name, LEVEL AS depth
    FROM org_tree
    START WITH parent_id IS NULL
    CONNECT BY PRIOR org_id = parent_id
  ) dept ON u.org_id = dept.org_id

분해:
  Step 1: 인라인 CONNECT BY 서브쿼리 식별 및 추출
  Step 2: CONNECT BY → WITH RECURSIVE CTE 변환 (llm-convert 패턴 사용)
  Step 3: CTE를 쿼리 최상위로 이동
  Step 4: 원래 서브쿼리 위치를 CTE 참조로 교체
  
  결과:
    WITH RECURSIVE dept_hierarchy AS (
      SELECT org_id, org_name, 1 AS depth FROM org_tree WHERE parent_id IS NULL
      UNION ALL
      SELECT o.org_id, o.org_name, h.depth + 1
      FROM org_tree o INNER JOIN dept_hierarchy h ON o.parent_id = h.org_id
    )
    SELECT u.*, dept.name FROM users u
    LEFT JOIN dept_hierarchy dept ON u.org_id = dept.org_id
```

### Pattern 3: 동적 SQL 분기별 분리 변환
```
입력:
  <choose>
    <when test="type == 'hierarchy'">
      SELECT ... CONNECT BY ... (L4)
    </when>
    <when test="type == 'flat'">
      SELECT ... NVL(...) (L1)
    </when>
    <otherwise>
      SELECT ... DECODE(...) ROWNUM (L2)
    </otherwise>
  </choose>

분해:
  Step 1: 각 분기의 SQL을 독립적으로 분류 (L1, L2, L4)
  Step 2: 분기별로 적합한 변환 전략 적용:
    - when[0] (L4) → complex-query-decomposer + llm-convert
    - when[1] (L1) → rule-convert
    - otherwise (L2) → rule-convert
  Step 3: 변환된 각 분기를 원래 <choose> 구조에 재조립
```

### Pattern 4: 복합 패턴 (여러 Pattern 중첩)
```
입력: ROWNUM 페이징 + 내부에 CONNECT BY + 동적 SQL

분해:
  Step 1: 최외곽 패턴 식별 (ROWNUM 페이징)
  Step 2: 내부 패턴 식별 (CONNECT BY, 동적 SQL)
  Step 3: 안쪽부터 바깥쪽으로 변환 (Inside-Out):
    3a: 동적 SQL 각 분기 내 단순 Oracle 구문 변환 (rule)
    3b: CONNECT BY → WITH RECURSIVE CTE 추출
    3c: ROWNUM 페이징 → LIMIT/OFFSET 구조 변환
  Step 4: 전체 조립
```

## 출력: transform-plan.json

각 L3~L4 쿼리에 대해 `workspace/results/{filename}/v{n}/{queryId}-transform-plan.json` 생성:

```json
{
  "version": 1,
  "query_id": "nightmare",
  "source_file": "UserMapper.xml",
  "complexity_level": "L4",
  "complexity_score": 18,
  "patterns_detected": ["ROWNUM_PAGINATION", "INLINE_CONNECT_BY", "DYNAMIC_SQL_BRANCHES", "NVL", "DECODE"],
  "transformation_strategy": "inside_out",
  "steps": [
    {
      "step": 1,
      "action": "EXTRACT_INNER_QUERY",
      "description": "ROWNUM 3중 페이징 구조에서 내부 쿼리를 추출",
      "input": "전체 SQL",
      "output": "내부 SELECT ... FROM users u ... ORDER BY ...",
      "preserves_dynamic_sql": true
    },
    {
      "step": 2,
      "action": "RULE_CONVERT_BRANCHES",
      "description": "동적 SQL 각 분기 내 단순 Oracle 구문 변환",
      "targets": [
        {"branch": "if[name]", "patterns": []},
        {"branch": "when[admin]", "patterns": []},
        {"branch": "otherwise", "patterns": ["NVL"]},
        {"branch": "if[ids]", "patterns": []},
        {"branch": "static", "patterns": ["NVL", "DECODE"]}
      ]
    },
    {
      "step": 3,
      "action": "EXTRACT_CTE",
      "description": "인라인 CONNECT BY 서브쿼리를 WITH RECURSIVE CTE로 추출",
      "input": "LEFT JOIN (SELECT ... CONNECT BY ...) o ON ...",
      "output": "WITH RECURSIVE org_cte AS (...) ... LEFT JOIN org_cte o ON ...",
      "reference": "llm-convert/references/connect-by-patterns.md"
    },
    {
      "step": 4,
      "action": "RESTRUCTURE_PAGINATION",
      "description": "ROWNUM 3중 페이징을 LIMIT/OFFSET으로 재구성",
      "input": "SELECT * FROM (SELECT a.*, ROWNUM rn FROM (...) WHERE ROWNUM <= ?) WHERE rn > ?",
      "output": "... ORDER BY ... LIMIT ? OFFSET ?",
      "reference": "llm-convert/references/rownum-pagination-patterns.md"
    },
    {
      "step": 5,
      "action": "ASSEMBLE",
      "description": "변환된 파트들을 최종 SQL로 조립",
      "output": "WITH RECURSIVE org_cte AS (...) SELECT ... FROM users u LEFT JOIN org_cte o ON ... WHERE ... ORDER BY ... LIMIT ? OFFSET ?",
      "dynamic_sql_preserved": true
    }
  ],
  "estimated_difficulty": "high",
  "manual_review_recommended": true,
  "notes": "CTE가 최상위로 이동하면서 동적 SQL 태그의 위치 조정 필요"
}
```

## Leader에게 반환
"L3~L4 분해 완료: {N}개 쿼리, 평균 {M}단계, 수동 검토 권장 {K}건"

## Converter가 이 파일을 활용하는 방법
1. L3~L4 쿼리의 transform-plan.json 확인
2. steps 배열의 순서대로 변환 실행 (step 1 → step 2 → ...)
3. 각 step의 action에 따라 적절한 스킬 호출:
   - RULE_CONVERT_BRANCHES → rule-convert
   - EXTRACT_CTE → llm-convert (connect-by-patterns 참조)
   - RESTRUCTURE_PAGINATION → llm-convert (rownum-pagination-patterns 참조)
   - ASSEMBLE → 최종 조립
4. 각 step 완료 시 중간 결과를 activity-log.jsonl에 기록
