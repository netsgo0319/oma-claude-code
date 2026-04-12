# OMA Kiro - Oracle Migration Accelerator

Oracle DB MyBatis/iBatis XML 쿼리를 PostgreSQL로 자동 변환, 검증, 학습하는 **Kiro Custom Agent** 시스템.

## 구성

```
.kiro/
  agents/       6개 에이전트 (JSON)
  prompts/      6개 프롬프트 (Markdown)
  skills/       19개 스킬 (SKILL.md + references)
  steering/     5개 스티어링 (Markdown)
  schemas/      10개 JSON Schema (에이전트 간 통신 계약)
  settings/     cli.json (기본 에이전트, 모델 설정)

tools/
  mybatis-sql-extractor/   MyBatis 엔진 기반 SQL 추출기 (Java/Gradle)
  *.py          7개 Python 도구 (XML 파싱, 변환, 검증, 분석, 리포트)
  *.sh          2개 Shell 스크립트 (초기화, Phase 3.5 래퍼)

workspace/
  input/        변환 대상 XML (불변)
  output/       변환 완료 XML
  results/      버전별 중간 결과 (JSON)
  _validation/  검증 SQL 스크립트 + 결과
  _extracted/   Phase 3.5 MyBatis 엔진 추출 결과
  reports/      최종 리포트 (HTML + Markdown)
  logs/         감사 로그 (activity-log.jsonl)
  reports/      최종 리포트 (migration-report.html)
```

## 에이전트

| 에이전트 | 모델 | 역할 |
|---------|------|------|
| `oracle-pg-leader` | Opus 4.6 | 오케스트레이터 - 전체 파이프라인 관리, 서브에이전트 분배 |
| `converter` | Sonnet 4.6 | Oracle SQL -> PostgreSQL 변환 (룰 기반 + LLM) |
| `test-generator` | Opus 4.6 | Oracle 딕셔너리 기반 테스트 케이스 생성 |
| `validator` | Sonnet 4.6 | 4단계 검증 (EXPLAIN -> 실행 -> 비교 -> Integrity Guard) |
| `reviewer` | Opus 4.6 | 실패 원인 분석 + 수정안 생성 + 자동 재시도 |
| `learner` | Sonnet 4.6 | 에지케이스 학습 + steering 갱신 + 자동 PR/Issue |

## 워크플로우

```
Phase 0:   사전 점검 (XML 존재, sqlplus/psql 설치, DB 접속 테스트)
Phase 1:   XML 파싱 (MyBatis 3.x / iBatis 2.x 자동 판별, 쿼리 추출)
Phase 1.5: 의존성 분석 + 복잡도 분류 (L0~L4, 위상 정렬)
Phase 2:   레이어별 변환 (리프 쿼리부터, 룰 기반 + LLM, 병렬)
Phase 2.5: 테스트 케이스 생성 (V$SQL_BIND_CAPTURE, 컬럼 통계, FK 등)
Phase 3:   검증 (EXPLAIN -> 실행 -> Oracle/PG 비교 -> Integrity Guard 14개 경고)
Phase 3.5: MyBatis 엔진 검증 (Java 필요, 동적 SQL 정밀 평가, 힐링 전)
Phase 4:   셀프 힐링 (실패 -> 원인 분석 -> 수정 -> 재시도, 최대 3회)
Phase 5:   학습 (에지케이스 축적 -> steering 갱신 -> 자동 PR)
Phase 6:   DBA/Expert 최종 검증 (필수)
Phase 7:   리포트 (통합 HTML 리포트 자동 생성)
```

### 레이어 기반 변환

쿼리 간 의존성을 분석하여 리프 쿼리부터 단계적으로 변환합니다:

```
Layer 0: SQL fragments + 독립 쿼리 (의존성 없음) -> 먼저 변환/검증
Layer 1: Layer 0을 참조하는 쿼리 -> Layer 0 성공 후 변환
Layer 2: Layer 0~1을 참조하는 복잡 쿼리 -> 순차적으로
   ...
```

### 복잡도 분류 (L0~L4)

