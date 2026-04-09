# Oracle → PostgreSQL MyBatis/iBatis Migration Agent Design

> Kiro Custom Agent 기반 Oracle SQL 자동 변환 & 검증 시스템  
> 작성일: 2026-04-09

---

## 1. 개요

### 1.1 목적

MyBatis 3.x / iBatis 2.x XML 파일에 포함된 Oracle SQL을 PostgreSQL로 자동 변환하고, 다단계 검증 후 실패 시 자동 재시도하는 Kiro 에이전트 시스템을 구축한다.

### 1.2 핵심 요구사항

| 항목 | 내용 |
|------|------|
| 변환 엔진 | 하이브리드 (룰셋 + LLM) |
| 규모 | 가변적 (수십~수천 파일), 대규모 시 병렬 처리 |
| 검증 | EXPLAIN → 실행 → Oracle/PostgreSQL 결과 비교 |
| 재시도 | 자동 3회 → 사용자 에스컬레이션 |
| 학습 | 에지케이스 축적, 자동 PR/Issue 생성 |
| 산출물 | 변환 XML + 리포트 + 마이그레이션 가이드 |
| DB 연결 | 사용자가 기존 Oracle/PostgreSQL 접속 정보 제공 |
| 플랫폼 | AWS Kiro (Custom Agent + Subagent + Skills + Steering) |
| 배포 | 불필요 (Kiro 로컬/IDE 환경) |
| 형상관리 | Git으로 에이전트 설정 공유, 팀원이 내려받아 사용 |

### 1.3 사용자

- 개발자 또는 마이그레이션 팀
- 각자 Kiro 환경에서 Git으로 공유된 에이전트 설정을 내려받아 사용

---

## 2. 아키텍처

### 2.1 설계 원칙

1. **컨텍스트 격리** — Leader는 오케스트레이션만, 무거운 작업은 서브에이전트 위임
2. **파일 기반 통신** — `workspace/results/`를 통해 서브에이전트 간 데이터 전달, Leader에게는 요약 한 줄만 반환
3. **버전 관리** — 모든 중간 산출물은 `v{n}` 디렉토리로 버전 추적
4. **steering = 지식 저장소** — 룰셋과 에지케이스가 steering에 누적되어 모든 에이전트가 참조
5. **input/output 분리** — 원본 보존, 변환 결과는 별도 디렉토리

### 2.2 디렉토리 구조

```
oracle-migration-accelerator/
├── .kiro/
│   ├── agents/
│   │   ├── oracle-pg-leader.json      ← 오케스트레이터 (메인 에이전트)
│   │   ├── converter.json             ← 변환 서브에이전트
│   │   ├── test-generator.json        ← 테스트 케이스 생성 서브에이전트
│   │   ├── validator.json             ← 검증 서브에이전트
│   │   ├── reviewer.json              ← 실패 분석 + 재시도 서브에이전트
│   │   └── learner.json               ← 에지케이스 학습 + PR/Issue 생성
│   │
│   ├── prompts/
│   │   ├── oracle-pg-leader.md        ← Leader 프롬프트
│   │   ├── converter.md               ← Converter 프롬프트
│   │   ├── test-generator.md          ← Test Generator 프롬프트
│   │   ├── validator.md               ← Validator 프롬프트
│   │   ├── reviewer.md                ← Reviewer 프롬프트
│   │   └── learner.md                 ← Learner 프롬프트
│   │
│   ├── skills/
│   │   ├── parse-xml/
│   │   │   ├── SKILL.md
│   │   │   ├── references/
│   │   │   │   └── mybatis-ibatis-tag-reference.md
│   │   │   └── assets/
│   │   │       └── parsed-template.json
│   │   ├── rule-convert/
│   │   │   ├── SKILL.md
│   │   │   └── references/
│   │   │       └── rule-catalog.md
│   │   ├── llm-convert/
│   │   │   ├── SKILL.md
│   │   │   └── references/
│   │   │       ├── connect-by-patterns.md
│   │   │       ├── merge-into-patterns.md
│   │   │       └── plsql-patterns.md
│   │   ├── explain-test/
│   │   │   └── SKILL.md
│   │   ├── execute-test/
│   │   │   └── SKILL.md
│   │   ├── compare-test/
│   │   │   └── SKILL.md
│   │   ├── generate-test-cases/
│   │   │   ├── SKILL.md
│   │   │   └── references/
│   │   │       └── oracle-dictionary-queries.md
│   │   ├── report/
│   │   │   └── SKILL.md
│   │   └── learn-edge-case/
│   │       └── SKILL.md
│   │
│   ├── steering/
│   │   ├── product.md                 ← Always 모드
│   │   ├── tech.md                    ← Always 모드
│   │   ├── oracle-pg-rules.md         ← Always 모드
│   │   ├── edge-cases.md              ← Always 모드
│   │   └── db-config.md               ← Manual 모드
│   │
│   └── hooks/
│       └── (에이전트 JSON 내 hooks 필드로 정의)
│
├── workspace/
│   ├── input/                         ← 변환 대상 XML 원본 (불변)
│   ├── output/                        ← 최종 변환 완료 XML
│   ├── results/
│   │   └── {filename}/
│   │       └── v{n}/
│   │           ├── parsed.json
│   │           ├── converted.json
│   │           ├── test-cases.json
│   │           ├── validated.json
│   │           └── review.json
│   ├── reports/
│   │   ├── conversion-report.md
│   │   └── migration-guide.md
│   └── progress.json
│
└── docs/
```

---

## 3. 에이전트 상세 설계

### 3.1 에이전트 ↔ 서브에이전트 관계

