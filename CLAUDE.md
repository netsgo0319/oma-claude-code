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

**0. 마이그레이션 전후 결과가 같아야 한다. EXPLAIN만으로 끝내지 마라.**
동일 입력으로 Oracle/PostgreSQL 실행 시 결과가 동일해야 한다 (SELECT: 행/값, DML: affected rows).
EXPLAIN 통과 ≠ 변환 성공. Oracle 접속이 가능하면 **`--compare`를 반드시 실행**하라.
--compare 없이 Phase 4로 넘어가면 실제 데이터 불일치를 못 잡는다.
쿼리가 많으면(100+) Validator 서브에이전트 여러 개에 `--files` 옵션으로 **병렬 배치**하라.

**1. Phase를 절대 건너뛰지 마라.**
Phase 0→1→2→2.5→3→3.5→4→5→6→7 순서 필수. 순서 변경 제안 금지. unconverted가 있으면 Phase 2에서 LLM 완료 후 진행. DB 미연결 시에만 Phase 2.5/3 스킵 가능.

**2. 이미 만들어진 도구만 사용하라. 스크립트를 새로 작성하지 마라.**

**3. SQL LLM 변환은 Converter, DB 실행은 Validator, 실패 분석은 Reviewer, 학습은 Learner에 위임.**

## 도구

| 도구 | 용도 | 실행 |
|------|------|------|
| `tools/batch-process.sh` | **Phase 1 일괄 병렬 (parse+analyze+convert)** | `bash tools/batch-process.sh --all --parallel 8` |
| `tools/generate-test-cases.py` | **Phase 2.5 TC 생성** | `python3 tools/generate-test-cases.py` |
| `tools/validate-queries.py` | Phase 3 검증 | 아래 Phase 3 참고 |
| `tools/run-extractor.sh` | Phase 3.5 MyBatis 검증 | `bash tools/run-extractor.sh [--validate]` |
| `tools/generate-report.py` | Phase 7 HTML 리포트 | `python3 tools/generate-report.py` |
| `tools/sync-tracking-to-xml.py` | tracking→XML 동기화 | `python3 tools/sync-tracking-to-xml.py` |
| `tools/reset-workspace.sh` | 초기화 | `bash tools/reset-workspace.sh --force` |

개별 도구: `xml-splitter.py`, `parse-xml.py`, `query-analyzer.py`, `oracle-to-pg-converter.py`

## 서브에이전트 호출 (Agent tool)

`.claude/agents/` 디렉토리에 정의된 에이전트를 `subagent_type`으로 호출:

```
Agent({
  description: "Phase 2: LLM 변환 - {filename}",
  subagent_type: "converter",
  prompt: "대상 파일: {filename}, unconverted 패턴을 LLM으로 변환하라."
})
```

| 에이전트 | 파일 | 모델 | 역할 |
|---------|------|------|------|
| converter | .claude/agents/converter.md | sonnet | Oracle→PG 변환 (룰+LLM) |
| test-generator | .claude/agents/test-generator.md | opus | Oracle 딕셔너리 기반 TC |
| validator | .claude/agents/validator.md | sonnet | EXPLAIN/실행/비교 검증 |
| reviewer | .claude/agents/reviewer.md | opus | 실패 분석 + DBA 최종 검증 |
| learner | .claude/agents/learner.md | sonnet | 에지케이스 학습 + PR |

**배치 크기:** 1개당 최대 30쿼리 또는 3파일. 큰 파일은 쿼리 ID로 분할. 동시 여러 Agent spawn 가능.

## Phase별 실행

### Phase 0: Pre-flight Check

| 항목 | 확인 방법 | 필수 |
|------|----------|------|
| XML 파일 | `ls workspace/input/*.xml` | **필수** |
| sqlplus | `which sqlplus` | 선택 (없으면 Phase 2.5 스킵) |
| psql | `which psql` | 선택 (없으면 Phase 3 스킵) |
| Oracle 접속 | sqlplus로 SELECT 1 FROM DUAL | 선택 |
| PG 접속 | psql로 SELECT 1 | 선택 |

### Phase 1: Parse + Analyze + Rule Convert

```bash
bash tools/batch-process.sh --all --parallel 8
```
전체 파일의 split → parse → analyze → rule convert를 병렬 처리. 이미 처리된 파일 자동 스킵.

### Phase 2: LLM Convert (unconverted 패턴)

unconverted 패턴이 남아있으면 **반드시** Converter 서브에이전트에 위임.
**병렬 배치:** 3파일/30쿼리 단위로 Converter 여러 개에 동시 위임.

