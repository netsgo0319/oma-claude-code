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
export ORACLE_HOST=10.0.139.149
export ORACLE_PORT=1521
export ORACLE_SID=ORCLPDB1              # PDB Service Name
export ORACLE_CONN_TYPE=service         # 'service' (기본) 또는 'sid'
export ORACLE_USER=wmson
export ORACLE_PASSWORD=****
export ORACLE_SCHEMA=WMSON              # 딕셔너리 대상 스키마

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
python3 tools/validate-queries.py --generate --output workspace/results/_validation/
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

## Kiro↔Claude Code 디렉토리 매핑

| Kiro | Claude Code | 자동 로드 |
|------|-------------|----------|
| `.kiro/steering/*.md` | `.claude/rules/*.md` | 세션 시작 시 자동 |
| `.kiro/skills/*/SKILL.md` | `.claude/skills/*/SKILL.md` | 필요 시 자동 |
| `.kiro/agents/*.json` | `.claude/agents/*.md` | Agent tool로 호출 |
| `.kiro/prompts/*.md` | agents에 통합 | — |
| `tools/` | `tools/` (동일) | — |
