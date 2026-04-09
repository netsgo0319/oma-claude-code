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

### 1. 이미 만들어진 도구를 사용하라. 절대 스크립트를 새로 작성하지 마라.

| 도구 | Phase | 실행 방법 |
|------|-------|----------|
| `tools/xml-splitter.py` | 1 | `python3 tools/xml-splitter.py {input} {output_dir}` |
| `tools/parse-xml.py` | 1 | `python3 tools/parse-xml.py {chunks_dir} {output_json}` |
| `tools/query-analyzer.py` | 1.5 | `python3 tools/query-analyzer.py {parsed.json}` |
| `tools/oracle-to-pg-converter.py` | 2 | `python3 tools/oracle-to-pg-converter.py {input} {output} --report {report}` |
| `tools/validate-queries.py` | 3 | `python3 tools/validate-queries.py --generate/--local/--execute` |
| `tools/generate-report.py` | 6 | `python3 tools/generate-report.py` |
| `tools/run-extractor.sh` | 7 | `bash tools/run-extractor.sh [--validate] [--execute]` |
| `tools/reset-workspace.sh` | 초기화 | `bash tools/reset-workspace.sh --force` |

**금지:**
- Python 파서/변환기를 새로 작성하는 것
- XML을 직접 읽어서 LLM으로 파싱하는 것
- "스크립트를 작성하겠습니다" → 이 생각이 들면 멈추고 tools/ 확인

### 2. Leader가 직접 하는 것 vs 서브에이전트 위임

**직접 실행 (Bash tool):**
- Phase 0 사전 점검
- Phase 1 도구 실행 (xml-splitter, parse-xml)
- Phase 1.5 도구 실행 (query-analyzer)
- Phase 2 기계적 변환 (oracle-to-pg-converter.py)
- Phase 6 리포트 생성 (generate-report.py)
- Phase 7 MyBatis 엔진 추출 (run-extractor.sh)

**Agent tool로 서브에이전트 위임:**
- Phase 2 LLM 변환 (unconverted 패턴) → converter (model: sonnet)
- Phase 2.5 테스트 케이스 생성 → test-generator (model: opus)
- Phase 3 검증 → validator (model: sonnet)
- Phase 4 셀프 힐링 → reviewer (model: opus) → converter → validator 루프
- Phase 5 학습 → learner (model: sonnet)

### 3. 서브에이전트 호출 패턴

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
| reviewer | .claude/agents/reviewer.md | opus | 실패 분석 + SQL 수정안 |
| learner | .claude/agents/learner.md | sonnet | 에지케이스 학습 + PR |

병렬 처리: 같은 레이어 내 독립적인 파일은 여러 Agent를 동시에 spawn할 수 있다.

## 워크플로우

### Phase 0: Pre-flight Check

```bash
# XML 파일 존재 확인
ls workspace/input/*.xml 2>/dev/null | head -20

# CLI 도구 확인
which sqlplus 2>/dev/null && echo "sqlplus: OK" || echo "sqlplus: NOT FOUND"
which psql 2>/dev/null && echo "psql: OK" || echo "psql: NOT FOUND"

# Oracle 접속 확인 (sqlplus 있을 때만)
echo "SELECT 1 FROM DUAL;" | sqlplus -S ${ORACLE_USER}/${ORACLE_PASSWORD}@${ORACLE_HOST}:${ORACLE_PORT}/${ORACLE_SID} 2>&1 | head -5

# PostgreSQL 접속 확인 (psql 있을 때만)
PGPASSWORD=${PG_PASSWORD} psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${PG_DATABASE} -c "SELECT 1" 2>&1 | head -3
```

결과에 따라:
- 전부 OK → Phase 1 진행
- XML만 OK, DB 미연결 → "Phase 1~2만 가능" 안내 후 사용자 확인
- XML 없음 → 중단, 안내

### Phase 1: 스캔 & 파싱

1. `wc -l workspace/input/*.xml` 로 크기 확인
2. 1000줄 이상: `python3 tools/xml-splitter.py workspace/input/{file}.xml workspace/results/{file}/v1/chunks/`
3. 파싱: `python3 tools/parse-xml.py workspace/results/{file}/v1/chunks/ workspace/results/{file}/v1/parsed.json`
4. progress.json 초기화

### Phase 1.5: 의존성 분석 & 복잡도 분류

1. `python3 tools/query-analyzer.py workspace/results/{file}/v1/parsed.json`
2. 산출물: dependency-graph.json, complexity-scores.json, conversion-order.json
3. 레벨별 통계 출력: "L0:{a}개, L1:{b}개, L2:{c}개, L3:{d}개, L4:{e}개"

### Phase 2: 레이어별 변환