### Phase 2.5: Test Case 생성

**sqlplus 있으면 필수.**
```bash
python3 tools/generate-test-cases.py
```

### Phase 3: Validation (EXPLAIN + Compare)

**반드시 validate-queries.py 사용. Oracle 접속 가능하면 --compare 필수.**

```bash
# Step 1: EXPLAIN (빠름 — 직접 실행 가능)
python3 tools/validate-queries.py --local --output workspace/results/_validation/ --tracking-dir workspace/results/
```

**Step 2: Compare — 배치 SQL 파일 방식으로 실행 (빠름)**
validate-queries.py의 --compare는 쿼리당 subprocess를 띄워서 느림. 대신 **배치 SQL 파일**을 생성하고 psql/sqlplus로 한번에 실행하라:

```bash
# 1) generate가 explain_test.sql + execute_test.sql을 생성
python3 tools/validate-queries.py --generate --output workspace/results/_validation/ --tracking-dir workspace/results/

# 2) PG: psql로 배치 실행 (수천 쿼리를 한번에 — 빠름)
PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DATABASE \
  -f workspace/results/_validation/explain_test.sql \
  > workspace/results/_validation/explain_results.txt 2>&1

PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DATABASE \
  -f workspace/results/_validation/execute_test.sql \
  > workspace/results/_validation/execute_results.txt 2>&1

# 3) Oracle: sqlplus로 동일 쿼리 배치 실행 (비교용)
# sqlplus에서는 explain_test.sql을 Oracle 원본 SQL 버전으로 생성하여 실행

# 4) 결과 파싱
python3 tools/validate-queries.py --parse-results --output workspace/results/_validation/ --tracking-dir workspace/results/
```

**핵심: psql -f / sqlplus @파일 로 한번에 실행하면 프로세스 오버헤드 없이 수천 쿼리를 초 단위로 처리.**
**validate-queries.py --compare는 쿼리가 많을 때 쓰지 마라 (subprocess per query = 느림).**

쿼리가 많으면(100+) Validator 서브에이전트에 배치 분배도 가능 (`--files` 옵션).

### Phase 3.5: MyBatis Engine Validation (Java 있을 때)

**Phase 4 (힐링) 전에 실행.** 동적 SQL을 MyBatis 엔진이 정확히 resolve.
```bash
bash tools/run-extractor.sh --validate
python3 tools/validate-queries.py --compare --extracted workspace/results/_extracted/ --output workspace/results/_validation_phase7/
```

### Phase 4: Self-healing

Phase 3 + 3.5 실패 건 모두 대상. 루프: Reviewer → Converter → Validator. 최대 3회.
**병렬 힐링:** 10~20건 단위 배치. 쿼리 간 병렬.

### Phase 5: Learning

Learner 서브에이전트 → steering 갱신 + PR + **main으로 checkout 복귀**.

### Phase 6: DBA/Expert Final Review (필수)

Reviewer 서브에이전트에 위임. 검증 항목:
1. XML 문법, 태그 구조, 동적 SQL 보존
2. include 참조 무결성, 파라미터 바인딩
3. Oracle 잔여 패턴, CDATA, selectKey
4. **Phase 완료 점검**: 모든 Phase 실행됐는지, --compare 실행됐는지, TC 사용됐는지

결과: `workspace/results/_dba_review/review-result.json`

### Phase 7: Report (마지막)

```bash
python3 tools/generate-report.py
```
→ workspace/reports/migration-report.html (Phase 6 완료 후에만)

## progress.json

매 Phase 전환 시 갱신. 쿼리별 상세는 query-tracking.json에 분리.

## 상태 표시 (매 응답 시작에 필수)

```
[DONE] Phase 0~2  [>>  ] Phase 3 (80/150)  [    ] Phase 3.5~7
Progress: 80/150 (53%) | OK:80 FAIL:0 WAIT:70 ESC:0
```

## Resume (중단 후 재개)

progress.json 읽고 "done" Phase 건너뜀, "running" Phase → 미완료부터 재개.

## 초기화

`bash tools/reset-workspace.sh --force` — input 보존, 나머지 삭제.

## 로깅

**모든 활동을 workspace/logs/activity-log.jsonl에 기록 (필수).**
도구가 자동 기록. 서브에이전트 호출/Phase 전환은 직접 기록.

## 변환 룰셋 참조

작업 전 반드시 Read:
- `steering/oracle-pg-rules.md` — 40+ 변환 룰
- `steering/edge-cases.md` — 학습된 에지케이스
