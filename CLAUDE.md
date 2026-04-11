# OMA — Oracle Migration Accelerator (Claude Code Edition)

MyBatis/iBatis XML 기반 Oracle SQL을 PostgreSQL로 자동 변환, 검증, 학습하는 에이전트 시스템.

## 트리거 인식

사용자가 아래 표현을 하면 **자동으로 전체 파이프라인(Phase 0~7)을 실행**한다:
- "변환해줘", "convert", "마이그레이션", "시작", "전체 수행"

사용자가 특정 Phase만 요청하면 해당 Phase만 실행:
- "Phase 1~2만 해줘" → 파싱+변환만
- "X파일만 변환해줘" → 특정 파일만 처리
- "다시 검증해줘" → 에스컬레이션 건 재검증

## 핵심 원칙

**0. 마이그레이션 전후 결과가 같아야 한다.**
동일 입력으로 Oracle/PostgreSQL 실행 시 결과가 동일해야 한다 (SELECT: 행/값, DML: affected rows). EXPLAIN 통과만으로는 불충분. --compare 검증이 필수.

**1. Phase를 절대 건너뛰지 마라.**
Phase 0→1→2→2.5→3→3.5→4→5→6→7 순서 필수. 순서 변경 제안 금지. unconverted가 있으면 Phase 2에서 LLM 완료 후 진행. DB 미연결 시에만 Phase 2.5/3 스킵 가능.

**2. 이미 만들어진 도구만 사용하라. 스크립트를 새로 작성하지 마라.**

**금지:**
- Python 파서/변환기를 새로 작성하는 것
- XML을 직접 읽어서 LLM으로 파싱하는 것
- "스크립트를 작성하겠습니다" → 이 생각이 들면 멈추고 tools/ 확인

**3. SQL LLM 변환은 Converter, DB 실행은 Validator, 실패 분석은 Reviewer, 학습은 Learner에 위임.**

## 도구

| 도구 | 용도 | 실행 |
|------|------|------|
| `tools/batch-process.sh` | **Phase 1 일괄 병렬 (parse+analyze+convert)** | `bash tools/batch-process.sh --all --parallel 8` |
| `tools/xml-splitter.py` | Phase 1 대형 XML 분할 | `python3 tools/xml-splitter.py {input} {output_dir}` |
| `tools/parse-xml.py` | Phase 1 XML 파싱 | `python3 tools/parse-xml.py {chunks_dir} {output_json}` |
| `tools/query-analyzer.py` | Phase 1 의존성/복잡도 분석 | `python3 tools/query-analyzer.py {parsed.json}` |
| `tools/oracle-to-pg-converter.py` | Phase 1/2 룰 기반 변환 | `python3 tools/oracle-to-pg-converter.py {input} {output} --report {report}` |
| `tools/generate-test-cases.py` | **Phase 2.5 TC 생성** | `python3 tools/generate-test-cases.py` |
| `tools/validate-queries.py` | Phase 3 검증 | 아래 Phase 3 참고 |
| `tools/run-extractor.sh` | Phase 3.5 MyBatis 검증 | `bash tools/run-extractor.sh [--validate]` |
| `tools/generate-report.py` | Phase 7 HTML 리포트 | `python3 tools/generate-report.py` |
| `tools/tracking_utils.py` | 쿼리 추적 유틸리티 | 도구 내부에서 import |
| `tools/reset-workspace.sh` | 초기화 | `bash tools/reset-workspace.sh --force` |

## Leader가 직접 하는 것 vs 서브에이전트 위임

**직접 실행 (Bash tool):**
- Phase 0 사전 점검
- Phase 1 도구 실행 (batch-process.sh 또는 개별 도구)
- Phase 2 기계적 변환 (oracle-to-pg-converter.py)
- Phase 2.5 테스트 케이스 생성 (generate-test-cases.py)
- Phase 7 리포트 생성 (generate-report.py)

**Agent tool로 서브에이전트 위임:**
- Phase 2 LLM 변환 (unconverted 패턴) → converter (model: sonnet)
- Phase 2.5 대량 TC 생성 → test-generator (model: opus)
- Phase 3 검증 → validator (model: sonnet)
- Phase 3.5 MyBatis 검증 후 추가 검증 → validator
- Phase 4 셀프 힐링 → reviewer (model: opus) → converter → validator 루프
- Phase 5 학습 → learner (model: sonnet)
- Phase 6 DBA/Expert Review → reviewer (model: opus)

## 서브에이전트 호출 패턴

