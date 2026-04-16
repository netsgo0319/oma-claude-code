# OMA Architecture Guide

> Oracle → PostgreSQL MyBatis/iBatis 마이그레이션 에이전트 시스템 아키텍처.

---

## 1. System Overview

```mermaid
flowchart TB
    U["사용자: 변환해줘"]
    U --> SV

    subgraph Supervisor["Supervisor (handoff.json 판단)"]
        SV[Step handoff.json 읽기\nproceed/retry/abort 판단]
    end

    SV --> S1[converter]
    SV --> S2[tc-generator]
    SV --> S3[validate-and-fix]
    SV --> S4[reporter]

    subgraph Tools["Python Tools (공유)"]
        T1[batch-process.sh]
        T2[oracle-to-pg-converter.py]
        T3[generate-test-cases.py]
        T4[validate-queries.py]
        T5[generate-query-matrix.py]
        T6[generate-report.py]
        T7[generate-handoff.py]
        T8[assemble-workspace.sh]
    end

    S1 --> T1 & T2
    S2 --> T3
    S3 --> T4
    S4 --> T5 & T6 & T8

    subgraph Rules["Rules (항상 로드)"]
        R1[guardrails.md — 안전 + handoff 계약]
        R2[oracle-pg-rules.md — 40+ 변환 룰]
        R3[edge-cases.md — 에지케이스]
    end

    S1 & S3 --> Rules

    subgraph Pipeline["pipeline/ (Step별 디렉토리)"]
        P0[step-0-preflight/]
        P1[step-1-convert/]
        P2[step-2-tc-generate/]
        P3[step-3-validate-fix/]
        P4[step-4-report/]
    end

    Tools --> Pipeline
```

### 설계 원칙

| 원칙 | 설명 |
|------|------|
| **슈퍼바이저 = handoff 판단** | handoff.json만 읽고 proceed/retry/abort. 직접 도구 실행 안 함 |
| **Step별 디렉토리 분리** | 각 Step은 자기 output/ + handoff.json만 쓴다. 교차 쓰기는 Step 3→1 tracking만 |
| **EXPLAIN ≠ 완료** | Execute + Compare까지 필수. Compare mismatch도 FAIL |
| **모든 쿼리 TC 기반 검증** | 0건==0건도 PASS. 스킵 없음 |
| **DBA 에러 즉시 분리** | relation/column/function_missing → 수정 루프 진입 안 함 |
| **UTC timestamp** | 로그는 UTC Unix int. 보고서 JS에서 로컬 시간 표시 |
| **스킬 기반 실행** | 26개 스킬 (6 파이프라인 + 20 도메인). 에이전트 skills: 필드로 자동 inject |
| **모델 배치** | supervisor+converter+validate-and-fix: **opus[1m]**, tc-generator+reporter: sonnet |
| **LLM TC 메인 엔진** | infer_value() 제거 → Bedrock Sonnet이 SQL 문맥 기반 TC 생성 (3 workers 병렬, 멀티리전) |
| **Scout → Broadcast** | Step 3에서 복잡 파일 선행 검증 → 발견 패턴 일괄 적용 → 나머지 병렬 |
| **iBatis 2.x 호환** | parse-xml, validate-queries, generate-test-cases에서 #param# + 동적 태그 지원 |

---

## 2. Pipeline + handoff.json 계약

```mermaid
flowchart LR
    S0[Step 0\nPreflight]
    S1[Step 1\nConvert]
    S2[Step 2\nTC Generate]
    S3[Step 3\nValidate+Fix]
    S4[Step 4\nReport]

    S0 -->|handoff.json| S1
    S1 -->|handoff.json| S2
    S2 -->|handoff.json| S3
    S3 -->|handoff.json\n+ gate_checks| S4
    S4 -->|handoff.json| Done([완료])

    S3 -->|gate FAIL\n→ 재위임| S3
```

| Step | 실행 주체 | 도구 | 산출물 | handoff 핵심 |
|------|----------|------|--------|-------------|
| **0** | 슈퍼바이저 | generate-sample-data.py | samples/, env-check.json | xml_file_count, env_checks |
| **1** | **converter** | batch-process.sh, converter.py | output/xml/, query-tracking.json | queries_total, complexity_dist |
| **2** | **tc-generator** | generate-test-cases.py + llm_tc_generator.py | merged-tc.json | queries_with_tc, LLM 3 workers 병렬 |
| **3** | **validate-and-fix** | run-extractor.sh + validate-queries.py | validated.json, compare.json | **gate_checks** + Scout→Broadcast |
| **4** | **reporter** | generate-query-matrix.py, generate-report.py | csv, json, html | validation (fields complete) |

