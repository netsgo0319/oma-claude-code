# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL을 PostgreSQL로 자동 변환, 검증하는 AI 에이전트 시스템.

Claude Code 기반으로 슈퍼바이저 + 4개 서브에이전트가 5단계 파이프라인을 실행합니다.
각 Step은 독립 디렉토리에서 실행되며, `handoff.json` 계약으로 연결됩니다.

## 전체 파이프라인

```
pipeline/shared/input/*.xml (Oracle MyBatis XML)
        |
  Step 0  Preflight — 환경 체크 + 샘플 수집
        | handoff.json
  Step 1  Convert — XML 파싱 → 40+ 룰 변환 + LLM 변환
        | handoff.json
  Step 2  TC Generate — 테스트 케이스 생성
        | handoff.json
  Step 3  Validate + Fix — EXPLAIN → Execute → Compare + 수정 루프 (최대 3회)
        | handoff.json (gate_checks)  ← ★ GATE
  Step 4  Report — HTML 리포트 + Query Matrix CSV/JSON
        |
pipeline/step-4-report/output/migration-report.html
```

### Step별 상세

| Step | 이름 | 에이전트 | 도구 | handoff 핵심 |
|------|------|---------|------|-------------|
| 0 | Preflight | 슈퍼바이저 직접 | generate-sample-data.py | env_checks, xml_file_count |
| 1 | Convert | **converter** | batch-process.sh, oracle-to-pg-converter.py | queries_total, complexity |
| 2 | TC Generate | **tc-generator** | generate-test-cases.py | queries_with_tc |
| 3 | Validate+Fix | **validate-and-fix** | validate-queries.py, run-extractor.sh | **gate_checks** |
| 4 | Report | **reporter** | generate-query-matrix.py, generate-report.py | validation |

## 구성 (Claude Code)

```
.claude/
  agents/         4개 에이전트 (converter, tc-generator, validate-and-fix, reporter)
  skills/         스킬 (20+)
  rules/          규칙 (guardrails, oracle-pg-rules, edge-cases, db-config)
  commands/       CLI 명령 (convert, validate, report, status, reset)
  settings.json   hooks + permissions

tools/                               공유 Python/Bash 도구
  generate-handoff.py                handoff.json 생성 유틸
  assemble-workspace.sh              pipeline → workspace 심링크 조립
  oracle-to-pg-converter.py          40+ 룰 기계적 변환
  validate-queries.py                3단계 검증 + Compare
  generate-test-cases.py             TC 생성
  generate-report.py                 HTML 리포트
  generate-query-matrix.py           Query Matrix CSV/JSON
  tracking_utils.py                  공용 트래킹 (flock 안전, final_state 분류)
  llm_tc_generator.py                LLM TC 생성 (Bedrock Sonnet, structured output)
  learn-from-results.py              결과 학습 + 패턴 추출 + 룰 승격 제안
  batch-process.sh                   Step 1 병렬 처리
  run-extractor.sh                   MyBatis 추출 래퍼

schemas/
  handoff.schema.json                handoff 계약 스키마
  query-tracking.schema.json         쿼리 추적 스키마
  (기타 11개 스키마)

pipeline/                            Step별 디렉토리
  shared/input/                      원본 XML
  step-0-preflight/output/ + handoff.json
  step-1-convert/output/ + handoff.json
  step-2-tc-generate/output/ + handoff.json
  step-3-validate-fix/output/ + handoff.json
  step-4-report/output/ + handoff.json
  supervisor-state.json              슈퍼바이저 상태

workspace/                           하위 호환 (심링크 뷰)
```

## 에이전트

| 에이전트 | 모델 | 역할 |
|---------|------|------|
| **converter** | **Opus[1M]** | Oracle→PG 변환. batch-process.sh 룰 변환 + LLM 복합 변환. 11개 스킬 preload |
| **tc-generator** | Sonnet | TC 생성. 커스텀바인드 > **LLM(Bedrock Sonnet, 3 workers 병렬)** — infer_value 제거됨 |
| **validate-and-fix** | **Opus[1M]** | 검증+수정. run-extractor → --full → fix-loop(3회). 10개 스킬 preload |
| **reporter** | Sonnet | 보고서. query-matrix.json → HTML 4탭 (Overview/Explorer/DBA/Log) |

## 환경변수

