---
name: query-analyzer
description: 쿼리 복잡도 분석. converter 에이전트가 의존성 그래프와 L0~L4 복잡도를 계산하여 변환 순서를 결정할 때 사용합니다.
---

## 개요

모든 쿼리를 flat하게 변환하는 대신, 의존성 그래프를 구축하여 리프 쿼리부터 변환한다.
리프가 성공해야 상위 쿼리의 변환/검증이 의미 있다.

## 입력
- workspace/results/{filename}/v{n}/parsed.json (전체 파일)

## 처리 절차

### Step 1: 의존성 추출

parsed.json의 각 쿼리에서 다음 의존 관계를 추출:

| 의존 유형 | 소스 | 타겟 | 감지 방법 |
|----------|------|------|----------|
| SQL_FRAGMENT | `<include refid="X">` | `<sql id="X">` | includes 배열 |
| NESTED_SELECT | `<association select="ns.queryId">` | 해당 queryId | resultMap 분석 |
| NESTED_COLLECTION | `<collection select="ns.queryId">` | 해당 queryId | resultMap 분석 |
| SUBQUERY | SQL 내 서브쿼리 | 참조 테이블/뷰 | SQL 파싱 |
| SEQUENCE | `<selectKey>` 시퀀스 | 시퀀스 객체 | selectKey 분석 |

### Step 2: 복잡도 점수 산정

각 쿼리에 대해 복잡도 점수를 계산:

```
base_score = 0

# Oracle 구문 복잡도
+1: NVL, NVL2, DECODE, SYSDATE, SYSTIMESTAMP, ROWNUM (각각)
+1: sequence.NEXTVAL/CURRVAL
+1: (+) 아우터 조인 (per occurrence)
+1: Oracle 힌트 (/*+ ... */)
+1: FROM DUAL
+1: MINUS
+2: LISTAGG
+2: PIVOT / UNPIVOT
+3: CONNECT BY / START WITH
+3: MERGE INTO
+3: PL/SQL 프로시저/패키지 호출

# 동적 SQL 복잡도
+1: <if> / <isNotNull> / <isNotEmpty> 등 (per tag)
+2: <choose>/<when>/<otherwise> (per choose block)
+2: <foreach> / <iterate> (per tag)
+3: 동적 SQL 중첩 (2단계 이상 — if 안에 choose, foreach 안에 if 등)

# 구조 복잡도
+1: 서브쿼리 (per depth level)
+1: JOIN (3개 이상 테이블부터, per additional table)
+2: <include> 참조 (per reference)
+3: <association select> / <collection select> (per nested query)
+1: UNION / UNION ALL (per occurrence)
```

### Step 3: 레벨 분류

| Level | 이름 | 점수 범위 | 변환 전략 |
|-------|------|----------|----------|
| L0 | Static | 0 | 변환 불필요 또는 복사만 |
| L1 | Simple Rule | 1~3 | rule-convert만으로 충분 |
| L2 | Dynamic Simple | 4~6 | rule-convert + 동적 SQL 주의 |
| L3 | Dynamic Complex | 7~12 | rule + llm 혼합, 신중하게 |
| L4 | Oracle Complex | 13+ | llm 위주, 수동 검토 권장 |

### Step 4: 위상 정렬 (Topological Sort)

의존성 그래프에서 위상 정렬을 수행하여 변환 레이어를 결정:

```
Layer 0: 의존성 없는 쿼리 (리프 노드)
  - SQL fragments (<sql id>)
  - 독립적인 단순 쿼리
Layer 1: Layer 0에만 의존하는 쿼리
  - <include>로 fragment를 참조하는 쿼리
Layer 2: Layer 0~1에 의존하는 쿼리
  - <association select>로 Layer 1 쿼리를 참조
Layer 3+: 깊은 의존성
  - 중첩 참조 체인
```

순환 의존성 감지: 순환이 발견되면 해당 쿼리들을 같은 레이어에 배치하고 WARNING 로그 기록.

### Step 5: 출력

