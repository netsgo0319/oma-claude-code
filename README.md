# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL을 PostgreSQL로 자동 변환, 검증하는 AI 에이전트 시스템.

Claude Code 기반으로 4개 서브에이전트(converter, tc-generator, validate-and-fix, reporter)가 5단계 파이프라인을 실행합니다.

## 전체 파이프라인

```
workspace/input/*.xml (Oracle MyBatis XML)
        |
  Step 0  Preflight — 환경 체크 + Oracle/PG 접속 + pgcrypto 확인
        |
  Step 1  Parse + Convert — XML 파싱 → 40+ 룰 변환 + LLM 복합 변환
        |
  Step 2  TC Generate — 테스트 케이스 생성
        |
  Step 3  Validate + Fix — EXPLAIN → Execute → Compare + 수정 루프 (최대 5회)
        |
  Step 4  Report — HTML 리포트 + Query Matrix CSV
        |
workspace/output/*.xml (PostgreSQL MyBatis XML)
workspace/reports/migration-report.html
```

### Step별 상세

| Step | 이름 | 핵심 동작 | 도구 |
|------|------|----------|------|
| 0 | **Preflight** | XML 존재, Python/psql/sqlplus/Java 체크. Oracle 오브젝트 스캔 (TABLE/FUNCTION/PACKAGE). PG pgcrypto extension 확인 | — |
| 1 | **Parse + Convert** | XML split → parse → analyze → 40+ 룰 변환 + LLM 복합 변환 (Converter 서브에이전트) | `batch-process.sh`, `oracle-to-pg-converter.py` |
| 2 | **TC Generate** | 테스트 케이스 생성 (V$SQL_BIND_CAPTURE, 컬럼 통계, FK, Java VO) | `generate-test-cases.py` |
| 3 | **Validate + Fix** | EXPLAIN → Execute → Compare (3단계 검증) + 실패 쿼리 수정 루프 최대 5회 (validate-and-fix 서브에이전트) | `validate-queries.py`, `run-extractor.sh`, validate-and-fix agent |
| 4 | **Report** | Query Matrix CSV (쿼리 x 3항목) + HTML 리포트 (에러 분류, 필터, Step Progress) | `generate-query-matrix.py`, `generate-report.py` |

## 구성 (Claude Code)

```
.claude/
  agents/         4개 에이전트 (converter, tc-generator, validate-and-fix, reporter)
  skills/         스킬 (SKILL.md + references)
  rules/          룰 (oracle-pg-rules, edge-cases, db-config, product, tech)
  commands/       명령 (convert, validate, report, status, reset)
  settings.json   hooks + permissions

tools/
  oracle-to-pg-converter.py    40+ 룰 기계적 변환 (1,800줄)
  validate-queries.py          3단계 검증 + 배치 스크립트 생성 (1,500줄)
  generate-test-cases.py       4소스 TC 생성 (370줄)
  generate-report.py           HTML 리포트 (1,600줄)
  generate-query-matrix.py     Query Matrix CSV/JSON (250줄)
  parse-xml.py                 MyBatis XML 파서 (400줄)
  query-analyzer.py            복잡도 L0~L4 분류 (280줄)
  xml-splitter.py              대형 XML 분할 (140줄)
  tracking_utils.py            공용 트래킹 (flock 안전) (400줄)
  sync-tracking-to-xml.py      tracking→output XML 동기화 (100줄)
  batch-process.sh             Step 1 병렬 처리 (260줄)
  run-extractor.sh             MyBatis 추출 래퍼 (gradlew 포함) (140줄)
  reset-workspace.sh           초기화 (80줄)

workspace/
  input/          변환 대상 XML (불변)
  output/         변환 완료 XML
  results/        버전별 중간 결과 + _validation/ + _extracted/
  reports/        migration-report.html + query-matrix.csv
  logs/           activity-log.jsonl
```

## 에이전트