Kiro에서 Custom Agent와 Subagent는 동일한 `.kiro/agents/*.json` 형식이다. 차이는 실행 방식:

- 사용자가 직접 실행 → Custom Agent
- 다른 에이전트가 `subagent` 도구로 호출 → Subagent

### 3.2 Leader (oracle-pg-leader.json)

```json
{
  "name": "oracle-pg-leader",
  "description": "Oracle→PostgreSQL MyBatis/iBatis 마이그레이션 오케스트레이터. XML 파일을 스캔하고 서브에이전트에 작업을 분배하며 진행 상황을 추적한다.",
  "prompt": "file://../prompts/oracle-pg-leader.md",
  "model": "claude-opus-4.6",
  "tools": ["read", "write", "glob", "grep", "subagent"],
  "allowedTools": ["read", "glob", "grep"],
  "toolsSettings": {
    "subagent": {
      "availableAgents": ["converter", "test-generator", "validator", "reviewer", "learner"],
      "trustedAgents": ["converter", "test-generator", "validator"]
    }
  },
  "resources": [
    "file://.kiro/steering/**/*.md",
    "skill://.kiro/skills/**/SKILL.md"
  ],
  "hooks": {
    "agentSpawn": [
      {
        "command": "echo '=== Oracle→PG Migration Agent Started ===' && date && mkdir -p workspace/input workspace/output workspace/results workspace/reports"
      }
    ],
    "userPromptSubmit": [
      {
        "command": "cat workspace/progress.json 2>/dev/null || echo '{\"status\": \"no_progress_yet\"}'"
      }
    ],
    "preToolUse": [
      {
        "matcher": "subagent",
        "command": "echo \"[$(date +%H:%M:%S)] Spawning subagent...\""
      }
    ],
    "postToolUse": [
      {
        "matcher": "subagent",
        "command": "echo \"[$(date +%H:%M:%S)] Subagent completed.\" && cat workspace/progress.json 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); total=len(d); done=sum(1 for v in d.values() if v.get('status')=='success'); print(f'Progress: {done}/{total}')\" 2>/dev/null || true"
      }
    ],
    "stop": [
      {
        "command": "echo '=== Cycle Complete ===' && cat workspace/progress.json 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); total=len(d); done=sum(1 for v in d.values() if v.get('status')=='success'); failed=sum(1 for v in d.values() if v.get('status')=='failed'); pending=total-done-failed; print(f'Total: {total} | Success: {done} | Failed: {failed} | Pending: {pending}')\" 2>/dev/null || true"
      }
    ]
  }
}
```

**Leader의 책임:**

1. `workspace/input/` 스캔 → XML 파일 목록 수집
2. 파일 규모에 따라 배치 구성 (10 이하: 순차, 11~100: 5개 배치, 100+: 10개 배치)
3. 서브에이전트 호출 순서 제어: Parser → Converter → Validator → Reviewer → Learner
4. `progress.json` 갱신
5. 전체 완료 후 report 스킬로 최종 산출물 생성

**Leader가 직접 하지 않는 것:** SQL 변환, DB 연결, 쿼리 실행, 에지케이스 분석

### 3.3 Converter (converter.json)

```json
{
  "name": "converter",
  "description": "MyBatis/iBatis XML의 Oracle SQL을 PostgreSQL로 변환한다. 단순 패턴은 룰셋, 복잡 쿼리는 LLM으로 처리.",
  "prompt": "file://../prompts/converter.md",
  "model": "claude-sonnet-4.6",
  "tools": ["read", "write"],
  "allowedTools": ["read", "write"],
  "resources": [
    "file://.kiro/steering/oracle-pg-rules.md",
    "file://.kiro/steering/edge-cases.md",
    "skill://.kiro/skills/rule-convert/SKILL.md",
    "skill://.kiro/skills/llm-convert/SKILL.md",
    "file://.kiro/skills/parse-xml/references/mybatis-ibatis-tag-reference.md"
  ]
}
```

**처리 흐름:**

1. `workspace/results/{filename}/v{n}/parsed.json` 읽기
2. `steering/oracle-pg-rules.md` 참조 → 룰 기반 치환
3. `steering/edge-cases.md` 참조 → 학습된 패턴 적용
4. 룰로 처리 불가한 복잡 쿼리 → LLM 변환 (llm-convert 스킬)
5. 결과 기록:
   - `workspace/output/{filename}.xml` (변환된 XML)
   - `workspace/results/{filename}/v{n}/converted.json` (변환 메타데이터)
6. Leader에게 반환: 한 줄 요약만

**converted.json 구조:**

```json
{
  "version": 1,
  "source_file": "UserMapper.xml",
  "total_queries": 50,
  "conversions": [
    {
      "query_id": "selectUserById",
      "method": "rule",
      "rules_applied": ["NVL→COALESCE", "SYSDATE→CURRENT_TIMESTAMP"],
      "original_sql": "...",
      "converted_sql": "...",
      "confidence": "high"
    },
    {
      "query_id": "getOrgHierarchy",
      "method": "llm",
      "pattern": "CONNECT BY → WITH RECURSIVE",
      "original_sql": "...",
      "converted_sql": "...",
      "confidence": "medium",
      "notes": "3단계 계층 쿼리, NOCYCLE 옵션 포함"
    }
  ]
}
```

### 3.4 Validator (validator.json)

