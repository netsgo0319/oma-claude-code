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
| `tools/generate-healing-tickets.py` | **Phase 4 힐링 티켓 생성** | `python3 tools/generate-healing-tickets.py` |
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

### Phase 0: Pre-flight Check + 환경 설치

| 항목 | 확인 방법 | 필수 | 미설치 시 |
|------|----------|------|----------|
| XML 파일 | `ls workspace/input/*.xml` | **필수** | 중단 |
| Python 3 | `python3 --version` | **필수** | 설치 안내 |
| psql | `which psql` | 선택 | `brew install postgresql` 또는 `apt install postgresql-client` 안내 |
| sqlplus | `which sqlplus` | 선택 | Oracle Instant Client 설치 안내 |
| Java 11+ | `java -version` | **권장** (Phase 3.5) | `brew install openjdk@21` 또는 `apt install default-jdk` 안내 |
| Gradle | — | 불필요 | **레포에 gradlew 포함됨.** Java만 있으면 `tools/mybatis-sql-extractor/gradlew`가 Gradle을 자동 다운로드 |
| Oracle 접속 | sqlplus로 SELECT 1 FROM DUAL | 선택 | 환경변수 확인 안내 |
| PG 접속 | psql로 SELECT 1 | 선택 | 환경변수 확인 안내 |

**미설치 도구가 있으면 설치 명령을 사용자에게 안내하라. 자동 설치하지 마라 (sudo 필요).**
**Java만 있으면 Phase 3.5 실행 가능 (Gradle 별도 설치 불필요, gradlew가 자동 처리).**
**Java가 없으면 Phase 3.5를 스킵할 수 있다고 안내하되, 설치를 강력 권장하라. Phase 3.5 없이는 동적 SQL 검증이 불완전하다.**

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

### Phase 3: Validation (3단계: EXPLAIN → 실행 → 비교)

**3단계 모두 실행해야 한다. Stage 1만 하고 넘어가지 마라.**
**Oracle 접속 가능하면 Stage 2, 3 필수. 건너뛰면 안 된다.**

**Stage 1: EXPLAIN (PG 문법 검증)**
```bash
python3 tools/validate-queries.py --generate --output workspace/results/_validation/ --tracking-dir workspace/results/
psql -f workspace/results/_validation/explain_test.sql > workspace/results/_validation/explain_results.txt 2>&1
python3 tools/validate-queries.py --parse-results --output workspace/results/_validation/
```

**Stage 2: 실행 (TC 바인드로 양쪽 실행)**
```bash
# PG 실행
psql -f workspace/results/_validation/execute_test.sql > workspace/results/_validation/execute_results.txt 2>&1
# Oracle 실행 (같은 TC, 원본 SQL)
sqlplus @workspace/results/_validation/oracle_compare.sql > workspace/results/_validation/oracle_results.txt 2>&1
```

**Stage 3: 비교 (Oracle vs PG 결과 매칭)**
```bash
python3 tools/validate-queries.py --parse-results --output workspace/results/_validation/
```
양쪽 결과 파일에서 test_id별로 row count를 비교. 불일치 시 Phase 4 대상.

**동적 SQL 쿼리는 Phase 3.5에서 MyBatis로 해결.**

### Phase 3.5: MyBatis Engine (양쪽 추출 + 비교)

**Java가 설치되어 있으면 반드시 실행. 건너뛰지 마라.**

```bash
# Step 1: 양쪽 SQL 추출
bash tools/run-extractor.sh --validate

# Step 2: 추출된 SQL로 배치 스크립트 생성 (--compare 쓰지 마라, OOM 위험)
python3 tools/validate-queries.py --generate --extracted workspace/results/_extracted/ --output workspace/results/_validation_phase7/ --tracking-dir workspace/results/

# Step 3: psql/sqlplus 배치 실행 (빠름)
PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DATABASE \
  -f workspace/results/_validation_phase7/explain_test.sql \
  > workspace/results/_validation_phase7/explain_results.txt 2>&1

PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DATABASE \
  -f workspace/results/_validation_phase7/execute_test.sql \
  > workspace/results/_validation_phase7/execute_results.txt 2>&1

sqlplus -S $ORACLE_USER/$ORACLE_PASSWORD@$ORACLE_HOST:$ORACLE_PORT/$ORACLE_SID \
  @workspace/results/_validation_phase7/oracle_compare.sql \
  > workspace/results/_validation_phase7/oracle_results.txt 2>&1

# Step 4: 결과 파싱
python3 tools/validate-queries.py --parse-results --output workspace/results/_validation_phase7/ --tracking-dir workspace/results/
```

**절대 `--compare` 옵션으로 직접 실행하지 마라 (subprocess per query = OOM/타임아웃).**
**항상 --generate → psql -f / sqlplus @ → --parse-results 3단계로 하라.**

### Phase 4: Self-healing (티켓 기반, 최대 5회)

Phase 3 + Phase 3.5 실패 건 모두 대상. 없으면 Phase 5로.

**Step 1: 힐링 티켓 생성**
EXPLAIN FAIL, COMPARE FAIL 결과에서 에러를 분류하여 `workspace/results/_healing/tickets.json`에 티켓 생성:
```bash
python3 tools/generate-healing-tickets.py --validation-dir workspace/results/_validation/ --output workspace/results/_healing/
```

