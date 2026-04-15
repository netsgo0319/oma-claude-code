---
inclusion: always
---

# OMA 가드레일 (모든 에이전트 필수 적용)

## 절대 금지 행동

### SQL 안전
- **DML은 PG: BEGIN/ROLLBACK + 5s timeout, Oracle: SELECT COUNT(*) WHERE**
- DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE 실행 금지
- statement_timeout 30초 설정 필수

### XML 입력 파일 — 2단계 원칙
- **1단계: `*.xml` 전부 가져온다. 파일명 패턴 필터 절대 금지.**
  - `*Mapper.xml`만, `*-oracle-*.xml`만, `*-sql-*.xml`만 등 **이름 기반 필터링을 걸지 마라**
  - `-ibatis-`, `-mybatis-`, 접미사 없는 것, 어떤 이름이든 input/에 있는 `*.xml`은 전부 수집
  - `find ... -name "*.xml"` — 이것이 유일하게 허용되는 glob. 추가 조건 금지
- **2단계: 파싱 시 MyBatis/iBatis XML인지 검증한다.**
  - `<mapper>`, `<sqlMap>`, `<select>`, `<insert>`, `<update>`, `<delete>` 태그 존재 여부로 판별
  - MyBatis/iBatis가 아닌 XML(Spring config, POM 등)은 **파싱 단계에서 자동 스킵** — 사전 필터 금지
  - 파일명으로 미리 걸러내면 정작 변환해야 할 파일을 놓친다. **반드시 내용 기반 판별.**

### 파일 안전
- **workspace/ 아래에 임시 .py/.sh 파일을 만들지 마라.** 기존 도구만 사용
- output XML 수정 전 반드시 버저닝: `cp file file.v{N}.bak`

### MyBatis 렌더링 (★ 핵심)
- **모든 쿼리는 MyBatis 엔진 렌더링을 거쳐 진짜 SQL을 추출해야 한다.**
- 렌더링 실패 = 테스트 스킵이 아니라 **TC 보강으로 해결해야 할 버그**
- NOT_TESTED_NO_RENDER를 "괜찮다"고 넘기지 마라. TC에 파라미터 실값을 넣고 재추출하라.
- static fallback(정적 XML 파싱)은 최후 수단. 렌더링 성공률 100%를 목표로 한다.

### MyBatis 파라미터
- **`#{param}`은 MyBatis 바인드 파라미터.** Oracle 구문이 아님. 변환 금지
- `#{sysdate}` → 그대로 유지. bare `SYSDATE`만 CURRENT_TIMESTAMP로 변환

### 검증 원칙
- **EXPLAIN 통과 ≠ 변환 성공.** Execute + Compare까지 필수
- **0건==0건도 유효한 PASS.** Compare를 스킵하지 마라
- **Compare mismatch(Oracle≠PG)도 FAIL이다.** EXPLAIN+Execute PASS여도 Compare 불일치면 수정 루프 대상
- 스키마 에러(relation/column/function_missing)만 수정 루프 면제. 나머지 전부 수정 시도

### PG 환경
- **search_path 필수 확인.** 스키마가 public이 아니면 `SET search_path TO {schema}, public;`
- pgcrypto extension 확인 (PKG_CRYPTO 변환에 필수)

## 보고서 생성 게이트

**reporter 체크리스트를 통과해야만 보고서를 생성할 수 있다:**
- 2c: FAIL인데 수정 루프 0회인 쿼리 → BLOCK
- 2d: DBA 3종 외 Compare 미실행 쿼리 → BLOCK
- 2e: **NOT_TESTED가 전체의 50% 이상** → BLOCK (psql 출력 캡처 실패)
- BLOCK이면 보고서 생성 금지. validate-and-fix 재위임 후 다시 reporter 호출.
- **"추가 검증이 필요하면..." 같은 소극적 보고는 허용하지 않는다. 직접 재실행하라.**

## 최종 JSON 산출물 포맷 (query-matrix.json)

**query-matrix.json이 보고서의 유일한 데이터 소스.** 모든 필드를 반드시 채워라.

### 상위 레벨 필드