1. 기계적 변환 (Leader 직접): `python3 tools/oracle-to-pg-converter.py workspace/input/{file}.xml workspace/output/{file}.xml --report workspace/results/{file}/v1/conversion-report.json`
2. conversion-report.json 확인 → unconverted가 있으면 converter 서브에이전트 위임
3. 레이어 순서대로 (Layer 0 → 1 → 2 → ...), 같은 레이어 내 병렬 가능
4. 현재 레이어 완료 후 다음 레이어로

### Phase 2.5: 테스트 케이스 생성

test-generator 서브에이전트에 위임 (Oracle DB 접속 필요).
산출물: workspace/results/{file}/v{n}/test-cases.json

### Phase 3: 검증

1. 스크립트 생성: `python3 tools/validate-queries.py --generate --output workspace/results/_validation/`
2. EXPLAIN 검증: `python3 tools/validate-queries.py --local --output workspace/results/_validation/`
3. 실행 검증: `python3 tools/validate-queries.py --execute --output workspace/results/_validation/`
4. 필요 시 validator 서브에이전트로 Oracle/PG 비교 검증 위임

### Phase 4: 셀프 힐링

validated.json에 fail이 있으면 자동 진입:
```
실패 건 → reviewer 서브에이전트 (원인 분석 + 수정안)
       → converter 서브에이전트 (재변환, v{n+1})
       → validator 서브에이전트 (재검증)
       → 성공? 완료 : 재시도 (최대 3회)
       → 3회 실패 → 사용자 에스컬레이션
```

### Phase 5: 학습

learner 서브에이전트에 위임. 반복 패턴 → steering 갱신 + PR 생성.

### Phase 6: 리포트

```bash
python3 tools/generate-report.py --output workspace/reports/migration-report.html
```

### Phase 7: MyBatis 엔진 검증 (옵셔널, Java 필요)

```bash
bash tools/run-extractor.sh [--validate] [--execute]
```

Java 미설치 시 스킵.

## progress.json 관리

매 Phase 전환, 매 서브에이전트 완료 시 반드시 갱신.

```json
{
  "_pipeline": {
    "current_phase": "phase_2",
    "current_phase_name": "레이어별 변환",
    "started_at": "2026-04-09T12:00:00Z",
    "phases_completed": ["phase_0", "phase_1", "phase_1.5"],
    "phases_remaining": ["phase_2", "phase_2.5", "phase_3", "phase_4", "phase_5", "phase_6"],
    "current_layer": 1,
    "total_layers": 4,
    "summary": { "success": 80, "fail": 5, "pending": 65, "escalated": 0 }
  },
  "files": {
    "UserMapper.xml": {
      "current_version": 1,
      "status": "converting",
      "complexity_level": "L2",
      "layer": 1,
      "totalQueries": 10,
      "oraclePatterns": {"NVL": 3, "SYSDATE": 2}
    }
  }
}
```

## 상태 표시 (매 응답 시작에 필수)

```
======================================
>>> Phase 2: 레이어별 변환 (Layer 1/4)
======================================
[DONE] Phase 0: 사전 점검 완료
[DONE] Phase 1: 파싱 완료 (12파일, 150쿼리)
[>>  ] Phase 2: 변환 중 (Layer 1/4, 80/150 완료)
[    ] Phase 3: 검증
[    ] Phase 4: 셀프 힐링
[    ] Phase 5: 학습
[    ] Phase 6: 리포트
Progress: 80/150 (53%) | OK:80 FAIL:0 WAIT:70
======================================
```

## 감사 로그 (필수)

모든 활동을 `workspace/logs/activity-log.jsonl`에 기록.

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
    _extracted/   Phase 7 MyBatis 추출 결과
  reports/      리포트 (HTML, Markdown)
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
| query-analyzer | skills/query-analyzer/SKILL.md | Phase 1.5 |
| cross-file-analyzer | skills/cross-file-analyzer/SKILL.md | Phase 1.5 |
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
| report | skills/report/SKILL.md | Phase 6 |
| learn-edge-case | skills/learn-edge-case/SKILL.md | Phase 5 |

## Oracle→PostgreSQL 변환 룰

전체 룰셋은 `steering/oracle-pg-rules.md` 참조. Learner가 갱신하므로 항상 최신 파일을 Read하라.

## 초기화

사용자가 "초기화해줘", "리셋" 요청 시:
```bash
bash tools/reset-workspace.sh --force
```
workspace/input/ 보존, 나머지 삭제.

## 대시보드

사용자에게 안내만:
```
별도 터미널에서: cd workspace && python3 -m http.server 8080
브라우저: http://localhost:8080/dashboard.html
```
**절대 python3 -m http.server를 Bash로 직접 실행하지 마라.**

## 환경변수

```bash
# Oracle (소스)
ORACLE_HOST, ORACLE_PORT, ORACLE_SID, ORACLE_USER, ORACLE_PASSWORD

# PostgreSQL (타겟)
PG_HOST, PG_PORT, PG_DATABASE, PG_SCHEMA, PG_USER, PG_PASSWORD
```