```json
{
  "name": "validator",
  "description": "변환된 PostgreSQL 쿼리를 EXPLAIN, 실행, Oracle 비교로 검증한다.",
  "prompt": "file://../prompts/validator.md",
  "model": "claude-sonnet-4.6",
  "tools": ["read", "write", "@oracle-mcp", "@postgresql-mcp"],
  "allowedTools": ["read", "@oracle-mcp/query", "@postgresql-mcp/query", "@postgresql-mcp/explain"],
  "mcpServers": {
    "oracle-mcp": {
      "command": "npx",
      "args": ["-y", "oracle-mcp-server"],
      "env": {
        "ORACLE_HOST": "${ORACLE_HOST}",
        "ORACLE_PORT": "${ORACLE_PORT}",
        "ORACLE_SID": "${ORACLE_SID}",
        "ORACLE_USER": "${ORACLE_USER}",
        "ORACLE_PASSWORD": "${ORACLE_PASSWORD}"
      },
      "timeout": 60000
    },
    "postgresql-mcp": {
      "command": "npx",
      "args": ["-y", "postgresql-mcp-server"],
      "env": {
        "PG_HOST": "${PG_HOST}",
        "PG_PORT": "${PG_PORT}",
        "PG_DATABASE": "${PG_DATABASE}",
        "PG_USER": "${PG_USER}",
        "PG_PASSWORD": "${PG_PASSWORD}"
      },
      "timeout": 60000
    }
  },
  "resources": [
    "file://.kiro/steering/oracle-pg-rules.md",
    "file://.kiro/steering/edge-cases.md",
    "skill://.kiro/skills/explain-test/SKILL.md",
    "skill://.kiro/skills/execute-test/SKILL.md",
    "skill://.kiro/skills/compare-test/SKILL.md"
  ],
  "hooks": {
    "preToolUse": [
      {
        "matcher": "execute_bash",
        "command": "echo '[SAFETY] Checking for destructive SQL...' && echo $KIRO_TOOL_INPUT | python3 -c \"import sys; data=sys.stdin.read().upper(); dangerous=['DROP ','TRUNCATE ','ALTER ','CREATE ','GRANT ','REVOKE ']; matches=[d for d in dangerous if d in data]; sys.exit(1) if matches else sys.exit(0)\" || (echo 'BLOCKED: Destructive SQL detected' && exit 1)"
      }
    ],
    "postToolUse": [
      {
        "matcher": "@postgresql-mcp",
        "command": "echo \"[$(date +%H:%M:%S)] PostgreSQL query executed\""
      },
      {
        "matcher": "@oracle-mcp",
        "command": "echo \"[$(date +%H:%M:%S)] Oracle query executed\""
      }
    ]
  }
}
```

**3단계 검증 파이프라인:**

| 단계 | 스킬 | 내용 | 실패 시 |
|------|------|------|---------|
| Step 1 | explain-test | PostgreSQL EXPLAIN 실행 → 문법 오류 검출 | Step 2 스킵 |
| Step 2 | execute-test | 트랜잭션 내 실제 실행 → 런타임 오류 검출 | Step 3 스킵 |
| Step 3 | compare-test | Oracle/PostgreSQL 양쪽 동일 파라미터 실행 → 결과 비교 | fail 기록 |
| Step 4 | zero-result-guard | 0건/NULL 결과의 신뢰성 경고 판정 | warn 기록 |

**validated.json 구조:**

```json
{
  "version": 1,
  "source_file": "UserMapper.xml",
  "results": [
    {
      "query_id": "selectUserById",
      "explain": { "status": "pass", "plan": "..." },
      "execute": { "status": "pass", "rows": 15, "duration_ms": 23 },
      "compare": { "status": "pass", "oracle_rows": 15, "pg_rows": 15, "match": true }
    },
    {
      "query_id": "getOrgHierarchy",
      "explain": { "status": "pass" },
      "execute": { "status": "fail", "error": "infinite recursion in WITH RECURSIVE" },
      "compare": { "status": "skipped" }
    }
  ],
  "summary": { "total": 50, "pass": 48, "fail": 2 }
}
```

**Step 4: Result Integrity Guard (결과 신뢰성 종합 검증)**

compare-test 통과 후에도 결과의 신뢰성을 다각도로 검증한다. "양쪽 같음 = 변환 성공"이라는 가정의 허점을 찾아낸다.

**A. 행 수 신뢰성 경고:**

| 경고 코드 | 조건 | 의미 |
|-----------|------|------|
| `WARN_ZERO_BOTH` | Oracle 0건 + PG 0건 + source가 `V$SQL_BIND_CAPTURE` | 운영 바인드 값인데 양쪽 0건 → 데이터 누락 또는 변환 오류 |
| `WARN_ZERO_ALL_CASES` | 모든 테스트 케이스가 0건 | 통계적 비정상 → 높은 확률로 문제 |
| `WARN_BELOW_EXPECTED` | `expected_rows_hint` 대비 실제 결과 10% 미만 | 이력 대비 현저히 적음 |
| `WARN_SAME_COUNT_DIFF_ROWS` | 행 수 동일하지만 내용 해시가 다름 | 겉보기 pass지만 실제 데이터 불일치 |

**B. 값 수준 경고:**

| 경고 코드 | 조건 | 의미 |
|-----------|------|------|
| `WARN_NULL_NON_NULLABLE` | NOT NULL 컬럼에서 NULL 반환 | 스키마 불일치 또는 변환 오류 |
| `WARN_EMPTY_VS_NULL` | Oracle `''` vs PG `NULL` (또는 반대) | Oracle '' = NULL 시멘틱스 차이 |
| `WARN_WHITESPACE_DIFF` | Oracle `'ABC   '` (CHAR 패딩) vs PG `'ABC'` | CHAR → VARCHAR 변환 시 trailing space 차이 |
| `WARN_NUMERIC_SCALE` | Oracle `1.10` vs PG `1.1` (후행 0 차이) | NUMBER → NUMERIC 스케일 차이 |