```json
{
  "generated_at": "2026-04-15T10:30:00",
  "total": 426,
  "summary": {"PASS_COMPLETE": 300, "FAIL_SYNTAX": 8, ...},
  "explain_error_categories": {"SYNTAX_ERROR": 8, "MISSING_TABLE": 5, ...},
  "oracle_patterns": {"NVL": 150, "DECODE": 80, "CONNECT_BY": 3, ...},
  "complexity_distribution": {"L0": 50, "L1": 200, "L2": 100, "L3": 60, "L4": 16},
  "conversion_methods": {"rule": 380, "llm": 30, "no_change": 10},
  "file_stats": [{"file": "UserMapper.xml", "queries_total": 50, "pass_count": 45, ...}],
  "step_progress": {"step-0": {"status": "success"}, ...},
  "queries": [...]
}
```

### 쿼리별 필드 정의

```json
{
  "query_id": "selectUser",
  "original_file": "UserMapper.xml",
  "sql_before": "SELECT NVL(NAME,'N/A') FROM TB_USER WHERE ID=#{id}",
  "sql_after": "SELECT COALESCE(NAME,'N/A') FROM TB_USER WHERE ID=#{id}",
  "final_state": "PASS_COMPLETE",
  "final_state_detail": "변환+비교 통과",
  "conversion_method": "rule",
  "conversion_history": [
    {"pattern": "NVL", "approach": "COALESCE 치환", "confidence": "high"}
  ],
  "test_cases": [
    {"name": "sample_row_1", "params": {"id": "USR001"}, "source": "SAMPLE_DATA"}
  ],
  "attempts": [
    {"attempt": 1, "ts": 1713100860, "error_category": "SYNTAX_ERROR",
     "error_detail": "syntax error at or near NVL", "fix_applied": "NVL→COALESCE", "result": "fail"},
    {"attempt": 2, "ts": 1713100920, "error_category": null,
     "error_detail": null, "fix_applied": "재검증", "result": "pass"}
  ],
  "explain_status": "pass",
  "compare_status": "pass",
  "complexity": "L1"
}
```

| 필드 | 정의 | 생산 Step | 빈값 의미 |
|------|------|----------|----------|
| `query_id` | MyBatis XML의 `<select id="...">` | Step 1 | — (필수) |
| `original_file` | 원본 XML 파일명 | Step 1 | — (필수) |
| `sql_before` | **변환 전** Oracle SQL 전문 | Step 1 (extracted_oracle → tracking fallback) | 파싱 실패 |
| `sql_after` | **변환 후** PG SQL 전문 | Step 1+3 (extracted_pg → tracking fallback) | 변환 미완료 |
| `final_state` | 14-state 중 하나 (PASS_COMPLETE 등) | Step 4 (계산) | — (필수) |
| `final_state_detail` | 사람 읽는 상태 설명 | Step 4 (계산) | — |
| `conversion_method` | `rule` / `llm` / `no_change` | Step 1 converter | 변환 미완료 |
| `conversion_history` | **변환 레시피** — 어떤 패턴을 어떻게 바꿨는지 | Step 1 converter | 룰 변환은 자동이라 비어있을 수 있음 |
| `test_cases` | 검증에 사용한 TC 목록 (파라미터 + 값) | Step 2 tc-generator | TC 생성 안 됨 |
| `attempts` | **디버깅 이력** — 검증 실패 후 수정 시도 기록 | Step 3 validate-and-fix | 한번에 통과 (수정 불필요) |
| `explain_status` | EXPLAIN 결과 (`pass`/`fail`/`not_tested`) | Step 3 | 검증 미실행 |
| `compare_status` | Compare 결과 (`pass`/`fail`/`not_tested`) | Step 3 | Compare 미실행 |
| `complexity` | 난이도 (`L0`~`L4`) | Step 1 query-analyzer | 분석 미실행 |

### conversion_history vs attempts (★ 혼동 주의)

| | `conversion_history` | `attempts` |
|---|---|---|
| **누가 기록** | Step 1 **converter** | Step 3 **validate-and-fix** |
| **언제** | SQL 변환할 때 | 검증 실패 후 수정할 때 |
| **내용** | "NVL→COALESCE 치환" (변환 레시피) | "syntax error 발생 → 수정 → 재검증" (디버깅) |
| **빈 배열이면** | 룰 변환만 적용 (자동, 기록 안 남을 수 있음) | 한번에 통과 (수정 불필요 = 좋은 것) |
| **필드** | pattern, approach, confidence | attempt, ts, error_category, error_detail, fix_applied, result |

**conversion_history는 "무엇을 바꿨는지", attempts는 "왜 실패하고 어떻게 고쳤는지".**

### 데이터 소스 우선순위

- `sql_before/after`: MyBatis extracted SQL (전문) > query-tracking.json (잘릴 수 있음)
- `test_cases`: test-cases.json에서 로드
- `attempts`: query-tracking.json의 attempts 배열
- `conversion_history`: query-tracking.json의 conversion_history 배열

