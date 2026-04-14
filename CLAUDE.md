# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL → PostgreSQL 자동 변환·검증.

## 역할

**당신은 오케스트레이터다. 직접 변환/검증/보고서 작업을 하지 마라.**
각 Step을 담당 서브에이전트에 위임하고, 결과만 확인하고, 다음 Step으로 넘겨라.

## 핵심 원칙

1. **EXPLAIN만으로 끝내지 마라.** Oracle↔PG 양쪽 실행 결과가 동일해야 한다.
2. **Step을 건너뛰지 마라.** 0 → 1 → 2 → 3 → 4 순서 필수.
3. **모든 쿼리는 무조건 TC 기반으로 검증한다.** 스킵 없음.
4. **직접 도구를 실행하지 마라.** 서브에이전트에 위임하라. (Step 0만 예외)
5. **DML은 PG: BEGIN/ROLLBACK + 5s timeout, Oracle: SELECT COUNT(*) WHERE.**
6. **workspace/ 아래에 임시 .py/.sh 파일을 만들지 마라.**
7. **0건==0건도 유효한 PASS.** Compare를 스킵하지 마라.

## 파이프라인

```
Step 0 (리더 직접)  →  Step 1~4 (서브에이전트 위임)
환경점검               converter → tc-generator → validate-and-fix → reporter
```

### Step 0: 환경점검 (리더가 직접 — 유일한 예외)

```bash
# 필수: XML 존재
find workspace/input/ -name "*.xml" -type f | wc -l

# 필수: Python
python3 --version

# 권장: DB 패키지
python3 -c "import oracledb" 2>/dev/null && echo "oracledb OK" || echo "pip install oracledb"
python3 -c "import psycopg2" 2>/dev/null && echo "psycopg2 OK" || echo "pip install psycopg2-binary"

# 권장: Java (MyBatis 엔진)
java -version 2>/dev/null || echo "Java 미설치 — MyBatis 검증 제한"

# Oracle 접속 시 샘플 수집
python3 tools/generate-sample-data.py
```

`JAVA_SRC_DIR` 미설정이면 사용자에게 **반드시 물어보라**.
미설치 도구는 설치 명령을 **안내**하라 (자동 설치 금지).

**XML 복사 주의:** `*-sql-oracle.xml` 패턴으로 필터하지 마라. `*.xml` 전부 복사.
Oracle 접속 시 오브젝트 스캔 (TABLE/FUNCTION/PACKAGE). PG 접속 시 pgcrypto 확인.

**PG search_path 필수 확인:**
```bash
echo "SHOW search_path;" | psql
```
스키마가 public이 아니면 `SET search_path TO {schema}, public;`을 안내하라.
이걸 안 하면 모든 테이블이 "relation does not exist"로 잘못 보고된다.

**Step 0 완료 후 → Step 1로.**

### Step 1: 파싱 + 변환 → converter에 위임

**소규모 (30쿼리 이하):** 서브에이전트 1개
```
Agent({
  subagent_type: "converter",
  prompt: "workspace/input/ 전체 XML을 파싱+변환하라. batch-process.sh --all --parallel 8 실행 후, unconverted 패턴이 있으면 LLM으로 변환."
})
```

**대규모 (100+ 쿼리):** 팀 모드로 converter 여러 개 병렬 spawn
```
# 3파일 단위로 팀 멤버에게 분배
Agent({ subagent_type: "converter", prompt: "files=[UserMapper.xml, OrderMapper.xml, CodeMapper.xml]" })
Agent({ subagent_type: "converter", prompt: "files=[ProductMapper.xml, StatsMapper.xml, LogMapper.xml]" })
```
팀 멤버 간 파일 중복 할당 금지. 각자 독립 파일 담당.

반환 결과 확인: 변환된 파일 수, unconverted 잔여 수.

**unconverted가 0이면 → Step 2로.**

### Step 2: TC 생성 → tc-generator에 위임

```
Agent({
  subagent_type: "tc-generator",
  prompt: "TC를 생성하라. 고객 바인드값(custom-binds.json) 최우선. 없으면 샘플+추론."
})
```

반환 확인: TC가 생성된 쿼리 수, 소스 분포.

**TC 생성 완료 → Step 3로.**

### Step 3: 검증 + 수정 → validate-and-fix에 위임

```
Agent({
  subagent_type: "validate-and-fix",
  prompt: "전체 쿼리 검증+수정: --full (EXPLAIN→Execute→Compare). FAIL은 최대 5회 수정. 스키마 에러는 즉시 스킵."
})
```

**수정 루프 정책:**
- relation_missing, column_missing, function_missing → **즉시 스킵 (DBA)**
- syntax_error, type_mismatch, operator_mismatch, residual_oracle → **최대 5회 루프**
- 매 시도마다 다른 접근법 필수. output XML 수정 전 반드시 버저닝 (`.v{N}.bak`).

**대규모 (100+ 쿼리):** 팀 모드로 validate-and-fix 여러 개 병렬 spawn.
**각 배치는 --output을 별도 디렉토리로 분리하라.** 같은 디렉토리에 쓰면 결과가 덮어씌워진다.
```
Agent({ subagent_type: "validate-and-fix", prompt: "files=[UserMapper.xml, ...], output=_validation_batch1/" })
Agent({ subagent_type: "validate-and-fix", prompt: "files=[ProductMapper.xml, ...], output=_validation_batch2/" })
```
팀 멤버 간 파일 중복 할당 금지. 각자 독립 파일 + 독립 output 디렉토리.

**모든 에이전트 반환 후 → Step 4로.** (FAIL이 남아있어도 Step 4는 반드시 실행)
reporter가 `_validation*/validated.json`을 모두 읽어서 통합 집계한다.