### Step 3 → 4 GATE (★)

슈퍼바이저가 Step 3 handoff.json의 `gate_checks`를 읽고 판단:
- `fix_loop_executed.status == "fail"` → 재위임 ("수정 루프 0회 쿼리 있음")
- `compare_coverage.status == "fail"` → 재위임 ("Compare 미실행 N건")
- `fix_attempted == 0` AND 비-DBA FAIL → 재위임 ("수정 0건 불허")

---

## 3. 데이터 흐름

### 단계별 입출력 매핑

```
Step 0:
  READ:  pipeline/shared/input/*.xml
  WRITE: pipeline/step-0-preflight/output/samples/{TABLE}.json
         pipeline/step-0-preflight/handoff.json

Step 1:
  READ:  pipeline/shared/input/*.xml
         pipeline/step-0-preflight/output/samples/
  WRITE: pipeline/step-1-convert/output/xml/{file}.xml
         pipeline/step-1-convert/output/results/{file}/v1/query-tracking.json
         pipeline/step-1-convert/handoff.json

Step 2:
  READ:  pipeline/step-1-convert/output/results/*/v1/parsed.json
         pipeline/step-0-preflight/output/samples/
  WRITE: pipeline/step-2-tc-generate/output/merged-tc.json
         pipeline/step-2-tc-generate/handoff.json

Step 3 (Scout → Broadcast):
  3a Scout:
    READ:  같은 (L3/L4 복잡 파일 30개 선별)
    WRITE: pipeline/step-3-validate-fix/shared-fixes.jsonl  ← 발견 패턴 공유
  3b Pre-apply:
    READ:  shared-fixes.jsonl
    WRITE: pipeline/step-1-convert/output/xml/*.xml  ← 패턴 일괄 적용
  3c Validate:
    READ:  pipeline/step-1-convert/output/xml/{file}.xml
           pipeline/step-2-tc-generate/output/merged-tc.json
           workspace/results/_extracted_pg/  ← ★ _extracted가 아님
           pipeline/shared/input/*.xml (Compare용)
           shared-fixes.jsonl (fix-loop 전 조회)
    WRITE: pipeline/step-3-validate-fix/output/validation/batch{N}/
           pipeline/step-3-validate-fix/output/extracted_pg/
           pipeline/step-1-convert/output/results/{file}/v1/query-tracking.json  ← cross-write
           pipeline/step-3-validate-fix/handoff.json (gate_checks)

Step 4:
  READ:  ALL query-tracking.json + validated.json + compare.json + extracted
  WRITE: pipeline/step-4-report/output/query-matrix.{csv,json}
         pipeline/step-4-report/output/migration-report.html
         pipeline/step-4-report/handoff.json
```

### query-matrix.json 필드 → 소스 매핑