```bash
# Oracle
export ORACLE_HOST=oracle.example.com
export ORACLE_PORT=1521
export ORACLE_SID=ORCL
export ORACLE_USER=migration_user
export ORACLE_PASSWORD=****

# PostgreSQL
export PG_HOST=pg.example.com
export PG_PORT=5432
export PG_DATABASE=target_db
export PG_USER=migration_user
export PG_PASSWORD=****

# LLM TC 생성 (Step 2)
export LLM_TC_ENABLED=1
export AWS_BEARER_TOKEN_BEDROCK=...                          # Bedrock 인증 토큰
export LLM_TC_REGIONS="us-east-1,us-west-2,ap-northeast-2"  # 멀티리전 (throttling 분산)
export LLM_TC_WORKERS=3                                      # 동시 API 호출 수
```

## 실행

```bash
# 1. 입력 XML 복사
cp /path/to/mybatis/*.xml workspace/input/
ln -sfn $(pwd)/workspace/input pipeline/shared/input

# 2. Claude Code 실행
claude    # → "변환해줘" → Step 0~4 자동 수행

# 또는 개별 도구
python3 tools/oracle-to-pg-converter.py pipeline/shared/input/Mapper.xml pipeline/step-1-convert/output/xml/Mapper.xml
python3 tools/validate-queries.py --full --output pipeline/step-3-validate-fix/output/validation/
python3 tools/generate-report.py --output pipeline/step-4-report/output/migration-report.html
```

## 산출물

| 경로 | 내용 |
|------|------|
| `pipeline/step-1-convert/output/xml/*.xml` | 변환된 PostgreSQL MyBatis XML |
| `pipeline/step-4-report/output/migration-report.html` | **통합 HTML 리포트** |
| `pipeline/step-4-report/output/query-matrix.csv` | 전체 쿼리 매트릭스 (flat) |
| `pipeline/step-4-report/output/query-matrix.json` | 쿼리 매트릭스 (상세 JSON) |
| `pipeline/step-{N}-*/handoff.json` | Step별 handoff 계약 |

### HTML 리포트 구성

- **Overview**: 6개 카드 + Step Progress 바
- **Explorer**: 파일→쿼리 트리 + MyBatis XML diff + 렌더링 SQL diff + Attempt History
- **DBA**: 누락 오브젝트 그룹핑 + 0건 3분류 (양쪽0/Oracle만0/PG만0)
- **Log**: 활동 타임라인 + 감사 로그

## 최종 JSON 구조

### handoff.json (Step 3 예제)

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
    "state_counts": {
      "PASS_COMPLETE": 300,
      "PASS_HEALED": 15,
      "FAIL_SYNTAX": 8,
      "FAIL_SCHEMA_MISSING": 5
    }
  },
  "gate_checks": {
    "fix_loop_executed": {"status": "pass", "fail_no_loop_count": 0},
    "compare_coverage": {"status": "pass", "compare_target": 414, "compare_done": 370}
  },
  "outputs": {
    "validation_dir": "pipeline/step-3-validate-fix/output/validation/"
  },
  "next_step": "step-4-report",
  "next_step_recommendation": "proceed"
}
```

### query-matrix.json (쿼리 예제)

```json
{
  "query_id": "selectUser",
  "original_file": "UserMapper.xml",
  "type": "select",
  "xml_before": "<select id=\"selectUser\">SELECT NVL(NAME,'N/A')...</select>",
  "xml_after": "<select id=\"selectUser\">SELECT COALESCE(NAME,'N/A')...</select>",
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

## 핵심 안전장치

| 장치 | 내용 |
|------|------|
| DDL 차단 hook | DROP/TRUNCATE/ALTER TABLE 실행 차단 |
| DML safety | PG: BEGIN/ROLLBACK + 5s timeout, Oracle: SELECT COUNT(*) WHERE |
| GATE check | Step 3→4: fix_loop + compare_coverage 둘 다 pass 필수 |
| MyBatis #{param} 보존 | 바인드 파라미터는 Oracle 패턴이 아님. 변환 금지 |
| Cross-step write | Step 3→1 query-tracking만. fcntl.flock 원자적 |
| EXPLAIN 사전 필터 | EXPLAIN 실패 쿼리는 Execute/Compare 스킵 (DB 시간 절약) |
| Compare 배치 실행 | 쿼리별 subprocess 대신 단일 세션으로 배치 (Oracle 1회 + PG 1회) |
| File-scoped tracking | query-tracking 갱신 시 (file, qid) 스코프로 충돌 방지 |
| Compaction 복구 | pipeline/supervisor-state.json으로 상태 복원 |

<!-- harness-eval-badge:start -->
![Harness Score](https://img.shields.io/badge/harness-7.2%2F10-yellow)
![Harness Grade](https://img.shields.io/badge/grade-B-yellow)
![Last Eval](https://img.shields.io/badge/eval-2026--04--16-blue)
<!-- harness-eval-badge:end -->