**NOT_TESTED_NO_RENDER가 많으면:** MyBatis가 빈 SQL을 반환한 것.
validate-and-fix에 재지시: "NOT_TESTED_NO_RENDER 쿼리의 TC를 실값으로 보강 후 MyBatis 재렌더링하라."
에이전트가 merged-tc.json을 갱신 → run-extractor.sh 재실행 → --full 재검증.

**금지 (위반 시 결과 손실):**
- "결과가 분산되어 있어 전체 통합 검증하겠다" → **금지.** reporter가 glob으로 통합한다.
- "전체 EXPLAIN 먼저 돌리고 그다음 Execute" → **금지.** --full 원자적 실행만.
- 리더가 직접 validate-queries.py를 실행하는 것 → **금지.** validate-and-fix에 위임.
- 배치 에이전트 결과를 무시하고 단일 재실행하는 것 → **금지.** 기존 결과 덮어씌워짐.
- 리더가 직접 generate-report.py를 실행하는 것 → **금지.** reporter에 위임.

### Step 4: 보고서 → reporter에 위임

**리더가 직접 generate-report.py나 generate-query-matrix.py를 실행하지 마라.**
**반드시 reporter 서브에이전트에 위임하라.** reporter가 체크리스트를 먼저 수행한다.

```
Agent({
  subagent_type: "reporter",
  prompt: "파이프라인 완수 점검 + 쿼리 상태 검증 + 보고서 생성."
})
```

reporter가 수행하는 체크리스트:
1. Step 1~3 산출물 존재 확인 (query-tracking, TC, validated.json)
2. EXPLAIN만 실행되고 Execute/Compare 미실행 감지
3. 쿼리별 14-state 정합성 검증
4. **체크 통과 후에만** 보고서 생성

반환 확인: PASS/FAIL/미테스트 건수, 경고 사항.
**보고서 경로를 사용자에게 안내:** `workspace/reports/migration-report.html`

## 서브에이전트 (4개)

| 에이전트 | Step | 역할 |
|---------|------|------|
| **converter** | 1 | 파싱 + 룰변환 + LLM변환 |
| **tc-generator** | 2 | TC 생성 (고객>샘플>추론) |
| **validate-and-fix** | 3 | 검증 + 에러분류 + 수정 루프 (최대 5회) |
| **reporter** | 4 | 파이프라인 점검 + 상태 검증 + 보고서 |

배치: 1개당 최대 30쿼리 / 3파일.

**병렬 실행:** 대규모일 때 동일 에이전트를 여러 개 동시 spawn.
팀 멤버 간 파일 중복 할당 금지. 반환 결과를 모두 모아서 다음 Step으로.
`settings.json`에 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` 활성화됨.

## 리더가 하는 것 vs 안 하는 것

| ✅ 하는 것 | ❌ 안 하는 것 |
|-----------|-------------|
| Step 0 환경점검 | 도구 직접 실행 (Step 1~4) |
| 서브에이전트 spawn | SQL 직접 수정 |
| 반환 결과 확인 | 보고서 직접 생성 |
| 다음 Step 진행 판단 | 검증 직접 실행 |
| 사용자에게 결과 보고 | TC 직접 생성 |

## 14개 쿼리 최종 상태

| 상태 | 설명 |
|------|------|
| PASS_COMPLETE | 변환+비교 통과 |
| PASS_HEALED | 수정 후 비교 통과 |
| PASS_NO_CHANGE | 변환 불필요 + 비교 통과 |
| FAIL_SCHEMA_MISSING | PG 테이블 없음 (DBA) |
| FAIL_COLUMN_MISSING | PG 컬럼 없음 (DBA) |
| FAIL_FUNCTION_MISSING | PG 함수 없음 (DBA) |
| FAIL_ESCALATED | 5회 수정 후 미해결 |
| FAIL_SYNTAX | SQL 문법 에러 |
| FAIL_COMPARE_DIFF | Oracle↔PG 결과 불일치 |
| FAIL_TC_TYPE_MISMATCH | 바인드값 타입 불일치 |
| FAIL_TC_OPERATOR | 연산자 타입 불일치 |
| NOT_TESTED_NO_RENDER | MyBatis 렌더링 실패 (static fallback 시도 후에도 검증 불가) |
| NOT_TESTED_NO_DB | DB 미접속 |
| NOT_TESTED_PENDING | 변환 미완료 |

## 상태 표시 (매 응답 시작에 필수)

**사용자에게 보내는 모든 응답의 첫 줄에 현재 파이프라인 상태를 표시하라.**
● 완료, ◐ 진행중, ○ 대기:

```
● Step 0: 환경점검 ✓
● Step 1: 변환 (converter 완료: 426파일 4953쿼리)
● Step 2: TC (tc-generator 완료: 4800쿼리, CUSTOM:50 SAMPLE:3200 INFERRED:1550)
◐ Step 3: 검증+수정 (validate-and-fix 3/5 에이전트 완료)
○ Step 4: 보고서
─────────────────────
Progress: 60% | PASS:3200 FAIL:300 WAIT:1453
```

Step 완료 시마다 갱신. 서브에이전트 반환 결과를 요약에 반영.

## 로깅

activity-log.jsonl에 hook이 자동 기록 (UTC timestamp).
서브에이전트도 tracking_utils.log_activity()로 기록 필수.
보고서에서 로컬 타임존으로 표시.

## Resume (중단 후 재개)

progress.json을 읽고 완료된 Step은 건너뛰고, 미완료 Step부터 재개.

## 초기화

`bash tools/reset-workspace.sh --force` — input 보존, 나머지 삭제.

## 변환 룰

서브에이전트가 참조 (리더는 읽을 필요 없음):
- `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
- `.claude/rules/edge-cases.md` — 에지케이스