| Level | 이름 | 예시 | 변환 전략 |
|-------|------|------|----------|
| L0 | Static | `SELECT id FROM users WHERE id = #{id}` | 변환 불필요 |
| L1 | Simple Rule | NVL, SYSDATE, ROWNUM | 룰 기반 자동 치환 |
| L2 | Dynamic Simple | `<if>`, `<where>` + 단순 Oracle 구문 | 룰 우선, 동적 SQL 주의 |
| L3 | Dynamic Complex | 중첩 `<choose>`, `<foreach>`, 서브쿼리 | 룰 + LLM 혼합 |
| L4 | Oracle Complex | CONNECT BY + MERGE + 동적 SQL 조합 | LLM 위주, 수동 검토 권장 |

### 셀프 힐링

검증 실패 시 자동으로 원인 분석 -> 수정 -> 재검증을 반복합니다.
각 시도는 버전(v1->v2->v3)으로 추적됩니다. 3회 실패 시 사용자에게 에스컬레이션.

### 학습 루프

변환 과정에서 발견된 패턴이 steering 파일에 자동 축적됩니다.
다음 변환 시 같은 패턴을 만나면 축적된 지식으로 바로 해결합니다.
Learner가 자동 PR을 생성하고 팀이 리뷰/머지하면 전원이 혜택을 받습니다.

## 스킬

| 카테고리 | 스킬 | 역할 |
|---------|------|------|
| 파싱 | `parse-xml` | MyBatis/iBatis XML 파싱 (28+35 태그) |
| 분석 | `query-analyzer` | 의존성 그래프 + 복잡도 점수 + 위상 정렬 |
| 분석 | `cross-file-analyzer` | 파일 간 의존성 분석 + 전역 참조 추적 |
| 분석 | `complex-query-decomposer` | 복잡 쿼리 분해 + 서브쿼리 추출 |
| 변환 | `rule-convert` | 룰 기반 기계적 치환 (40+ 룰) |
| 변환 | `llm-convert` | LLM 기반 복잡 패턴 변환 |
| 변환 | `param-type-convert` | 파라미터 타입 변환 + 타입 매핑 |
| SQL 추출 | `extract-sql` | MyBatis BoundSql API로 실제 SQL 추출 |
| 테스트 | `generate-test-cases` | Oracle 딕셔너리 기반 테스트 케이스 |
| 검증 | `explain-test` | PostgreSQL EXPLAIN 문법 검증 |
| 검증 | `execute-test` | 실제 실행 검증 (트랜잭션+ROLLBACK) |
| 검증 | `compare-test` | Oracle/PG 결과 비교 + Result Integrity Guard |
| DB 접근 | `db-oracle` | sqlplus CLI 기반 Oracle 접근 |
| DB 접근 | `db-postgresql` | psql CLI 기반 PostgreSQL 접근 |
| 로깅 | `audit-log` | 통합 감사 로그 (10개 타입) |
| 리포트 | `report` | 변환 리포트 + 마이그레이션 가이드 |
| 학습 | `learn-edge-case` | 에지케이스 학습 + PR/Issue 생성 |

## 도구 (Python/Java/Shell)

| 도구 | Phase | 역할 |
|------|-------|------|
| `tools/xml-splitter.py` | Phase 1 | 대형 XML을 쿼리 단위로 분할 |
| `tools/parse-xml.py` | Phase 1 | chunk → parsed.json (Oracle 패턴 감지) |
| `tools/query-analyzer.py` | Phase 1.5 | 의존성 그래프 + 복잡도 L0~L4 + 위상 정렬 |
| `tools/oracle-to-pg-converter.py` | Phase 2 | 기계적 SQL 변환 (40+ 룰, CDATA/멀티라인/ROWNUM/INTERVAL) |
| `tools/validate-queries.py` | Phase 3 | EXPLAIN + 실제 실행 + SSM 원격 검증 + Result Integrity Guard |
| `tools/generate-report.py` | Phase 7 | 전체 결과 종합 → 단일 HTML 리포트 |
| `tools/generate-query-matrix.py` | Phase 7 | 전체 쿼리 × 3항목 (변환/EXPLAIN/비교) CSV |
| `tools/generate-test-cases.py` | Phase 2.5 | Oracle 딕셔너리 기반 TC 자동 생성 |
| `tools/sync-tracking-to-xml.py` | 유틸 | query-tracking.json → output XML 동기화 |
| `tools/run-extractor.sh` | Phase 3.5 | MyBatis 엔진 SQL 추출 + 검증 (원커맨드) |
| `tools/mybatis-sql-extractor/` | Phase 3.5 | Java/Gradle — SqlSessionFactory + BoundSql API |
| `tools/reset-workspace.sh` | 초기화 | workspace 초기화 (input 보존) |