3개 JSON 파일을 workspace/results/{filename}/v{n}/ 에 생성:

#### dependency-graph.json
```json
{
  "version": 1,
  "source_file": "UserMapper.xml",
  "nodes": [
    {
      "query_id": "commonColumns",
      "type": "sql_fragment",
      "dependents": ["selectUserById", "searchUsers"]
    },
    {
      "query_id": "selectUserById",
      "type": "select",
      "depends_on": ["commonColumns"],
      "dependents": ["getUserWithOrders"]
    },
    {
      "query_id": "getUserWithOrders",
      "type": "select",
      "depends_on": ["selectUserById"],
      "dependents": []
    }
  ],
  "edges": [
    {"from": "selectUserById", "to": "commonColumns", "type": "SQL_FRAGMENT"},
    {"from": "getUserWithOrders", "to": "selectUserById", "type": "NESTED_SELECT"}
  ],
  "cycles": [],
  "total_nodes": 3,
  "total_edges": 2
}
```

#### complexity-scores.json
```json
{
  "version": 1,
  "source_file": "UserMapper.xml",
  "queries": [
    {
      "query_id": "commonColumns",
      "score": 0,
      "level": "L0",
      "level_name": "Static",
      "breakdown": {}
    },
    {
      "query_id": "selectUserById",
      "score": 3,
      "level": "L1",
      "level_name": "Simple Rule",
      "breakdown": {
        "oracle_nvl": 1,
        "oracle_sysdate": 1,
        "include_ref": 1
      }
    },
    {
      "query_id": "getOrgHierarchy",
      "score": 15,
      "level": "L4",
      "level_name": "Oracle Complex",
      "breakdown": {
        "oracle_connect_by": 3,
        "oracle_sys_connect_by_path": 1,
        "oracle_nocycle": 1,
        "dynamic_if": 2,
        "dynamic_choose": 2,
        "subquery_depth": 2,
        "join_tables": 2,
        "include_ref": 2
      }
    }
  ],
  "summary": {
    "L0": 5,
    "L1": 20,
    "L2": 15,
    "L3": 8,
    "L4": 2,
    "total": 50,
    "average_score": 4.2
  }
}
```

#### conversion-order.json
```json
{
  "version": 1,
  "source_file": "UserMapper.xml",
  "layers": [
    {
      "layer": 0,
      "description": "SQL fragments + 독립 쿼리 (의존성 없음)",
      "queries": ["commonColumns", "userColumns", "simpleSelect"],
      "strategy": "rule-convert만 사용, 병렬 변환 가능"
    },
    {
      "layer": 1,
      "description": "Layer 0 참조하는 쿼리",
      "queries": ["selectUserById", "insertUser", "updateUser"],
      "depends_on_layers": [0],
      "strategy": "Layer 0 성공 확인 후 변환"
    },
    {
      "layer": 2,
      "description": "Layer 0~1 참조하는 복잡 쿼리",
      "queries": ["getUserWithOrders", "searchUsers"],
      "depends_on_layers": [0, 1],
      "strategy": "Layer 0~1 성공 확인 후 변환, llm 필요할 수 있음"
    },
    {
      "layer": 3,
      "description": "최상위 복잡 쿼리",
      "queries": ["getOrgHierarchy"],
      "depends_on_layers": [0, 1, 2],
      "strategy": "llm 위주 변환, 수동 검토 권장"
    }
  ],
  "total_layers": 4,
  "conversion_strategy": "Layer 0부터 순차적으로 변환 → 검증 → 다음 Layer"
}
```

## Leader에게 반환
"의존성 분석 완료: {N}개 쿼리, {L}개 레이어. L0:{a}개, L1:{b}개, L2:{c}개, L3:{d}개, L4:{e}개"

## 참조 문서

- [복잡도 스키마](../../schemas/complexity-scores.schema.json)
- [의존성 스키마](../../schemas/dependency-graph.schema.json)
- [변환 순서 스키마](../../schemas/conversion-order.schema.json)
