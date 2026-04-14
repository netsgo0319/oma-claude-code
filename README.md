# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL을 PostgreSQL로 자동 변환, 검증, 학습하는 AI 에이전트 시스템.

Kiro(`oma_kiro`)와 Claude Code(`oma-claude-code`) 두 플랫폼에서 동일한 파이프라인을 실행할 수 있습니다.

## 전체 파이프라인

```
workspace/input/*.xml (Oracle MyBatis XML)
        |
  Phase 0  Pre-flight — 환경 체크 + Oracle/PG 접속 + pgcrypto 확인
        |
  Phase 1  Parse + Rule Convert — XML 파싱 → 40+ 룰 기계적 변환 (병렬)
        |
  Phase 2  LLM Convert — unconverted 패턴을 Converter 서브에이전트가 LLM 변환
        |
  Phase 2.5  Test Case — Oracle 딕셔너리 4소스에서 바인드값 수집 → TC 생성
        |
  Phase 3  Validation — Stage 1: EXPLAIN → Stage 2: Execute → Stage 3: Compare
        |
  Phase 3.5  MyBatis Engine — Java로 동적 SQL 실제 렌더링 후 재검증
        |
  Phase 4  Self-healing — 티켓 기반 최대 5회 (Reviewer→Converter→Validator 루프)
        |
  Phase 5  Learning — 패턴 학습 → rules/edge-cases 갱신 → 자동 PR
        |
  Phase 6  DBA Review — XML 무결성, 파라미터, 잔여 Oracle 패턴 최종 검증
        |
  Phase 7  Report — HTML 리포트 + Query Matrix CSV
        |
workspace/output/*.xml (PostgreSQL MyBatis XML)
workspace/reports/migration-report.html
```

### Phase별 상세

| Phase | 이름 | 핵심 동작 | 도구 |
|-------|------|----------|------|
| 0 | **Pre-flight** | XML 존재, Python/psql/sqlplus/Java 체크. Oracle 오브젝트 스캔 (TABLE/FUNCTION/PACKAGE). PG pgcrypto extension 확인 | — |
| 1 | **Parse + Rule Convert** | XML split → parse → analyze → 40+ 룰 기계적 변환. 8병렬 | `batch-process.sh`, `oracle-to-pg-converter.py` |
| 2 | **LLM Convert** | CONNECT BY→WITH RECURSIVE, MERGE→ON CONFLICT, (+)→JOIN 등 구조 변환. 3파일/30쿼리 배치 병렬 | Converter 서브에이전트 |
| 2.5 | **Test Cases** | V$SQL_BIND_CAPTURE (실제 캡처값) + ALL_TAB_COL_STATISTICS (경계값) + FK 샘플링 + 타입 추론. DML은 null/empty/boundary TC 제외 | `generate-test-cases.py` |
| 3 | **Validation** | Stage 1: psql EXPLAIN. Stage 2: psql/sqlplus 실행 (DML 5s timeout). Stage 3: Oracle vs PG row count 비교 | `validate-queries.py` |
| 3.5 | **MyBatis Engine** | Java SqlSessionFactory로 동적 SQL 렌더링 → 실제 SQL 추출 → 재검증 | `run-extractor.sh`, gradlew |
| 4 | **Self-healing** | `generate-healing-tickets.py`로 에러 분류 → 카테고리별 5회 딥다이브 (Reviewer→Converter→Validator) | `generate-healing-tickets.py` |
| 5 | **Learning** | 반복 실패→성공 패턴 → rules 추가, 새 패턴 → edge-cases 등록, Git PR 자동 생성 | Learner 서브에이전트 |
| 6 | **DBA Review** | XML well-formedness, 태그 구조, 동적 SQL 보존, include 참조, 파라미터 바인딩, 잔여 Oracle 패턴 | Reviewer 서브에이전트 |
| 7 | **Report** | Query Matrix CSV (쿼리×3항목) + HTML 리포트 (힐링 티켓, 에러 분류, 필터, Phase Progress) | `generate-query-matrix.py`, `generate-report.py` |

### Phase 완료 조건