## query-tracking.json 기록 필수

**서브에이전트가 작업 완료 시 query-tracking.json에 반드시 기록해야 할 것:**
- **converter**: `conversion_history[]` (pattern, approach, confidence) + `conversion_method` + `pg_sql`
- **validate-and-fix**: `attempts[]` (attempt, ts, error_category, error_detail, fix_applied, result) + `explain` + `compare_results`
- **tc-generator**: test-cases.json에 별도 기록 (name, params, source)

**비어있으면 보고서 JSON에 빈 배열로 나온다.** reporter가 검증 시 경고.

## 산출물 필수 규칙

**모든 최종 단계(수정, 재검증, 보고서)는 아래 3개 산출물을 반드시 갱신해야 한다:**
1. `pipeline/step-4-report/output/query-matrix.csv` — flat CSV
2. `pipeline/step-4-report/output/query-matrix.json` — 상세 JSON
3. `pipeline/step-4-report/output/migration-report.html` — HTML 리포트

수정 루프 완료 후, TC 보강 후, 어떤 재검증이든 끝나면 → **반드시 reporter에 위임하여 3개 파일 재생성.**
query-matrix.json에 필수 필드(query_id, original_file, sql_before, sql_after, final_state, test_cases, attempts, conversion_history)가 없으면 불완전.

## handoff.json 계약

**각 Step 완료 시 handoff.json을 반드시 생성한다.** 슈퍼바이저는 이 파일만 읽고 판단한다.

```bash
python3 tools/generate-handoff.py --step {N} --results-dir {path} [options]
```

**Step 3 handoff.json 예제 (gate_checks 포함):**
```json
{
  "step": "step-3-validate-fix",
  "step_number": 3,
  "status": "success",
  "started_at": 1713101520,
  "completed_at": 1713103200,
  "summary": {
    "queries_total": 426,
    "explain_pass": 380,
    "compare_pass": 350,
    "fix_attempted": 25,
    "state_counts": {"PASS_COMPLETE": 300, "PASS_HEALED": 15, "FAIL_SYNTAX": 8}
  },
  "gate_checks": {
    "fix_loop_executed": {"status": "pass", "fail_no_loop_count": 0},
    "compare_coverage": {"status": "pass", "compare_target": 414, "compare_done": 370, "compare_missing_non_dba": 0}
  },
  "outputs": {
    "validation_dir": "pipeline/step-3-validate-fix/output/validation/",
    "tracking_files_updated": ["pipeline/step-1-convert/output/results/UserMapper.xml/v1/query-tracking.json"]
  },
  "next_step": "step-4-report",
  "next_step_recommendation": "proceed"
}
```

## 대량 unconverted 패턴 처리

(+) outer join, MERGE INTO 등 대량 unconverted 패턴이 있을 때:
- **새 변환 스크립트를 만들지 마라.** `oracle-to-pg-converter.py`에 룰을 추가하라.
- LLM 개별 변환이 비효율적이면 → **converter 에이전트가 output XML을 직접 Edit**하라.
- 한 파일 안의 동일 패턴은 한번에 일괄 Edit. 쿼리별로 따로 하지 마라.

## 서브에이전트 행동 규칙

**서브에이전트는 질문하지 마라. 결과를 내라.**
- 리더 에이전트는 서브에이전트에게 답을 줄 수 없다. 질문하고 멈추면 작업이 중단된다.
- 판단이 필요하면 **최선의 판단으로 직접 실행**하고, 결과에 판단 근거를 기록하라.
- "어떻게 할까요?", "확인해주세요", "선택해주세요" → **금지. 직접 결정하고 실행.**
- 에러가 나면 스스로 분석하고 수정 시도하라. 리더에게 에러만 보고하고 멈추지 마라.
- 완료 시 반드시 **handoff.json 생성** + **한 줄 요약 반환**으로 끝내라.

## 리더 전용 금지

- 리더가 직접 validate-queries.py를 실행하는 것 → **validate-and-fix에 위임**
- 리더가 직접 generate-report.py를 실행하는 것 → **reporter에 위임**
- "결과가 분산되어 있어 전체 통합 검증하겠다" → **reporter가 glob으로 통합**
- "전체 EXPLAIN 먼저 돌리고 그다음 Execute" → **--full 원자적 실행만**
- 배치 에이전트 결과를 무시하고 단일 재실행 → **기존 결과 덮어씌워짐**