| 에이전트 | 모델 | 역할 |
|---------|------|------|
| **converter** | Sonnet | Oracle→PG 변환. 룰 컨버터 v1만 실행, v2+는 output Edit만. #{sysdate} 변환 안 함 |
| **tc-generator** | Sonnet | 테스트 케이스 생성. 4소스(샘플/VO/바인드캡처/FK)에서 바인드값 수집 |
| **validate-and-fix** | Sonnet | 3단계 검증 (EXPLAIN→실행→비교) + 실패 시 원인 분석 + SQL 수정 + 재검증 루프 |
| **reporter** | Sonnet | Query Matrix CSV/JSON + HTML 리포트 생성 |

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
> 변환해줘               # Step 0~4 자동 수행

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
| `workspace/reports/query-matrix.csv` | 전체 쿼리 x 3항목 (변환/EXPLAIN/비교) |
| `workspace/results/_validation/validated.json` | EXPLAIN 검증 결과 (pass/fail 목록) |
| `workspace/logs/activity-log.jsonl` | 전체 감사 로그 |

### HTML 리포트 구성

- **Overview**: 6개 카드 (파일수, 전체쿼리, PASS, FAIL코드, FAIL DBA, 미테스트) + Step Progress 바
- **Explorer**: 파일→쿼리 트리 네비게이션 + 쿼리별 상세 (Oracle/PG SQL 비교, 14-state 배지, TC 결과, Attempt History)
- **Log**: 활동 타임라인 + 감사 로그 (에러/결정/경고 필터)

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

## 쿼리 라이프사이클 (발견 → 변환 → TC → 검증 → 수정 → 완료)

하나의 쿼리가 파이프라인을 통과하는 전체 과정입니다.

```
예시: selectOrderList (daiso-oms_oms-order-sql-oracle.xml)

Step 1: 발견 + 룰 변환 + LLM 변환
  ├── XML 파싱 → query_id: selectOrderList, type: select
  ├── Oracle 패턴 감지: NVL(3), DECODE(1), ROWNUM(1)
  ├── 복잡도: L2 (Dynamic Simple)
  ├── 룰 변환: NVL→COALESCE, DECODE→CASE, ROWNUM→LIMIT
  ├── LLM 변환 (unconverted가 있을 때만):
  │   (+) outer join → LEFT JOIN, CONNECT BY → WITH RECURSIVE
  └── 상태: converted (rule/llm)

Step 2: TC 생성
  ├── 파라미터 추출: #{owkey}, #{ctkey}, #{pageStart}
  ├── 4소스에서 바인드값 수집 → TC 생성 (최대 6종)
  └── 상태: tc_generated

Step 3: 검증 + 수정 루프
  ├── EXPLAIN (PG 문법 검증)
  │   EXPLAIN SELECT ... FROM TORDER ... WHERE OWKEY='DS' AND CTKEY='HE' LIMIT 5;
  │   → PASS 또는 FAIL
  ├── Execute (양쪽 실행)
  │   PG: psql → SELECT ... LIMIT 5; → (3 rows)
  │   Oracle: SELECT COUNT(*) FROM (원본 SQL) WHERE ROWNUM<=50; → 3
  ├── Compare (결과 비교)
  │   Oracle 3행 vs PG 3행 → MATCH
  ├── 수정 루프 (FAIL인 경우, 최대 5회):
  │   Attempt 1:
  │     원인 분석 → output XML 수정 (Edit)
  │     재검증: EXPLAIN → PASS
  │     → 통과 (attempt_count: 1)
  │   (실패 시 Attempt 2~5 반복)
  │   (5회 실패 → escalated → Step 4 리포트에 보고)
  └── 결과: query-tracking.json attempts 배열 갱신

Step 4: 리포트
  ├── query-matrix.csv: selectOrderList → COMPLETE (변환O EXPLAIN O Compare O)
  └── migration-report.html: Overview + Files + 드릴다운
```

### 상태 전이

```
parsed → converted (rule/llm) → validating → COMPLETE
                                           → FAIL → fix attempt
                                                    → resolved (attempt 1~5)
                                                    → escalated (5회 실패)
```