- Phase 3 FAIL이 있으면 **반드시 Phase 4 실행** (Phase 3→6 점프 금지)
- Phase 4 완료: 모든 actionable 티켓이 resolved 또는 escalated
- DBA-only 티켓 (relation_missing 등)은 Phase 6에서 보고

## 구성 (Claude Code)

```
.claude/
  agents/         5개 에이전트 (converter, validator, reviewer, learner, test-generator)
  skills/         19개 스킬 (SKILL.md + references)
  rules/          5개 룰 (oracle-pg-rules, edge-cases, db-config, product, tech)
  commands/       5개 명령 (convert, validate, report, status, reset)
  settings.json   hooks + permissions

tools/
  oracle-to-pg-converter.py    40+ 룰 기계적 변환 (1,800줄)
  validate-queries.py          3단계 검증 + 배치 스크립트 생성 (1,500줄)
  generate-test-cases.py       4소스 TC 생성 (370줄)
  generate-healing-tickets.py  Phase 4 티켓 생성 (160줄)
  generate-report.py           HTML 리포트 (1,600줄)
  generate-query-matrix.py     Query Matrix CSV/JSON (250줄)
  parse-xml.py                 MyBatis XML 파서 (400줄)
  query-analyzer.py            복잡도 L0~L4 분류 (280줄)
  xml-splitter.py              대형 XML 분할 (140줄)
  tracking_utils.py            공용 트래킹 (flock 안전) (400줄)
  sync-tracking-to-xml.py      tracking→output XML 동기화 (100줄)
  batch-process.sh             Phase 1 병렬 처리 (260줄)
  run-extractor.sh             Phase 3.5 래퍼 (gradlew 포함) (140줄)
  reset-workspace.sh           초기화 (80줄)

workspace/
  input/          변환 대상 XML (불변)
  output/         변환 완료 XML
  results/        버전별 중간 결과 + _validation/ + _healing/ + _extracted/
  reports/        migration-report.html + query-matrix.csv
  logs/           activity-log.jsonl
```

## 에이전트

| 에이전트 | 모델 | 역할 |
|---------|------|------|
| **converter** | Sonnet | Oracle→PG 변환. 룰 컨버터 v1만 실행, v2+는 output Edit만. #{sysdate} 변환 안 함 |
| **validator** | Sonnet | 3단계 검증 (EXPLAIN→실행→비교). DML 5s timeout. 병렬 시 파일 단위 분배 |
| **reviewer** | Opus | 실패 원인 분석 + SQL 수정안. #{param}은 Oracle 패턴 아님 |
| **learner** | Sonnet | 에지케이스 학습 → rules/edge-cases 갱신 → Git PR |
| **test-generator** | Opus | Oracle 딕셔너리 4소스 TC 생성. DML에 null/empty TC 제외 |

## 환경변수

```bash
# Oracle
export ORACLE_HOST=oracle.example.com
export ORACLE_PORT=1521
export ORACLE_SID=ORCL              # PDB Service Name
export ORACLE_CONN_TYPE=service         # 'service' (기본) 또는 'sid'
export ORACLE_USER=migration_user
export ORACLE_PASSWORD=****
export ORACLE_SCHEMA=APP_SCHEMA              # 딕셔너리 대상 스키마

# PostgreSQL
export PG_HOST=pg.example.com
export PG_PORT=5432
export PG_DATABASE=target_db
export PG_SCHEMA=public
export PG_USER=migration_user
export PG_PASSWORD=****
```

## 실행

```bash
# Claude Code
cp /path/to/mybatis/*.xml workspace/input/
claude                    # Claude Code 실행
> 변환해줘               # Phase 0~7 자동 수행

# 또는 개별 도구
python3 tools/oracle-to-pg-converter.py workspace/input/Mapper.xml workspace/output/Mapper.xml
python3 tools/validate-queries.py --full --output workspace/results/_validation/ --tracking-dir workspace/results/
python3 tools/generate-report.py
```

## 산출물

| 경로 | 내용 |
|------|------|
| `workspace/output/*.xml` | 변환된 PostgreSQL MyBatis XML |
| `workspace/reports/migration-report.html` | **통합 HTML 리포트** (브라우저에서 열기) |
| `workspace/reports/query-matrix.csv` | 전체 쿼리 × 3항목 (변환/EXPLAIN/비교) |
| `workspace/results/_healing/tickets.json` | Phase 4 힐링 티켓 (에러 분류, retry 이력) |
| `workspace/results/_validation/validated.json` | EXPLAIN 검증 결과 (pass/fail 목록) |
| `workspace/logs/activity-log.jsonl` | 전체 감사 로그 |