`.claude/agents/` 디렉토리에 정의된 에이전트를 `subagent_type`으로 호출한다:

```
Agent({
  description: "Phase 2: LLM 변환 - {filename}",
  subagent_type: "converter",
  prompt: "대상 파일: {filename}, 버전: v{n}, conversion-report.json의 unconverted 패턴을 LLM으로 변환하라."
})
```

에이전트 정의 파일: `.claude/agents/{agent-name}.md`
각 에이전트는 frontmatter에 model, allowed-tools, description이 정의되어 있다.

| 에이전트 | 파일 | 모델 | 역할 |
|---------|------|------|------|
| converter | .claude/agents/converter.md | sonnet | Oracle→PG 변환 (룰+LLM) |
| test-generator | .claude/agents/test-generator.md | opus | Oracle 딕셔너리 기반 테스트 |
| validator | .claude/agents/validator.md | sonnet | EXPLAIN/실행/비교 검증 |
| reviewer | .claude/agents/reviewer.md | opus | 실패 분석 + SQL 수정안 + DBA Review |
| learner | .claude/agents/learner.md | sonnet | 에지케이스 학습 + PR |

**배치 크기 (모든 서브에이전트 공통):**
- 1개당 최대 **30쿼리** 또는 **3파일**
- 큰 파일은 쿼리 ID로 분할하여 분배
- 가능한 한 **동시에 여러 서브에이전트를 위임**하여 병렬 처리

병렬 처리: 같은 레이어 내 독립적인 파일은 여러 Agent를 동시에 spawn할 수 있다.
기타: 구체적 파일 경로/버전 전달, 반환값은 한 줄 요약, 동일 파일 중복 할당 금지.

## 워크플로우

### Phase 0: Pre-flight Check

| 항목 | 확인 방법 | 필수 |
|------|----------|------|
| XML 파일 | `ls workspace/input/*.xml` | **필수** |
| sqlplus | `which sqlplus` | 선택 (없으면 Phase 2.5 스킵) |
| psql | `which psql` | 선택 (없으면 Phase 3 스킵) |
| Oracle 접속 | sqlplus로 SELECT 1 FROM DUAL | 선택 |
| PG 접속 | psql로 SELECT 1 | 선택 |

결과에 따라:
- 전부 OK → Phase 1 진행
- XML만 OK, DB 미연결 → "Phase 1~2만 가능" 안내 후 사용자 확인
- XML 없음 → 중단, 안내

### Phase 1: Parse + Analyze + Rule Convert

```bash
bash tools/batch-process.sh --all --parallel 8
```
전체 파일의 split → parse → analyze → rule convert를 병렬 처리. 이미 처리된 파일 자동 스킵.

**크로스 파일 분석 (대규모):** cross-file-analyzer 스킬로 파일 간 변환 순서 결정.

### Phase 2: LLM Convert (unconverted 패턴)

unconverted 패턴이 남아있으면 **반드시** Converter 서브에이전트에 위임.

**병렬 배치:** 3파일/30쿼리 단위로 Converter 여러 개에 동시 위임.

레이어 순서대로 (Layer 0 → 1 → 2 → ...), 같은 레이어 내 병렬 가능.
현재 레이어 완료 후 다음 레이어로.

### Phase 2.5: Test Case 생성

**sqlplus 있으면 필수.**
```bash
python3 tools/generate-test-cases.py
```

**병렬 배치 (서브에이전트):** 파일이 많으면 Test Generator 여러 개에 분배.

### Phase 3: Validation (EXPLAIN + Compare)

**반드시 validate-queries.py 사용. Oracle 접속 가능하면 --compare 필수.**

Oracle 접속 가능 시:
```bash
python3 tools/validate-queries.py --local --output workspace/results/_validation/ --tracking-dir workspace/results/
python3 tools/validate-queries.py --compare --output workspace/results/_validation/ --tracking-dir workspace/results/
```

Oracle 접속 불가 시:
```bash
python3 tools/validate-queries.py --local --output workspace/results/_validation/ --tracking-dir workspace/results/
python3 tools/validate-queries.py --execute --output workspace/results/_validation/ --tracking-dir workspace/results/
```

**병렬 배치:** 파일이 많으면 Validator 여러 개에 `--files` 옵션으로 분배.

### Phase 3.5: MyBatis Engine Validation (Java 있을 때)

**Phase 4 (힐링) 전에 실행.** MyBatis 엔진이 동적 SQL을 정확히 resolve한 SQL로 검증.
```bash
bash tools/run-extractor.sh --validate
```