**C. 타입/정밀도 경고:**

| 경고 코드 | 조건 | 의미 |
|-----------|------|------|
| `WARN_DATE_PRECISION` | Oracle DATE (초 단위) vs PG TIMESTAMP (마이크로초) | 정밀도 손실 또는 불필요 정밀도 |
| `WARN_IMPLICIT_CAST` | Oracle 암묵적 타입 변환 감지 (`WHERE num_col = 'string'`) | PG에서 런타임 에러 또는 다른 결과 가능 |
| `WARN_CLOB_TRUNCATION` | TEXT 컬럼 값이 Oracle CLOB과 길이 차이 | 대용량 텍스트 잘림 |
| `WARN_BOOLEAN_REPR` | Oracle `'Y'/'N'` 또는 `1/0` vs PG boolean 타입 불일치 | 타입 표현 차이 |

**D. 정렬/구조 경고:**

| 경고 코드 | 조건 | 의미 |
|-----------|------|------|
| `WARN_NULL_SORT_ORDER` | ORDER BY 결과에서 NULL 행의 위치가 다름 | NULLS FIRST/LAST 기본값 차이 |
| `WARN_CASE_SENSITIVITY` | 동일 WHERE인데 대소문자 비교 동작 차이 감지 | NLS vs PG collation 차이 |

**경고 판정 로직 상세:**

행 내용 해시 비교 (WARN_SAME_COUNT_DIFF_ROWS 감지):
```
1. 양쪽 결과를 행 단위로 정렬 (ORDER BY 전 컬럼)
2. 각 행을 JSON 직렬화 → SHA256 해시
3. 해시 집합 비교 → 불일치 행 식별
```

trailing space 감지 (WARN_WHITESPACE_DIFF):
```
1. 결과 컬럼 중 CHAR 타입 식별 (ALL_TAB_COLUMNS.DATA_TYPE = 'CHAR')
2. Oracle 결과의 해당 컬럼 값 LENGTH vs PG 결과 LENGTH 비교
3. TRIM 후 동일하면 → trailing space 경고
```

암묵적 타입 변환 감지 (WARN_IMPLICIT_CAST):
```
1. parsed.json에서 WHERE 조건의 바인드 변수 타입 vs 컬럼 타입 비교
2. 불일치 시 (예: 문자열 바인드 vs NUMBER 컬럼) → 경고
3. Oracle은 암묵적 변환 성공, PG는 에러 가능
```

validated.json warnings 형식:

```json
{
  "query_id": "selectUserById",
  "compare": { "status": "pass", "oracle_rows": 15, "pg_rows": 15, "match": true },
  "warnings": [
    {
      "code": "WARN_WHITESPACE_DIFF",
      "severity": "medium",
      "message": "STATUS 컬럼: Oracle CHAR(10) 패딩 'ACTIVE    ' vs PG 'ACTIVE'. TRIM 후 동일.",
      "column": "STATUS",
      "oracle_value": "ACTIVE    ",
      "pg_value": "ACTIVE",
      "test_case_id": "tc1_bind_capture"
    },
    {
      "code": "WARN_IMPLICIT_CAST",
      "severity": "high",
      "message": "WHERE id = #{id}: 바인드 타입 VARCHAR vs 컬럼 타입 NUMBER. Oracle 암묵적 변환, PG 에러 가능.",
      "parameter": "id",
      "bind_type": "VARCHAR",
      "column_type": "NUMBER"
    }
  ]
}
```

severity 수준 및 후속 처리:
- `critical`: WARN_ZERO_ALL_CASES, WARN_SAME_COUNT_DIFF_ROWS → Reviewer 자동 에스컬레이션
- `high`: WARN_ZERO_BOTH, WARN_BELOW_EXPECTED, WARN_IMPLICIT_CAST → 수동 검토 항목
- `medium`: 나머지 → 리포트에 경고 기록 (변환 품질 참고)

**MCP 서버 대안:** MCP 서버 패키지가 없으면 shell 도구 + psql/sqlplus CLI로 대체:

```json
{
  "tools": ["read", "write", "shell"],
  "toolsSettings": {
    "shell": {
      "allowedCommands": ["psql", "sqlplus"],
      "deniedCommands": ["rm", "drop"]
    }
  }
}
```

### 3.5 Reviewer (reviewer.json)

```json
{
  "name": "reviewer",
  "description": "검증 실패한 쿼리의 원인을 분석하고 수정안을 제시한다. 최대 N회 자동 재시도 후 사용자에게 에스컬레이션.",
  "prompt": "file://../prompts/reviewer.md",
  "model": "claude-opus-4.6",
  "tools": ["read", "write", "@postgresql-mcp"],
  "allowedTools": ["read", "write"],
  "mcpServers": {
    "postgresql-mcp": {
      "command": "npx",
      "args": ["-y", "postgresql-mcp-server"],
      "env": {
        "PG_HOST": "${PG_HOST}",
        "PG_PORT": "${PG_PORT}",
        "PG_DATABASE": "${PG_DATABASE}",
        "PG_USER": "${PG_USER}",
        "PG_PASSWORD": "${PG_PASSWORD}"
      },
      "timeout": 60000
    }
  },
  "resources": [
    "file://.kiro/steering/oracle-pg-rules.md",
    "file://.kiro/steering/edge-cases.md"
  ]
}
```

**처리 흐름:**

1. `validated.json`에서 실패 건 읽기
2. 실패 원인 분류: `SYNTAX_ERROR`, `RUNTIME_ERROR`, `DATA_MISMATCH`, `UNKNOWN`
3. 원인별 수정안 생성
4. `review.json` 기록
5. 수정된 SQL로 재변환 요청