## 감사 로그

모든 에이전트 활동이 `workspace/logs/activity-log.jsonl`에 기록됩니다.

```bash
# 실시간 로그 확인
tail -f workspace/logs/activity-log.jsonl | python3 -m json.tool

# 에러만 필터
grep '"type":"ERROR"' workspace/logs/activity-log.jsonl | python3 -m json.tool

# 특정 쿼리의 전체 이력
grep 'getOrgHierarchy' workspace/logs/activity-log.jsonl | python3 -m json.tool

# AI 판단 기록
grep '"type":"DECISION"' workspace/logs/activity-log.jsonl | python3 -m json.tool

# 학습 이력
grep '"type":"LEARNING"' workspace/logs/activity-log.jsonl | python3 -m json.tool
```

### 로그 타입

| 타입 | 내용 |
|------|------|
| `PHASE_START/END` | Phase 시작/종료 + 소요시간 |
| `DECISION` | AI 판단 근거 (왜 rule/llm 선택, 왜 재시도 등) |
| `ATTEMPT` | 변환/검증/분석 시도 |
| `SUCCESS` | 성공 결과 |
| `ERROR` | 에러 상세 (전문, SQL, 바인드 값, 가능한 원인) |
| `FIX` | 수정 시도 (이전 SQL, 수정 SQL, 수정 이유) |
| `ESCALATION` | 사용자 에스컬레이션 (전체 시도 이력) |
| `HUMAN_INPUT` | 사용자 입력/개입 |
| `LEARNING` | 패턴 학습 (steering 갱신, PR/Issue) |
| `WARNING` | Result Integrity Guard 경고 |

## 사전 준비