### HTML 리포트 포함 내용

- Phase Progress 바 (● 완료 / ◐ 진행 / ○ 대기)
- Query Validation Matrix (COMPLETE/EXPLAIN_ONLY/FAIL 카드)
- **Healing Tickets** (카테고리별 분류 + Action Required 테이블)
- **EXPLAIN Failure Categories** (SYNTAX_ERROR/MISSING_OBJECT 등 + 조치 가이드)
- DBA/Expert Review 결과
- 파일별 드릴다운 (Oracle/PG SQL 병렬 비교)
- **파일 필터** (All/Fail/Pass 토글)
- 활동 타임라인 + 감사 로그

## 핵심 안전장치

| 장치 | 내용 |
|------|------|
| DML empty_string TC 제외 | Oracle '' = NULL → 풀스캔 UPDATE 방지 |
| DML null_test TC 제외 | 동적 SQL 조건 누락 → 대량 DML 방지 |
| DML statement_timeout 5s | 대형 테이블 DML 강제 종료 |
| DML 대형 테이블 execute_skip | 10,000행+ 테이블 DML은 EXPLAIN만 |
| CDATA 자동 래핑 | 변환 시 < 연산자 생성 → XML 깨짐 방지 |
| NVL overlap skip | 중첩 NVL 이중 변환 방지 (19개 변환기) |
| oracle_compare.sql flatten | sqlplus 멀티라인 SP2 에러 방지 |
| TrackingManager flock | 병렬 Validator 동시 쓰기 안전 |
| DDL 차단 hook | DROP/TRUNCATE/ALTER TABLE 실행 차단 |
| rm workspace/* 만 허용 | 프로젝트 파일 삭제 방지 |

## 쿼리 라이프사이클 (발견 → 변환 → TC → 검증 → 힐링 → 완료)

하나의 쿼리가 파이프라인을 통과하는 전체 과정입니다.

```
예시: selectOrderList (daiso-oms_oms-order-sql-oracle.xml)

Phase 1: 발견 + 룰 변환
  ├── XML 파싱 → query_id: selectOrderList, type: select
  ├── Oracle 패턴 감지: NVL(3), DECODE(1), ROWNUM(1)
  ├── 복잡도: L2 (Dynamic Simple)
  ├── 룰 변환: NVL→COALESCE, DECODE→CASE, ROWNUM→LIMIT
  └── 상태: converted (rule)
      결과: results/{file}/v1/query-tracking.json → pg_sql 기록

Phase 2: LLM 변환 (unconverted가 있을 때만)
  ├── residual 패턴이 남아있으면 Converter 서브에이전트 위임
  ├── (+) outer join → LEFT JOIN, CONNECT BY → WITH RECURSIVE
  └── 상태: converted (llm)
      결과: output/{file}.xml 갱신 + query-tracking 갱신

Phase 2.5: TC 시나리오 생성
  ├── 파라미터 추출: #{owkey}, #{ctkey}, #{pageStart}
  ├── 4소스에서 바인드값 수집:
  │   V$SQL_BIND_CAPTURE: owkey='DS' (실제 캡처)
  │   FK 샘플링: ctkey='HE' (참조 테이블)
  │   컬럼 통계: pageStart=1 (MIN값)
  │   이름 추론: fallback
  ├── TC 생성 (SELECT는 최대 6종):
  │   default:      {owkey:'DS', ctkey:'HE', pageStart:1}
  │   null_test:    {owkey:null, ctkey:null, pageStart:null}
  │   empty_string: {owkey:'', ctkey:'', pageStart:1}
  │   bind_capture: {owkey:'AB', ctkey:'HQ', pageStart:5}
  │   boundary:     {owkey:'ZZ', ctkey:'ZZ', pageStart:99999}
  │   fk_sample:    {owkey:'DS', ctkey:'SE', pageStart:1}
  └── 결과: results/{file}/v1/test-cases.json + _test-cases/merged-tc.json

Phase 3: 검증 (MyBatis 엔진 우선)
  ├── Step 1: MyBatis 엔진에 TC params 주입
  │   java -jar extractor.jar --params merged-tc.json
  │   → getBoundSql({owkey:'DS', ctkey:'HE'})
  │   → <if test="owkey != null"> 분기 평가 → 완전한 SQL 출력
  │   → 6개 TC × 다른 분기 = 다수의 SQL variant
  │
  ├── Step 2: EXPLAIN (PG 문법 검증)
  │   EXPLAIN SELECT ... FROM TORDER ... WHERE OWKEY='DS' AND CTKEY='HE' LIMIT 5;
  │   → PASS ✓ (또는 FAIL: syntax error at near "...")
  │
  ├── Step 3: Execute (양쪽 실행)
  │   PG: psql → SELECT ... LIMIT 5; → (3 rows)
  │   Oracle: SELECT COUNT(*) FROM (원본 SQL) WHERE ROWNUM<=50; → 3
  │
  ├── Step 4: Compare (결과 비교)
  │   Oracle 3행 vs PG 3행 → MATCH ✓
  │
  └── 상태: EXPLAIN pass + Compare pass → COMPLETE
      결과: validated.json + query-tracking.json explain 갱신

Phase 4: 힐링 (FAIL인 경우에만)
  ├── 티켓 생성: HT-0042, category: syntax_error, severity: high
  │   error: "syntax error at or near COALESCE"
  │
  ├── Phase 3.5 교차 참조:
  │   → MyBatis 엔진에서 PASS → 자동 resolved (resolved_by_mybatis_engine)
  │   → MyBatis에서도 FAIL → 힐링 루프 진입
  │
  ├── 힐링 루프 (최대 5회):
  │   Retry 1:
  │     Reviewer: "NVL→COALESCE 변환 시 중첩 괄호 중복" 진단
  │     Converter: output XML 수정 (Edit)
  │     재검증: MyBatis 재추출 → EXPLAIN → PASS ✓
  │     → 티켓 resolved (retry_count: 1)
  │
  │   (실패 시 Retry 2~5 반복)
  │   (5회 실패 → 티켓 escalated → Phase 6에서 DBA에게 보고)
  │
  └── 결과: _healing/tickets.json 갱신 (status, history, retry_count)

Phase 5: 학습
  ├── "NVL 중첩 괄호" 패턴 → edge-cases.md 등록
  ├── 3회 이상 반복 패턴 → oracle-pg-rules.md 룰 승격
  └── Git PR 자동 생성

Phase 6: DBA Review
  ├── output XML 무결성 검증 (well-formed, 태그, 파라미터)
  ├── 에스컬레이션 건 보고
  └── review-result.json 저장

Phase 7: 리포트
  ├── query-matrix.csv: selectOrderList → COMPLETE (변환✓ EXPLAIN✓ Compare✓)
  ├── migration-report.html:
  │   Overview: Action Items, Phase Progress, Query Matrix 카드
  │   Files탭: 파일→쿼리 드릴다운 (Oracle/PG SQL 비교)
  │   Tickets탭: Resolved/Escalated/Skipped 상세
  └── 보고서에서 이 쿼리의 전체 이력 추적 가능
```

### 상태 전이

```
parsed → converted (rule/llm) → validating → COMPLETE
                                           → FAIL → healing_ticket
                                                    → resolved (retry 1~5)
                                                    → resolved_by_mybatis_engine
                                                    → escalated (5회 실패)
                                                    → skipped (DBA schema 등)
```

## Kiro↔Claude Code 디렉토리 매핑

| Kiro | Claude Code | 자동 로드 |
|------|-------------|----------|
| `.kiro/steering/*.md` | `.claude/rules/*.md` | 세션 시작 시 자동 |
| `.kiro/skills/*/SKILL.md` | `.claude/skills/*/SKILL.md` | 필요 시 자동 |
| `.kiro/agents/*.json` | `.claude/agents/*.md` | Agent tool로 호출 |
| `.kiro/prompts/*.md` | agents에 통합 | — |
| `tools/` | `tools/` (동일) | — |