**재시도 정책:**

| 시도 | 동작 |
|------|------|
| 1~3 | Reviewer 자동 분석 + 수정 → Converter 재변환 → Validator 재검증 |
| 4 | 사용자 에스컬레이션: 원인, 시도 이력, 수동 확인 필요 사항 제시 |

**review.json 구조:**

```json
{
  "version": 2,
  "query_id": "getOrgHierarchy",
  "failure_type": "RUNTIME_ERROR",
  "root_cause": "WITH RECURSIVE에서 NOCYCLE 대응 누락, 순환 탈출 조건 필요",
  "fix_applied": "UNION ALL → UNION으로 변경하여 중복 제거로 순환 방지",
  "previous_sql": "...",
  "fixed_sql": "...",
  "attempt": 2,
  "max_attempts": 3
}
```

### 3.6 Test Generator (test-generator.json)

```json
{
  "name": "test-generator",
  "description": "쿼리별 바인드 변수를 분석하고 Oracle 딕셔너리에서 메타데이터/실행 이력/실제 바인드 값을 수집하여 의미 있는 테스트 케이스 조합을 생성한다.",
  "prompt": "file://../prompts/test-generator.md",
  "model": "claude-opus-4.6",
  "tools": ["read", "write", "@oracle-mcp"],
  "allowedTools": ["read", "write", "@oracle-mcp/query"],
  "mcpServers": {
    "oracle-mcp": {
      "command": "npx",
      "args": ["-y", "oracle-mcp-server"],
      "env": {
        "ORACLE_HOST": "${ORACLE_HOST}",
        "ORACLE_PORT": "${ORACLE_PORT}",
        "ORACLE_SID": "${ORACLE_SID}",
        "ORACLE_USER": "${ORACLE_USER}",
        "ORACLE_PASSWORD": "${ORACLE_PASSWORD}"
      },
      "timeout": 60000
    }
  },
  "resources": [
    "file://.kiro/steering/oracle-pg-rules.md",
    "skill://.kiro/skills/generate-test-cases/SKILL.md"
  ]
}
```

**처리 흐름:**

1. parsed.json에서 쿼리 구조 분석 (파라미터 목록, 동적 SQL 분기 조건, SQL 의미)

2. Oracle 딕셔너리에서 메타데이터 수집 (generate-test-cases 스킬의 상세 수집 절차 참조):
   - **테이블/컬럼 메타** — ALL_TAB_COLUMNS, ALL_COL_COMMENTS
   - **제약조건** — ALL_CONSTRAINTS, ALL_CONS_COLUMNS (PK, FK, CHECK, NOT NULL)
   - **통계 정보** — ALL_TAB_COL_STATISTICS (분포, 최솟값/최댓값, 유니크 수, NULL 비율)
   - **인덱스** — ALL_INDEXES, ALL_IND_COLUMNS
   - **실행 이력** — V$SQL, V$SQLAREA (SQL 텍스트 매칭)
   - **캡처된 바인드 값** — V$SQL_BIND_CAPTURE (실제 운영에서 사용된 바인드 변수 값)
   - **AWR 이력** — DBA_HIST_SQLSTAT, DBA_HIST_SQL_BIND_METADATA (장기 이력)
   - **샘플 데이터** — 관련 테이블에서 실제 데이터 샘플링
   - **시퀀스 정보** — ALL_SEQUENCES (현재 값, 증분)
   - **시노님/뷰** — ALL_SYNONYMS, ALL_VIEWS (실제 참조 객체 해석)

3. 쿼리 ID별 테스트 케이스 조합 생성:
   - Case 1: Oracle 바인드 캡처 기반 (실제 운영 값)
   - Case 2: 통계 기반 경계값 (min/max/median)
   - Case 3: 동적 SQL 모든 분기를 타는 조합
   - Case 4: NULL/빈 문자열 변형 (Oracle '' = NULL 차이 검출용)
   - Case 5: FK 관계 기반 연관 값 (JOIN이 실제로 매칭되는 값)

4. 결과: workspace/results/{filename}/v{n}/test-cases.json

**test-cases.json 구조:**

```json
{
  "version": 1,
  "source_file": "UserMapper.xml",
  "query_test_cases": [
    {
      "query_id": "selectUserById",
      "parameters": [
        { "name": "id", "type": "INTEGER" },
        { "name": "status", "type": "VARCHAR" }
      ],
      "oracle_metadata": {
        "tables": ["USERS"],
        "row_count": 150000,
        "bind_capture_found": true,
        "sample_data_available": true,
        "avg_rows_processed": 45,
        "total_executions": 12000
      },
      "expected_rows_hint": 45,
      "test_cases": [
        {
          "case_id": "tc1_bind_capture",
          "description": "Oracle V$SQL_BIND_CAPTURE에서 가져온 실제 운영 값",
          "source": "V$SQL_BIND_CAPTURE",
          "binds": { "id": 42, "status": "ACTIVE" }
        },
        {
          "case_id": "tc2_boundary_min",
          "description": "컬럼 통계 최솟값 기반",
          "source": "ALL_TAB_COL_STATISTICS",
          "binds": { "id": 1, "status": "ACTIVE" }
        },
        {
          "case_id": "tc3_boundary_max",
          "description": "컬럼 통계 최댓값 기반",
          "source": "ALL_TAB_COL_STATISTICS",
          "binds": { "id": 149999, "status": "INACTIVE" }
        },
        {
          "case_id": "tc4_null_status",
          "description": "동적 SQL 분기: status가 NULL인 경우",
          "source": "dynamic_sql_branch",
          "binds": { "id": 42, "status": null }
        },
        {
          "case_id": "tc5_empty_string",
          "description": "Oracle '' = NULL 동작 차이 검출",
          "source": "oracle_null_semantics",
          "binds": { "id": 42, "status": "" }
        },
        {
          "case_id": "tc6_sample_data",
          "description": "실제 테이블에서 샘플링한 값",
          "source": "SAMPLE_DATA",
          "binds": { "id": 1023, "status": "SUSPENDED" }
        }
      ]
    }
  ]
}
```