티켓 구조:
```json
{
  "ticket_id": "HT-001",
  "status": "open",           // open → in_progress → resolved / escalated
  "category": "syntax_error", // syntax_error, type_mismatch, residual_oracle, xml_invalid, ...
  "severity": "high",         // critical(XML깨짐), high(syntax), medium(type), low(schema)
  "query_id": "selectXxx",
  "file": "xxx-sql-oracle.xml",
  "error": "syntax error at or near ...",
  "retry_count": 0,
  "max_retries": 5,
  "history": []               // 각 retry의 시도/결과 기록
}
```

**Step 2: 티켓별 힐링 루프 (최대 5회)**
```
for each ticket (severity순, critical → high → medium):
  1. Reviewer(원인 분석) → ticket.history에 분석 결과 기록
  2. Converter(재변환) → output XML 수정 + ticket.history에 수정 내용 기록
  3. Validator(EXPLAIN 재검증) → 결과를 ticket에 기록
  4. 성공 → ticket.status = "resolved"
  5. 실패 → ticket.retry_count++ → 다음 retry (최대 5회)
  6. 5회 실패 → ticket.status = "escalated"
```

**output XML 수정 전 반드시 백업:**
```bash
cp -r workspace/output/ workspace/output_v{N}_backup/
```
수정 후 regression이 발생하면 백업에서 복원 가능. **output은 git에 미트래킹이므로 백업이 유일한 롤백 수단.**

**Leader가 직접 fix 스크립트를 작성하여 output XML을 수정하지 마라.**
반드시 Converter 서브에이전트에 위임하라. Leader가 직접 sed/Python으로 output을 수정하면 regression이 발생한다.

상태 전이: open → in_progress → retry_1 → ... → retry_5 → escalated (또는 → resolved).

**Step 3: 티켓 분류별 처리 전략**
| 카테고리 | 처리 | 에이전트 | 비고 |
|---------|------|---------|------|
| xml_invalid | CDATA 래핑 | Converter | 즉시 수정 가능 |
| syntax_error | SQL 구문 수정 | Reviewer→Converter | 딥다이브 5회 |
| residual_oracle | 미변환 패턴 재변환 | Converter | 룰 재적용 |
| type_mismatch | TC 바인드값 조정 | 자동 (스킵 가능) | DBA 불필요 |
| relation_missing | 테이블 미존재 | 스킵 (DBA 티켓) | Phase 6 보고 |
| operator_mismatch | 타입 캐스트 추가 | Converter | ::TEXT, ::INTEGER 등 |

**병렬 힐링:** 10~20건 단위 배치. 쿼리 간 병렬, 쿼리 내 retry는 순차.
**매 retry 후 반드시 EXPLAIN 재검증.** regression 확인 없이 다음 retry로 넘어가지 마라.

**Step 4: 힐링 완료 후 요약**
`workspace/results/_healing/summary.json`에 결과 기록:
- resolved 건수, escalated 건수, 카테고리별 통계
- 평균 retry 횟수, 가장 많이 발생한 에러 패턴
- Phase 6/7 리포트에 자동 반영

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
9. **Phase 완료 확인**: Phase 0~5가 모두 실행됐는지. 빠진 Phase 보고
10. **쿼리 매트릭스 확인**: `python3 tools/generate-query-matrix.py` 실행하여 전체 쿼리의 3항목 현황 확인:
    - **변환**: converted / no_change / pending
    - **EXPLAIN**: pass / fail / not_tested
    - **비교(Source vs Target)**: pass(TC N건 중 M건 성공) / fail(사유) / not_tested
11. **미완료 항목 보고**: EXPLAIN_ONLY, CONVERTED_ONLY, PENDING 쿼리 목록과 사유
12. **Compare 검증 완료 확인**: TC를 MyBatis SqlSessionFactory로 수행했는지, psql -f 배치로 실행했는지
13. **에스컬레이션 처리 확인**: 에스컬레이션된 쿼리가 사용자에게 보고됐는지

검증 결과를 `workspace/results/_dba_review/review-result.json`에 저장.
문제 발견 시 목록과 함께 사용자에게 보고. Phase 4로 돌아가지 않음 (보고만).

### Phase 7: Report (마지막)

```bash
# 쿼리 매트릭스 CSV 생성 (전체 쿼리 × 3항목)
python3 tools/generate-query-matrix.py --output workspace/reports/query-matrix.csv --json

# HTML 리포트 생성
python3 tools/generate-report.py
```

산출물:
- `workspace/reports/query-matrix.csv` — 전체 쿼리별 변환/EXPLAIN/비교 현황
- `workspace/reports/migration-report.html` — 통합 HTML 리포트

**Phase 6 (DBA Review) 완료 후에만 실행.** 모든 검증 결과를 포함.

## progress.json

매 Phase 전환 시 갱신. 쿼리별 상세는 query-tracking.json에 분리.

## 상태 표시 (매 응답 시작에 필수)

● 완료, ◐ 진행중, ○ 대기:
```
● Phase 0: Pre-flight ✓
● Phase 1: Parse+Convert (426파일, 4953쿼리)
● Phase 2: LLM Convert (26건)
◐ Phase 3: Validation (80/150)
○ Phase 3.5: MyBatis Engine
○ Phase 4~7
─────────────────────
Progress: 53% | OK:80 FAIL:0 WAIT:70 ESC:0
```

## TODO 관리

TODO(TaskCreate)를 사용할 때 **반드시 Phase 순서대로 생성**하라:
Phase 0 → 1 → 2 → 2.5 → 3 → 3.5 → 4 → 5 → 6 → 7.
뒤죽박죽으로 만들면 사용자가 진행 상황을 파악하기 어렵다.

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
