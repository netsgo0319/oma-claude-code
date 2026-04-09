# OMA Claude Code — Oracle Migration Accelerator

Oracle DB MyBatis/iBatis XML 쿼리를 PostgreSQL로 자동 변환, 검증, 학습하는 **Claude Code 에이전트 하네스**.

> [OMA Kiro](https://github.com/netsgo0319/oma_kiro)의 Claude Code 포팅 버전입니다.

## 구성

```
CLAUDE.md                  오케스트레이터 (= Kiro의 oracle-pg-leader)
.claude/
  settings.json            Hooks + 권한 설정
  commands/                슬래시 커맨드 (/convert, /status, /reset, /validate, /report)
  prompts/                 서브에이전트 프롬프트 (converter, validator, test-generator, reviewer, learner)

skills/                    19개 스킬 (SKILL.md + references)
steering/                  변환 룰셋 + 에지케이스 + DB 설정
schemas/                   10개 JSON Schema (에이전트 간 통신 계약)
tools/                     Python/Java/Shell 도구 (7개)

workspace/
  input/                   변환 대상 XML (불변)
  output/                  변환 완료 XML
  results/                 버전별 중간 결과 (JSON)
  reports/                 리포트 (HTML, Markdown)
  logs/                    감사 로그
```

## 에이전트 아키텍처

| 역할 | 구현 방식 | 모델 |
|------|----------|------|
| **Leader (오케스트레이터)** | CLAUDE.md (항상 자동 로딩) | Opus 4.6 |
| Converter (변환) | Agent tool → .claude/prompts/converter.md | Sonnet 4.6 |
| Test Generator (테스트) | Agent tool → .claude/prompts/test-generator.md | Opus 4.6 |
| Validator (검증) | Agent tool → .claude/prompts/validator.md | Sonnet 4.6 |
| Reviewer (리뷰) | Agent tool → .claude/prompts/reviewer.md | Opus 4.6 |
| Learner (학습) | Agent tool → .claude/prompts/learner.md | Sonnet 4.6 |

## 워크플로우

```
Phase 0    사전 점검 (XML, DB 접속)
Phase 1    XML 파싱 + Oracle 구문 태깅
Phase 1.5  의존성 분석 + 복잡도 L0~L4
Phase 2    레이어별 변환 (리프 우선, 룰+LLM)
Phase 2.5  테스트 케이스 생성
Phase 3    검증 (EXPLAIN → 실행 → 비교 → Guard)
Phase 4    셀프 힐링 (재시도×3)
Phase 5    학습 (steering 갱신, 자동 PR)
Phase 6    리포트 (통합 HTML)
Phase 7    MyBatis 엔진 검증 (옵셔널, Java 필요)
```

## 빠른 시작

### 1. 사전 준비

```bash
# Claude Code 설치
# https://docs.anthropic.com/en/docs/claude-code

# (선택) Oracle/PostgreSQL CLI
# sqlplus: Oracle Instant Client
# psql: PostgreSQL 클라이언트

# (선택) Java 11+ / Gradle: Phase 7용
```

### 2. 환경변수 설정

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

### 3. 실행

```bash
# 변환 대상 XML 배치
cp /path/to/mybatis/*.xml workspace/input/

# Claude Code 실행
claude

# 전체 파이프라인 자동 실행
> 변환해줘

# 또는 슬래시 커맨드
> /convert
```

### 사용 가능한 명령

| 명령 | 동작 |
|------|------|
| `변환해줘` / `/convert` | 전체 Phase 0~7 자동 수행 |
| `X파일만 변환해줘` | 특정 파일만 처리 |
| `다시 검증해줘` | 에스컬레이션 건 재검증 + 학습 |
| `/status` | 진행 상황 확인 |
| `/validate` | Phase 3 검증만 실행 |
| `/report` | HTML 리포트 생성 |
| `/reset` | 결과물 삭제 (input 보존) |

## 스킬 (19개)

| 카테고리 | 스킬 | 역할 |
|---------|------|------|
| 파싱 | parse-xml | MyBatis/iBatis XML 파싱 (28+35 태그) |
| 분석 | query-analyzer | 의존성 그래프 + 복잡도 + 위상 정렬 |
| 분석 | cross-file-analyzer | 파일 간 의존성 분석 |
| 분석 | complex-query-decomposer | 복잡 쿼리 분해 |
| 변환 | rule-convert | 룰 기반 치환 (40+ 룰) |
| 변환 | llm-convert | LLM 기반 복잡 패턴 변환 |
| 변환 | param-type-convert | 파라미터 타입 변환 |
| 변환 | rule-convert-tool | 도구 기반 기계적 변환 |
| SQL 추출 | extract-sql | MyBatis BoundSql API |
| 분할 | xml-splitter | 대형 XML 분할 |
| 테스트 | generate-test-cases | Oracle 딕셔너리 기반 테스트 |
| 검증 | explain-test | PostgreSQL EXPLAIN 검증 |
| 검증 | execute-test | 실행 검증 (트랜잭션+ROLLBACK) |
| 검증 | compare-test | Oracle/PG 결과 비교 |
| DB | db-oracle | sqlplus CLI 접근 |
| DB | db-postgresql | psql CLI 접근 |
| 로깅 | audit-log | 통합 감사 로그 |
| 리포트 | report | 변환 리포트 생성 |
| 학습 | learn-edge-case | 에지케이스 학습 + PR |

## Kiro → Claude Code 매핑

| Kiro | Claude Code |
|------|-------------|
| `.kiro/agents/*.json` | CLAUDE.md (leader) + `.claude/prompts/*.md` (sub) |
| `.kiro/prompts/*.md` | `.claude/prompts/*.md` |
| `.kiro/skills/*/SKILL.md` | `skills/*/SKILL.md` |
| `.kiro/steering/*.md` | `steering/*.md` |
| `.kiro/schemas/*.json` | `schemas/*.json` |
| `.kiro/settings/cli.json` | `.claude/settings.json` |
| Kiro hooks | `.claude/settings.json` hooks |
| `kiro-cli --agent X` | `claude` (CLAUDE.md 자동 로딩) |
| Kiro `subagent` tool | Claude Code `Agent` tool |
| Kiro `resources` 자동 로딩 | Agent prompt에서 `Read` tool로 참조 |

## 산출물

| 경로 | 내용 |
|------|------|
| `workspace/output/` | 변환된 PostgreSQL XML |
| `workspace/results/{file}/v{n}/` | 버전별 중간 결과 |
| `workspace/results/_validation/` | EXPLAIN/실행 검증 결과 |
| `workspace/results/_extracted/` | Phase 7 MyBatis 추출 |
| `workspace/reports/migration-report.html` | 통합 HTML 리포트 |
| `workspace/reports/conversion-report.md` | 변환 리포트 |
| `workspace/logs/activity-log.jsonl` | 감사 로그 |

## 기여

[CONTRIBUTING.md](docs/CONTRIBUTING.md) 참조.

## 라이선스

MIT License