### 3.7 Learner (learner.json)

```json
{
  "name": "learner",
  "description": "변환 과정에서 발견된 새로운 패턴과 에지케이스를 학습하여 steering에 축적하고, 자동으로 PR 또는 Issue를 생성한다.",
  "prompt": "file://../prompts/learner.md",
  "model": "claude-sonnet-4.6",
  "tools": ["read", "write", "grep", "glob", "shell"],
  "allowedTools": ["read", "grep", "glob"],
  "toolsSettings": {
    "shell": {
      "allowedCommands": ["git", "gh"],
      "deniedCommands": ["rm", "drop"]
    }
  },
  "resources": [
    "file://.kiro/steering/oracle-pg-rules.md",
    "file://.kiro/steering/edge-cases.md"
  ],
  "hooks": {
    "stop": [
      {
        "command": "cd $(git rev-parse --show-toplevel) && git diff --name-only .kiro/steering/ | head -5"
      }
    ]
  }
}
```

**학습 트리거:**

| 트리거 | 조건 | 산출물 |
|--------|------|--------|
| 반복 패턴 | 동일 룰이 3회 이상 Reviewer 거침 | oracle-pg-rules.md에 룰 추가 |
| 새 패턴 | LLM 변환 중 edge-cases.md에 없는 패턴 | edge-cases.md에 항목 추가 |
| 사용자 해결 | 에스컬레이션 후 수동 수정 건 | edge-cases.md + Issue 생성 |

**Git 자동화:**

- steering 변경 → `git commit` → `gh pr create --title "chore: add edge case - {패턴}" --body "..."`
- 사용자 해결 건 → `gh issue create --title "edge case: {패턴}" --label "learned-pattern"`

---

## 4. 스킬 상세 설계

### 4.1 parse-xml

```markdown
---
name: parse-xml
description: MyBatis 또는 iBatis XML 파일을 파싱하여 SQL 쿼리를 추출한다.
  mapper namespace, 쿼리 ID, SQL 타입(select/insert/update/delete),
  동적 SQL 요소(if/choose/foreach 등), 파라미터 매핑을 식별한다.
---
```

**사용 에이전트:** Leader

**레퍼런스:** `references/mybatis-ibatis-tag-reference.md` — MyBatis 3.x 28개 태그 + iBatis 2.x 35개+ 태그 전수 레퍼런스

**처리 절차:**

1. XML 루트 태그로 MyBatis 3.x (`<mapper>`) / iBatis 2.x (`<sqlMap>`) 판별
2. `mybatis-ibatis-tag-reference.md` §7 체크리스트 기준으로 전수 파싱
3. 각 쿼리 노드(select, insert, update, delete, statement, procedure) 추출
4. 동적 SQL 요소 식별 및 구조화 (`<if>`, `<choose>`, `<foreach>`, `<iterate>` 등)
5. `<include refid>` → 같은 XML 내 `<sql id>` 인라인 전개
6. 파라미터 매핑 추출 (`#{param}` / `#param#` 자동 판별)
7. Oracle 특유 구문 태깅:
   - 단순 패턴 (NVL, SYSDATE, ROWNUM 등) → `"rule"` 태그
   - 복잡 패턴 (CONNECT BY, MERGE INTO, PIVOT 등) → `"llm"` 태그
8. `workspace/results/{filename}/v1/parsed.json` 기록

### 4.2 rule-convert

```markdown
---
name: rule-convert
description: Oracle SQL을 PostgreSQL로 기계적으로 변환하는 룰셋을 적용한다.
  parsed.json에서 "rule" 태그된 쿼리에 대해 패턴 매칭 기반 치환을 수행한다.
---
```

**사용 에이전트:** Converter

**변환 카테고리:** 함수 변환, 조인 변환, 데이터 타입 변환, 날짜 포맷 변환, 기타 구문 변환, MyBatis/iBatis 특수 변환 (상세는 `steering/oracle-pg-rules.md` 참조)

**처리 절차:**

1. parsed.json에서 `"rule"` 태그 쿼리 필터
2. `steering/oracle-pg-rules.md` 룰셋 로드
3. 각 쿼리에 패턴 매칭 → 치환 적용 (동적 SQL 분기별 각각)
4. 변환 후 Oracle 구문 잔존 검사 → 남아있으면 `"llm"`으로 에스컬레이션
5. `converted.json`에 기록 (method: `"rule"`, rules_applied 목록 포함)

### 4.3 llm-convert

```markdown
---
name: llm-convert
description: 룰셋으로 처리할 수 없는 복잡한 Oracle SQL을 LLM을 활용하여
  PostgreSQL로 변환한다. CONNECT BY 계층쿼리, MERGE INTO, PIVOT/UNPIVOT,
  PL/SQL 호출, 복합 분석함수 등을 처리한다.
---
```

**사용 에이전트:** Converter

**복잡 패턴별 변환:**

| Oracle 패턴 | PostgreSQL 변환 | 레퍼런스 |
|-------------|----------------|----------|
| CONNECT BY / START WITH | WITH RECURSIVE | connect-by-patterns.md |
| NOCYCLE | UNION + 방문 배열 순환 감지 | connect-by-patterns.md |
| MERGE INTO | INSERT ... ON CONFLICT | merge-into-patterns.md |
| PIVOT / UNPIVOT | CASE 집계 또는 crosstab() | (SKILL.md 내장) |
| PL/SQL 프로시저 | PL/pgSQL 함수 | plsql-patterns.md |