1. [Kiro CLI](https://kiro.dev) 설치
2. Python 3.8+ (파싱/변환/검증 도구)
3. Java 11+ & Gradle (Phase 3.5 MyBatis 엔진 검증용, **선택**)
4. Oracle / PostgreSQL 접속 정보 환경변수 설정:

```bash
# .env
export ORACLE_HOST=oracle.example.com
export ORACLE_PORT=1521
export ORACLE_SID=ORCL
export ORACLE_USER=migration_user
export ORACLE_PASSWORD=****

export PG_HOST=pg.example.com
export PG_PORT=5432
export PG_DATABASE=target_db
export PG_SCHEMA=public
export PG_USER=migration_user
export PG_PASSWORD=****
```

## 실행

```bash
# 1. 변환 대상 XML 배치
cp /path/to/mybatis/*.xml workspace/input/

# 2. 에이전트 실행 (기본: oracle-pg-leader)
kiro-cli --agent oracle-pg-leader

# 3. "변환해줘" 입력 -> Phase 0~7 자동 수행

# 도구만 개별 실행 (에이전트 없이)
python3 tools/oracle-to-pg-converter.py workspace/input/Mapper.xml workspace/output/Mapper.xml
python3 tools/validate-queries.py --local --output workspace/results/_validation/
python3 tools/generate-report.py
bash tools/run-extractor.sh --validate    # Phase 3.5 (Java 필요)
```

### 사용 가능한 명령

| 명령 | 동작 |
|------|------|
| `변환해줘` | 전체 XML을 Phase 0~7 자동 수행 |
| `X파일만 변환해줘` | 특정 파일만 처리 |
| `Y쿼리 수정했어, 다시 검증해줘` | 에스컬레이션 건 재검증 + 학습 |
| `현재 진행 상황` | progress.json 기반 현황 |
| `Phase 1~2만 해줘` | DB 없이 파싱+변환만 |
| `Phase 3.5 진행해줘` | MyBatis 엔진 검증 (Java 필요) |
| `초기화해줘` | workspace 리셋 (input 보존) |

## 산출물

| 경로 | 내용 |
|------|------|
| `workspace/output/` | 변환된 PostgreSQL XML 파일 |
| `workspace/results/{file}/v{n}/` | 버전별 중간 결과 (JSON) |
| `workspace/results/_validation/` | EXPLAIN/실행 검증 결과 |
| `workspace/results/_extracted/` | Phase 3.5 MyBatis 엔진 추출 결과 |
| **`workspace/reports/migration-report.html`** | **통합 HTML 리포트 (브라우저에서 열기)** |
| `workspace/reports/conversion-report.md` | 변환 리포트 Markdown 버전 |
| `workspace/reports/migration-guide.md` | 마이그레이션 가이드 (수동 검토 항목) |
| `workspace/logs/activity-log.jsonl` | 전체 감사 로그 |

### HTML 리포트

Phase 7에서 자동 생성되는 통합 리포트입니다. 별도로 생성하려면:

```bash
python3 tools/generate-report.py
# -> workspace/reports/migration-report.html
```

포함 내용:
- 파일별 변환 결과 (원본 라인수, 쿼리수, 상태)
- Oracle 패턴 분포 차트 (NVL, DECODE, CONNECT BY 등)
- 복잡도 분포 (L0~L4)
- EXPLAIN 검증 결과 (PASS/FAIL + 실패 상세)
- 실행 검증 결과 (row count + Integrity Guard 경고)
- Phase 3.5 MyBatis 추출 결과 (variants, multi-branch)
- 활동 로그 (최근 30건)

## 팀 사용

```bash
git clone https://github.com/netsgo0319/oma_kiro.git
# .env 설정 후 kiro-cli --agent oracle-pg-leader 실행
# Learner가 에지케이스 발견 시 자동 PR 생성 -> 팀 리뷰 -> 머지
```

## TODO

- [ ] **Scanner 서브에이전트 추가** — Phase 1~2를 파일 N개 일괄 수행. Leader가 파일별 4회 shell 호출하는 대신 1회 subagent 호출로 context 절약 (11파일 기준 44 calls → 1 call)
- [ ] **Healer 서브에이전트 추가** — Phase 4 셀프 힐링 루프를 내부에서 자체 수행. 실패 건 목록을 받아 Reviewer→Converter→Validator 루프를 3회까지 돌리고 결과만 반환 (최대 54 calls → 1 call)
- [ ] **Leader 대형 JSON 직접 읽기 금지** — progress.json, query-tracking.json 등을 `fs_read`로 읽지 않고 `shell`로 요약만 추출하도록 프롬프트 규칙 추가
- [ ] **토큰 사용량 추적** — Kiro가 Hook에 토큰 데이터를 노출하면 Phase/에이전트별 토큰 소모량을 progress.json과 HTML 리포트에 반영
- [ ] **PreToolUse Hook 강화** — SQL DDL 차단 hook 우회 방지 (JSON 파싱, 코멘트 기반 우회 차단)
- [ ] **Secret 감지 Hook 추가** — Bash 명령에서 비밀번호/API키 패턴 감지
- [ ] **자동화 테스트 인프라** — pytest 기반, 6,991줄 도구 코드 테스트 커버리지
- [ ] **JSON Schema 런타임 검증** — 10개 스키마의 실시간 검증 (jsonschema 패키지)
- [ ] **compare 성능 개선** — subprocess per query → 배치 SQL 전용 (psql -f, sqlplus @)
- [ ] **보고서 HTML 크기 제한** — 5000쿼리+ 시 SQL 잘라내기 또는 lazy loading
- [ ] **steering 파일 졸업/아카이브** — edge-cases.md append-only → 룰 승격 시 제거

## 기여

[CONTRIBUTING.md](docs/CONTRIBUTING.md) 참조 - 에이전트/스킬/룰/에지케이스 추가 가이드.

## 문서

- **[아키텍처 가이드](docs/architecture.md)** — Phase별 플로우, 의사결정 트리, Mermaid 다이어그램
- [설계 스펙](docs/superpowers/specs/2026-04-09-oracle-pg-migration-agent-design.md)
- [구현 플랜](docs/superpowers/plans/2026-04-09-oracle-pg-migration-plan.md)
- [기여 가이드](docs/CONTRIBUTING.md)

<!-- harness-eval-badge:start -->
![Harness Score](https://img.shields.io/badge/harness-8.0%2F10-green)
![Harness Grade](https://img.shields.io/badge/grade-A-green)
![Last Eval](https://img.shields.io/badge/eval-2026--04--09-blue)
<!-- harness-eval-badge:end -->