**Oracle 접속 가능하면 Phase 3.5에서도 --compare 필수:**
```bash
python3 tools/validate-queries.py --compare --extracted workspace/results/_extracted/ --output workspace/results/_validation_phase7/ --tracking-dir workspace/results/
```

Phase 3보다 정확 (동적 SQL 분기 resolve). Java 없으면 스킵 가능 (사용자에게 안내).

### Phase 4: Self-healing

Phase 3 + Phase 3.5 실패 건 모두 대상. 없으면 Phase 5로.

루프: Reviewer → Converter → Validator. 최대 3회.
상태 전이: validating → retry_1 → retry_2 → retry_3 → escalated (또는 → success).

**병렬 힐링:** 10~20건 단위 배치. 쿼리 간 병렬, 쿼리 내 retry는 순차.

### Phase 5: Learning

Learner 서브에이전트가:
1. 반복 실패→성공 패턴 → oracle-pg-rules.md 룰 추가
2. 새 LLM 패턴 → edge-cases.md 등록
3. Git branch + PR 자동 생성 → **main으로 checkout 복귀**

### Phase 6: DBA/Expert Final Review (필수)

**output XML의 최종 품질을 검증한다. 보고서 생성 전 마지막 관문.**

Reviewer 서브에이전트에 위임하여 아래 항목을 검증:
1. **MyBatis XML 문법**: 모든 output XML이 valid XML인지 (파싱 에러 없음)
2. **태그 구조**: `<select>`, `<insert>`, `<update>`, `<delete>` 태그가 올바르게 닫혔는지
3. **동적 SQL 보존**: `<if>`, `<choose>`, `<foreach>` 등 동적 태그가 원본과 동일하게 보존됐는지
4. **include 참조 무결성**: `<include refid="X">` 가 참조하는 `<sql id="X">`가 모두 존재하는지
5. **파라미터 바인딩**: `#{param}` 이 원본과 동일한지 (누락/변경 없음)
6. **PostgreSQL 잔여 패턴**: 변환 후에도 Oracle 구문이 남아있지 않은지 (SYSDATE, NVL, ROWNUM 등)
7. **CDATA 블록**: CDATA 안의 SQL이 올바르게 변환됐는지
8. **selectKey**: sequence 변환이 올바른지 (NEXTVAL → nextval)

**파이프라인 완료 점검 (Phase 6에서 함께 수행):**
9. **Phase 완료 확인**: Phase 0~5가 모두 실행됐는지 점검. 빠진 Phase가 있으면 보고
10. **EXPLAIN 검증 완료**: 전체 쿼리에 대해 EXPLAIN이 실행됐는지 (validation_total > 0)
11. **Compare 검증 완료**: Oracle 접속 가능했으면 --compare 실행됐는지 (compare_total > 0)
12. **테스트 케이스 사용**: test-cases.json이 활용됐는지 (더미 값 '1'이 아닌 실제 바인드 값)
13. **에스컬레이션 처리**: 에스컬레이션된 쿼리가 사용자에게 보고됐는지

검증 결과를 `workspace/results/_dba_review/review-result.json`에 저장.
문제 발견 시 목록과 함께 사용자에게 보고. Phase 4로 돌아가지 않음 (보고만).

### Phase 7: Report (마지막)

```bash
python3 tools/generate-report.py
```
→ workspace/reports/migration-report.html

**Phase 6 (DBA Review) 완료 후에만 실행.** 모든 검증 결과를 포함.

## progress.json 관리

매 Phase 전환, 매 서브에이전트 완료 시 반드시 갱신.
전체 상태 + 파일별 상태 추적. 쿼리별 상세는 query-tracking.json에 분리 (`tracking_file` 참조).

```json
{
  "_pipeline": {
    "current_phase": "phase_3",
    "phases": {
      "phase_0": {"status": "done", "duration_ms": 5000},
      "phase_1": {"status": "done", "duration_ms": 55000},
      "phase_3": {"status": "running"}
    },
    "summary": {"success": 80, "fail": 5, "pending": 65, "escalated": 0}
  },
  "UserMapper.xml": {
    "status": "validating",
    "queries_total": 10, "queries_success": 6, "queries_fail": 0,
    "tracking_file": "workspace/results/UserMapper.xml/v1/query-tracking.json"
  }
}
```

## 상태 표시 (매 응답 시작에 필수)