**처리 절차:**

1. 쿼리 분류 (계층/MERGE/PIVOT/PL/SQL/기타)
2. `steering/edge-cases.md`에서 동일 패턴 선례 확인
3. 선례 있으면 → 선례 기반 변환
4. 선례 없으면 → `references/` 패턴 가이드 참조하여 변환
5. confidence 평가 (high/medium/low)
6. `converted.json`에 기록

### 4.4 explain-test

```markdown
---
name: explain-test
description: 변환된 PostgreSQL 쿼리에 EXPLAIN을 실행하여 문법 오류를 검증한다.
---
```

**사용 에이전트:** Validator

**파라미터 바인딩 전략:** VARCHAR→`'test'`, INTEGER→`1`, DATE→`'2024-01-01'` (parameterType 참조)

### 4.5 execute-test

```markdown
---
name: execute-test
description: 변환된 PostgreSQL 쿼리를 실제 실행하여 런타임 오류를 검증한다.
  EXPLAIN 통과한 쿼리만 대상. 트랜잭션 내 실행 + ROLLBACK.
---
```

**사용 에이전트:** Validator

**안전장치:** `statement_timeout = '30s'`, DML은 반드시 `BEGIN; ... ROLLBACK;`

### 4.6 compare-test

```markdown
---
name: compare-test
description: 동일 파라미터로 Oracle과 PostgreSQL에 쿼리를 실행하여 결과를 비교한다.
  execute-test 통과한 SELECT 쿼리만 대상.
---
```

**사용 에이전트:** Validator

**비교 항목:** 행 수, 컬럼명(대소문자 무시), 컬럼 타입 호환성, 데이터 값(허용 오차), 정렬 순서

**허용 차이:** Oracle DATE↔PostgreSQL TIMESTAMP, NUMBER 정밀도 1e-10 이내, NULL vs '' (warn 처리)

### 4.7 report

```markdown
---
name: report
description: 변환 완료 후 전체 결과를 취합하여 conversion-report.md와
  migration-guide.md를 생성한다.
---
```

**사용 에이전트:** Leader

**산출물:**

- `conversion-report.md` — 통계, 파일별 요약, 실패 상세, 버전별 이력
- `migration-guide.md` — 수동 검토 항목, 제약사항, 에지케이스, 권장 후속 작업

### 4.8 learn-edge-case

```markdown
---
name: learn-edge-case
description: 변환 과정에서 발견된 새 패턴과 에지케이스를 steering에 축적하고
  자동으로 PR 또는 Issue를 생성한다.
---
```

**사용 에이전트:** Learner

**edge-cases.md 항목 형식:**

```markdown
### [패턴 이름]
- **Oracle**: 원본 SQL 패턴/예시
- **PostgreSQL**: 변환 결과/예시
- **주의**: 변환 시 주의사항
- **발견일**: YYYY-MM-DD
- **출처**: {파일명}#{쿼리ID}
- **해결 방법**: rule | llm | manual
```

### 4.9 에이전트 ↔ 스킬 매핑 요약

| 에이전트 | 사용 스킬 |
|---------|----------|
| Leader | parse-xml, report |
| Converter | rule-convert, llm-convert |
| Test Generator | generate-test-cases |
| Validator | explain-test, execute-test, compare-test |
| Reviewer | (스킬 없이 자체 프롬프트로 분석) |
| Learner | learn-edge-case |

---

## 5. Steering 파일 설계

### 5.1 product.md (Always)

프로젝트 목적, 워크플로우 요약, 산출물 목록, 사용법을 기술한다.

### 5.2 tech.md (Always)

기술 스택(Kiro CLI, claude-opus-4.6/claude-sonnet-4.6), DB 연결(CLI 기반 db-oracle/db-postgresql 스킬), 외부 도구(gh, git), 파일 형식 규약, 디렉토리 규약을 기술한다.

### 5.3 oracle-pg-rules.md (Always)

Oracle→PostgreSQL 변환 룰셋을 정의한다. 카테고리:

- 함수 변환 (NVL, DECODE, SYSDATE, LISTAGG, ROWNUM 등 20+개)
- 조인 변환 ((+) → ANSI JOIN)
- 데이터 타입 변환 (VARCHAR2, NUMBER, CLOB, BLOB 등 16개)
- 날짜 포맷 변환 (RR, FF 등 17개)
- 기타 구문 (DUAL, 빈 문자열, 힌트, MINUS, 파티션 등)
- MyBatis/iBatis 특수 변환 (selectKey, 파라미터 표기, procedure)

Learner가 반복 패턴 발견 시 룰을 자동 추가한다.

### 5.4 edge-cases.md (Always)

Learner가 자동으로 에지케이스를 축적한다. 수동 편집도 가능. PR로 팀 공유.

### 5.5 db-config.md (Manual)

DB 접속 정보 템플릿. 채팅에서 `#db-config`으로 호출. 실제 비밀번호는 환경변수로 관리, steering에는 플레이스홀더만 기록.

---