| 필드 | 소스 Step | 파일 |
|------|----------|------|
| query_id, original_file | Step 1 | query-tracking.json |
| xml_before | Step 4 | input/*.xml에서 ET.tostring 추출 |
| xml_after | Step 4 | output/*.xml에서 ET.tostring 추출 |
| sql_before | Step 1 | extracted_oracle/ → query-tracking.json (fallback) |
| sql_after | Step 3 | extracted_pg/ → query-tracking.json (fallback) |
| conversion_method, conversion_history | Step 1 | query-tracking.json |
| test_cases | Step 2 | per-file/test-cases.json |
| attempts | Step 3 | query-tracking.json (Step 3이 갱신) |
| explain_status | Step 3 | validated.json → query-tracking.json |
| compare_status | Step 3 | compare_validated.json |
| final_state | Step 3 → Step 4 | tracking_utils가 설정 → generate-query-matrix.py가 보충 |
| complexity | Step 1 | complexity-scores.json |
| mybatis_extracted | Step 3 | 'both'/'oracle_only'/'pg_only'/'no' |
| fail_by_extraction | Step 4 | MyBatis 렌더링 vs 정적 추출별 FAIL 분류 |

---

## 4. Query Lifecycle (15-State)

```mermaid
stateDiagram-v2
    [*] --> parsed: Step 1 XML 파싱
    parsed --> converted: 룰 변환 (40+ 룰)
    parsed --> unconverted: 룰로 변환 불가
    unconverted --> converted: LLM 변환 (converter)
    unconverted --> pending: LLM도 실패

    converted --> tc_generated: Step 2 TC 생성
    tc_generated --> mybatis_render: MyBatis 렌더링
    mybatis_render --> validating: SQL 렌더링 성공
    mybatis_render --> ognl_fail: OGNL ClassNotFoundException
    ognl_fail --> stub_gen: 스텁 자동 생성
    stub_gen --> mybatis_render: 재렌더링 (최대 3회)
    mybatis_render --> static_fallback: 빈 SQL
    static_fallback --> validating: static XML에서 추출

    validating --> PASS_COMPLETE: EXPLAIN+Execute+Compare 통과
    validating --> PASS_NO_CHANGE: 변환 불필요
    validating --> FAIL: 에러 발생

    FAIL --> classify: 에러 분류
    classify --> FAIL_SCHEMA_MISSING: relation 없음 (DBA)
    classify --> FAIL_COLUMN_MISSING: column 없음 (DBA)
    classify --> FAIL_FUNCTION_MISSING: function 없음 (DBA)
    classify --> fix_loop: 코드 에러

    fix_loop --> validating: 수정 후 재검증
    fix_loop --> PASS_HEALED: 수정 후 통과
    fix_loop --> FAIL_ESCALATED: 3회 실패

    pending --> NOT_TESTED_PENDING
```

### 15개 최종 상태

| 상태 | 조건 | 분류 |
|------|------|------|
| PASS_COMPLETE | conv + explain pass + compare pass | 성공 |
| PASS_HEALED | attempt > 0 + explain pass + compare pass | 성공 |
| PASS_NO_CHANGE | no_change + explain pass + compare pass | 성공 |
| FAIL_SCHEMA_MISSING | relation does not exist | DBA |
| FAIL_COLUMN_MISSING | column does not exist | DBA |
| FAIL_FUNCTION_MISSING | function does not exist | DBA |
| FAIL_ESCALATED | attempt ≥ 3 + fail | 코드 |
| FAIL_SYNTAX | explain fail + SYNTAX_ERROR | 코드 |
| FAIL_COMPARE_DIFF | compare fail | 코드 |
| FAIL_TC_TYPE_MISMATCH | TYPE_MISMATCH | TC |
| FAIL_TC_OPERATOR | TYPE_OPERATOR | TC |
| NOT_TESTED_DML_SKIP | DML + explain pass + compare not_tested | 미테스트 |
| NOT_TESTED_NO_RENDER | mybatis=no | 미테스트 |
| NOT_TESTED_NO_DB | explain/compare not_tested | 미테스트 |
| NOT_TESTED_PENDING | conv=pending | 미테스트 |

---

## 5. 디렉토리 구조

```
/tmp/oma-claude-code/
  CLAUDE.md                            # 슈퍼바이저 전용 (handoff 판단만)
  .claude/
    agents/                            # 4개 에이전트
      converter.md                     # Step 1
      tc-generator.md                  # Step 2
      validate-and-fix.md              # Step 3 + gate_checks
      reporter.md                      # Step 4 + assemble
    rules/                             # 공유 규칙 (항상 로드)
    skills/                            # 스킬 (20+)
    commands/                          # CLI 명령
    settings.json                      # hooks + permissions

  tools/                               # 공유 Python/Bash 도구
    generate-handoff.py                # ★ handoff.json 생성 유틸
    assemble-workspace.sh              # ★ pipeline → workspace 심링크 조립

  schemas/
    handoff.schema.json                # ★ handoff 스키마

  pipeline/                            # ★ Step별 디렉토리
    supervisor-state.json              # 슈퍼바이저 상태 (compaction 복구)
    shared/input/                      # → workspace/input 심링크
    step-0-preflight/output/ + handoff.json
    step-1-convert/output/ + handoff.json
    step-2-tc-generate/output/ + handoff.json
    step-3-validate-fix/output/ + handoff.json
    step-4-report/output/ + handoff.json

  workspace/                           # 하위 호환 (심링크 뷰)
```

---

## 6. 보고서

| 탭 | 내용 |
|----|------|
| **Overview** | 6카드 + 15-state 상세 테이블 + FAIL 원인 분석 (추출경로별: MyBatis 렌더링 vs 정적 추출) |
| **Explorer** | 파일→쿼리 트리 + 15-state 아이콘/라벨 + SQL diff + TC 결과(바인드값+행수) + Attempt History + **검색어 하이라이트** |
| **DBA** | 누락 오브젝트(DB/테이블/컬럼 명시, 매퍼 파일 위치) + 0건 3분류 (**"재변환 대상" 명시**) |
| **Log** | activity-log.jsonl 타임라인 |

### 산출물

| 파일 | 위치 |
|------|------|
| migration-report.html | `pipeline/step-4-report/output/` |
| query-matrix.csv | `pipeline/step-4-report/output/` |
| query-matrix.json | `pipeline/step-4-report/output/` |

### query-matrix.json 쿼리 예제

```json
{
  "query_id": "selectUser",
  "original_file": "UserMapper.xml",
  "xml_before": "<select id=\"selectUser\">SELECT NVL(NAME,'N/A') FROM TB_USER<where><if test=\"id!=null\">AND ID=#{id}</if></where></select>",
  "xml_after": "<select id=\"selectUser\">SELECT COALESCE(NAME,'N/A') FROM TB_USER<where><if test=\"id!=null\">AND ID=#{id}</if></where></select>",
  "sql_before": "SELECT NVL(NAME,'N/A') FROM TB_USER WHERE ID='USR001'",
  "sql_after": "SELECT COALESCE(NAME,'N/A') FROM TB_USER WHERE ID='USR001'",
  "final_state": "PASS_COMPLETE",
  "final_state_detail": "변환+비교 통과",
  "conversion_method": "rule",
  "conversion_history": [
    {"pattern": "NVL", "approach": "COALESCE 치환", "confidence": "high"}
  ],
  "test_cases": [
    {"name": "sample_row_1", "params": {"id": "USR001"}, "source": "SAMPLE_DATA"}
  ],
  "attempts": [],
  "explain_status": "pass",
  "missing_object": null,
  "compare_status": "pass",
  "compare_detail": [{"oracle_rows": 3, "pg_rows": 3, "match": true}],
  "complexity": "L1"
}
```

### DBA 실패 쿼리 예제

```json
{
  "query_id": "selectAddr",
  "final_state": "FAIL_SCHEMA_MISSING",
  "explain_status": "fail",
  "missing_object": {"type": "table", "name": "taddr", "action": "CREATE TABLE taddr"},
  "compare_status": "not_tested"
}
```

### 상위 레벨 DBA 집계

```json
{
  "dba_objects": [
    {"type": "table", "name": "taddr", "action": "CREATE TABLE taddr",
     "affected_queries": [{"query_id": "selectAddr", "file": "AddrMapper.xml"}]}
  ],
  "dba_zero_rows": {"both_zero": [...], "oracle_only_zero": [...], "pg_only_zero": [...]},
  "compare_fail_types": {"oracle_error": 55, "row_mismatch": 4, "pg_error": 4}
}
```

---

## 7. 성능 최적화

| 기능 | 도구 | 효과 |
|------|------|------|
| **LLM TC 병렬화** | llm_tc_generator.py | 3 workers (ThreadPoolExecutor) + 멀티리전 라운드로빈. 25분→8분 |
| **EXPLAIN 사전 필터** | validate-queries.py | EXPLAIN 실패 쿼리를 Execute/Compare에서 제거 |
| **Compare 배치 실행** | validate-queries.py | 쿼리별 subprocess → DB 세션 1회 (oracledb/psql) |
| **Scout → Broadcast** | shared_fix_registry.py | 복잡 파일 선행 검증 → 패턴 공유 → 나머지 일괄 적용 |
| **pre-scan stubs** | pre-scan-stubs.py | XML 사전 스캔 → Java stub 자동 생성 → 빌드 1회로 완료 |
| **PG 타입 인식 바인딩** | validate-queries.py | TC 값과 PG 컬럼 타입 자동 조정 (varchar↔integer) |

---

## 8. 학습 루프

```
/learn (수동 실행)
  │
  ├── learn-from-results.py → pipeline/learning/
  │     ├── run-{date}.json          이번 실행 분석
  │     ├── cumulative.json          패턴별 누적 카운트
  │     └── promotion-candidates.md  승격 후보 (사람 검토)
  │
  └── 승격 기준:
        3회+ 반복 + regex 가능 → oracle-to-pg-converter.py 룰 추가
        3회+ 반복 + LLM 필요 → oracle-pg-rules.md 가이드 추가
        1~2회 → edge-cases.md 기록
```