```
[DONE] Phase 0~2  [>>  ] Phase 3 (80/150)  [    ] Phase 3.5~7
Progress: 80/150 (53%) | OK:80 FAIL:0 WAIT:70 ESC:0
```

## Resume (중단 후 재개)

시작 시 progress.json 읽고:
1. "done" Phase 건너뜀
2. "running" Phase → 미완료 파일/쿼리부터 재개
3. Phase 2 재개 시 `current_layer` 확인하여 해당 레이어부터

## 에스컬레이션 후 재개

사용자가 "X 쿼리 수정했어" → progress.json 확인 → 새 버전 → Validator 재검증 → Learner 학습.

## 감사 로그 (필수)

**모든 활동을 workspace/logs/activity-log.jsonl에 기록.**
도구가 자동 기록하지만, 서브에이전트 호출/Phase 전환/에스컬레이션은 Leader가 직접 기록.

로그 타입: PHASE_START, PHASE_END, DECISION, ATTEMPT, SUCCESS, ERROR, FIX, ESCALATION, HUMAN_INPUT, LEARNING, WARNING

```json
{"timestamp":"2026-04-09T12:00:00Z","type":"PHASE_START","phase":"phase_1","detail":"파싱 시작, 12개 XML 파일"}
```

## 디렉토리 구조

```
workspace/
  input/        변환 대상 XML (불변)
  output/       변환 완료 XML
  results/      버전별 중간 결과 (JSON)
    _validation/  EXPLAIN/실행 검증 결과
    _extracted/   Phase 3.5 MyBatis 추출 결과
    _dba_review/  Phase 6 DBA 리뷰 결과
  reports/      리포트 (HTML)
  logs/         감사 로그
  progress.json 진행 상황

tools/          Python/Java/Shell 도구 (수정 금지)
skills/         스킬 참조 문서 (SKILL.md + references)
steering/       변환 룰셋 + 에지케이스 (Learner가 갱신)
schemas/        JSON Schema (에이전트 간 통신 계약)
```

## 스킬 참조

서브에이전트에게 작업 위임 시, 해당 스킬의 SKILL.md와 references를 Read하여 프롬프트에 포함하라.

| 스킬 | 경로 | 사용처 |
|------|------|--------|
| parse-xml | skills/parse-xml/SKILL.md | Phase 1 |
| query-analyzer | skills/query-analyzer/SKILL.md | Phase 1 |
| cross-file-analyzer | skills/cross-file-analyzer/SKILL.md | Phase 1 |
| rule-convert | skills/rule-convert/SKILL.md | Phase 2 (converter) |
| llm-convert | skills/llm-convert/SKILL.md | Phase 2 (converter) |
| param-type-convert | skills/param-type-convert/SKILL.md | Phase 2 (converter) |
| complex-query-decomposer | skills/complex-query-decomposer/SKILL.md | Phase 2 (L3-L4) |
| extract-sql | skills/extract-sql/SKILL.md | Phase 2 (converter) |
| xml-splitter | skills/xml-splitter/SKILL.md | Phase 1 |
| rule-convert-tool | skills/rule-convert-tool/SKILL.md | Phase 2 |
| generate-test-cases | skills/generate-test-cases/SKILL.md | Phase 2.5 |
| explain-test | skills/explain-test/SKILL.md | Phase 3 (validator) |
| execute-test | skills/execute-test/SKILL.md | Phase 3 (validator) |
| compare-test | skills/compare-test/SKILL.md | Phase 3 (validator) |
| db-oracle | skills/db-oracle/SKILL.md | Phase 2.5, 3 |
| db-postgresql | skills/db-postgresql/SKILL.md | Phase 3 |
| audit-log | skills/audit-log/SKILL.md | 전체 |
| report | skills/report/SKILL.md | Phase 7 |
| learn-edge-case | skills/learn-edge-case/SKILL.md | Phase 5 |

## 초기화

사용자가 "초기화해줘", "리셋" 요청 시:
```bash
bash tools/reset-workspace.sh --force
```
workspace/input/ 보존, 나머지 삭제.

## 환경변수

```bash
# Oracle (소스)
ORACLE_HOST, ORACLE_PORT, ORACLE_SID, ORACLE_USER, ORACLE_PASSWORD

# PostgreSQL (타겟)
PG_HOST, PG_PORT, PG_DATABASE, PG_SCHEMA, PG_USER, PG_PASSWORD
```

## 변환 룰셋 참조
작업 전 반드시 `steering/oracle-pg-rules.md`와 `steering/edge-cases.md`를 Read하라.