> **NOTE (2026-04-09 업데이트):** MCP 서버는 CLI 기반 db-oracle/db-postgresql 스킬로 대체되었습니다. 아래 MCP 설정은 초기 설계 기록으로 보존합니다. 실제 구현은 .kiro/agents/*.json 및 .kiro/skills/db-oracle/, .kiro/skills/db-postgresql/ 참조.

## 6. DB 연결 (MCP)

### 6.1 MCP 서버

Validator와 Reviewer에서 `mcpServers` 필드로 Oracle/PostgreSQL MCP 서버를 정의한다. 접속 정보는 환경변수(`${ORACLE_HOST}` 등)로 주입.

> **구현 시 주의:** 스펙 내 MCP 서버 패키지명(`oracle-mcp-server`, `postgresql-mcp-server`)은 가상의 이름이다. 구현 단계에서 실제 존재하는 MCP 서버 패키지를 조사하여 확정해야 한다. 존재하지 않으면 §6.2 대안(shell + psql/sqlplus)을 사용한다.

### 6.2 대안 (MCP 서버 미존재 시)

`shell` 도구 + `psql`/`sqlplus` CLI:

```json
{
  "tools": ["read", "write", "shell"],
  "toolsSettings": {
    "shell": {
      "allowedCommands": ["psql", "sqlplus"],
      "deniedCommands": ["rm", "drop"]
    }
  }
}
```

### 6.3 보안

- Password는 환경변수만 사용 (`.env` 또는 시스템)
- steering/db-config.md에는 플레이스홀더만 기록
- Validator hooks에서 파괴적 SQL (DROP, TRUNCATE, ALTER 등) 차단

---

## 7. 전체 워크플로우

### 7.1 메인 파이프라인

```
Phase 1: 스캔 & 파싱
  Leader → workspace/input/ 스캔 → parse-xml 스킬 → parsed.json (v1)

Phase 2: 변환 (병렬)
  Leader → [subagent] Converter × N → converted.json (v1) + output XML

Phase 2.5: 테스트 케이스 생성 (병렬)
  Leader → [subagent] Test Generator × N → test-cases.json (v1)
  - Oracle 딕셔너리에서 메타데이터/실행 이력/바인드 캡처 값 수집
  - 쿼리별 다중 테스트 케이스 조합 생성

Phase 3: 검증 (병렬, test-cases.json 활용)
  Leader → [subagent] Validator × N → validated.json (v1)
  - 각 테스트 케이스별로 EXPLAIN → 실행 → Oracle/PG 비교 수행

Phase 4: 실패 건 리뷰 & 재시도 (반복, 최대 3회)
  Leader → [subagent] Reviewer → review.json
         → [subagent] Converter (v{n+1}) → [subagent] Validator (v{n+1})
         → 성공 시 다음 / 실패 시 반복 / 3회 초과 시 에스컬레이션

Phase 5: 학습
  Leader → [subagent] Learner → edge-cases.md 갱신 + PR/Issue

Phase 6: 리포트
  Leader → report 스킬 → conversion-report.md + migration-guide.md
```

### 7.2 에스컬레이션 후 재개

사용자가 수동 해결 후 Leader에게 재검증 요청 → 새 버전(v{n+1}) 생성 → Validator 재검증 → 성공 시 Learner가 해결 건 학습

### 7.3 progress.json 상태 머신

```
pending → parsing → converting → validating → success
                                     │
                                     ├── retry_1 → validating
                                     ├── retry_2 → validating
                                     ├── retry_3 → validating
                                     └── escalated → (사용자 개입) → validating → success
```

### 7.4 배치 전략

| 파일 수 | 병렬도 |
|---------|--------|
| 1~10 | 순차 (서브에이전트 1개씩) |
| 11~100 | 5개 단위 병렬 배치 |
| 100+ | 10개 단위 병렬 배치 |

### 7.5 파일 기반 통신

서브에이전트 간 데이터 전달은 `workspace/results/{file}/v{n}/` 파일을 통해 수행. Leader에게는 한 줄 요약만 반환. 컨텍스트 폭발 방지.

---

## 8. 버전 관리 체계

모든 중간 산출물은 버전별 디렉토리에 보관:

```
workspace/results/{filename}/
  v1/
    parsed.json       ← 최초 파싱
    converted.json    ← 최초 변환
    validated.json    ← 최초 검증 → 실패
    review.json       ← 실패 원인 분석
  v2/
    converted.json    ← 리뷰 반영 재변환
    validated.json    ← 재검증 → 실패
    review.json       ← 2차 분석
  v3/
    converted.json    ← 최종 변환
    validated.json    ← 검증 성공
```

**이점:** 재시도 이력 추적, 디버깅(v1↔v3 비교), 학습 데이터(변화 과정 분석), 롤백 가능

---

## 9. 형상관리 & 팀 공유

### 9.1 Git 관리 대상

| 경로 | Git 추적 | 이유 |
|------|----------|------|
| `.kiro/agents/` | O | 에이전트 설정 공유 |
| `.kiro/prompts/` | O | 프롬프트 공유 |
| `.kiro/skills/` | O | 스킬 공유 |
| `.kiro/steering/` | O | 룰셋 & 에지케이스 공유 |
| `workspace/input/` | 프로젝트별 판단 | 원본 XML |
| `workspace/output/` | 프로젝트별 판단 | 변환 결과 |
| `workspace/results/` | X (.gitignore) | 중간 산출물, 용량 큼 |
| `workspace/reports/` | O | 리포트 공유 |
| `workspace/progress.json` | X (.gitignore) | 런타임 상태 |

### 9.2 .gitignore

```
workspace/results/
workspace/progress.json
.env
```

### 9.3 팀 사용 흐름

```
1. git clone → .kiro/ 설정 일괄 획득
2. .env 파일에 DB 접속 정보 설정
3. workspace/input/에 변환 대상 XML 배치
4. kiro-cli --agent oracle-pg-leader 실행
5. 학습된 에지케이스 → Learner가 자동 PR 생성
6. 팀원이 PR 리뷰 & 머지 → 전원 steering 업데이트
```
