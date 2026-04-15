---
name: cross-file-analyzer
description: 크로스 파일 의존성 분석. converter 에이전트가 association select, include refid 등 파일 간 참조를 추적하여 변환 순서를 결정할 때 참조합니다.
---

## 개요

query-analyzer 스킬은 단일 파일 내 의존성만 분석한다.
이 스킬은 **전체 XML 파일을 통합 분석**하여 크로스 파일 의존성을 추적한다.

## 입력
- workspace/results/*/v{n}/parsed.json (모든 파일의 파싱 결과)
- workspace/results/*/v{n}/dependency-graph.json (파일별 의존성 그래프)

## 크로스 파일 의존 유형

| 유형 | 소스 | 타겟 | 예시 |
|------|------|------|------|
| ASSOCIATION_SELECT | `<association select="ns.queryId">` | 다른 파일의 쿼리 | `select="com.example.OrderMapper.selectByUserId"` |
| COLLECTION_SELECT | `<collection select="ns.queryId">` | 다른 파일의 쿼리 | `select="com.example.RoleMapper.selectByUserId"` |
| CROSS_INCLUDE | `<include refid="ns.fragmentId">` | 다른 namespace의 SQL fragment | `refid="com.example.CommonMapper.baseColumns"` |
| RESULT_MAP_EXTENDS | `<resultMap extends="ns.mapId">` | 다른 파일의 resultMap | `extends="com.example.BaseMapper.baseResult"` |
| CACHE_REF | `<cache-ref namespace="ns">` | 다른 namespace의 캐시 | `namespace="com.example.UserMapper"` |

## 처리 절차

### Step 1: 네임스페이스 → 파일 매핑 구축
모든 parsed.json에서 namespace를 추출하여 매핑 테이블 생성:
```json
{
  "com.example.mapper.UserMapper": "UserMapper.xml",
  "com.example.mapper.OrderMapper": "OrderMapper.xml"
}
```

### Step 2: 크로스 파일 참조 추출
각 parsed.json에서:
- resultMap의 `association select`, `collection select` 속성 분석
- `select` 값에서 namespace 추출 → 다른 파일인지 판별
- `<include refid>`에서 다른 namespace 참조 감지
- `<resultMap extends>`에서 다른 namespace 참조 감지

### Step 3: 글로벌 의존성 그래프 구축
파일 단위 그래프 + 크로스 파일 엣지를 통합하여 글로벌 그래프 생성

### Step 4: 글로벌 위상 정렬
파일 간 의존 순서를 결정:
- 다른 파일에 의존하지 않는 파일 → 먼저 변환
- 다른 파일에 의존하는 파일 → 의존 대상이 변환된 후 변환

### Step 5: 순환 의존 감지
파일 간 순환 의존이 있으면 WARNING 기록 + 해당 파일들을 같은 레이어에 배치

## 출력

### workspace/results/_global/cross-file-graph.json
```json
{
  "version": 1,
  "total_files": 12,
  "total_queries": 150,
  "namespace_map": {
    "com.example.mapper.UserMapper": "UserMapper.xml",
    "com.example.mapper.OrderMapper": "OrderMapper.xml"
  },
  "cross_file_edges": [
    {
      "from_file": "UserMapper.xml",
      "from_query": "getUserWithOrders",
      "to_file": "OrderMapper.xml",
      "to_query": "selectOrdersByUserId",
      "type": "COLLECTION_SELECT",
      "source": "<collection select=\"com.example.mapper.OrderMapper.selectOrdersByUserId\">"
    }
  ],
  "file_dependency_order": [
    {
      "layer": 0,
      "files": ["CommonMapper.xml", "OrderMapper.xml"],
      "description": "다른 파일에 의존하지 않는 파일"
    },
    {
      "layer": 1,
      "files": ["UserMapper.xml"],
      "depends_on": ["OrderMapper.xml"],
      "description": "Layer 0 파일에 의존"
    },
    {
      "layer": 2,
      "files": ["ReportMapper.xml"],
      "depends_on": ["UserMapper.xml", "OrderMapper.xml"],
      "description": "Layer 0~1 파일에 의존"
    }
  ],
  "cycles": [],
  "isolated_files": ["ConfigMapper.xml"]
}
```

## Leader에게 반환
"크로스 파일 분석 완료: {N}파일, 크로스 참조 {M}건, 파일 레이어 {L}단계, 순환 {C}건"

## 참조 문서

- [의존성 그래프 스키마](../../schemas/dependency-graph.schema.json)
- [크로스파일 그래프 스키마](../../schemas/cross-file-graph.schema.json)
