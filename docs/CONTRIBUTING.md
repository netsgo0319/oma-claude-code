# Contributing Guide — OMA Claude Code

Claude Code 에이전트 시스템의 확장 방법을 설명합니다.

## 새 변환 룰 추가

가장 간단한 기여. `.claude/rules/oracle-pg-rules.md`에 룰을 추가합니다:

```markdown
| Oracle 패턴 | PostgreSQL 패턴 | 비고 |
|------------|----------------|------|
| MY_FUNC(a) | pg_func(a) | 설명 |
```

변환 과정에서 발견된 새 룰은 수동으로 추가합니다.

## 새 에지케이스 추가

`.claude/rules/edge-cases.md`에 항목을 추가합니다:

```markdown
### 패턴 이름
- **Oracle**: 원본 SQL
- **PostgreSQL**: 변환 결과
- **주의**: 주의사항
- **발견일**: YYYY-MM-DD
- **출처**: 파일명#쿼리ID
- **해결 방법**: rule | llm | manual
```

## 새 스킬 추가

1. `.claude/skills/{skill-name}/` 디렉토리 생성
2. `SKILL.md` 작성 (YAML frontmatter 필수):

```markdown
---
name: {skill-name}
description: 스킬 설명 (에이전트가 요청에 매칭할 때 사용)
---

## 입력
...

## 처리 절차
...

## 출력
...
```

3. (선택) `references/` — 참조 문서
4. (선택) `assets/` — 템플릿, 스키마

### 스킬 명명 규칙
- 소문자, 숫자, 하이픈만 (최대 64자)
- 디렉토리명 = frontmatter의 name

## 새 에이전트 추가

1. `.claude/agents/{agent-name}.md` 생성 (Markdown frontmatter 포함)
2. 역할, 입력, 처리 절차, 출력 형식, 안전 규칙을 문서화
3. 현재 에이전트: `converter` (변환), `validate-and-fix` (검증+수정 루프)

## 새 Rules 파일 추가

`.claude/rules/{name}.md` 생성:

변환 룰이나 에지케이스를 Markdown 테이블/리스트로 작성.
에이전트가 자동으로 참조합니다.

## JSON Schema 검증

에이전트 간 통신 아티팩트는 `schemas/`에 정의된 JSON Schema를 따릅니다:

| 스키마 | 생성 주체 | 소비 주체 |
|--------|-------------|-------------|
| parsed.schema.json | parse-xml 도구 | Converter |
| converted.schema.json | Converter | validate-and-fix |
| test-cases.schema.json | generate-test-cases 도구 | validate-and-fix |
| validated.schema.json | validate-and-fix | Leader |
| review.schema.json | validate-and-fix | Converter (재시도) |
| dependency-graph.schema.json | query-analyzer 도구 | Converter |
| complexity-scores.schema.json | query-analyzer 도구 | Converter |
| conversion-order.schema.json | query-analyzer 도구 | Converter |
| cross-file-graph.schema.json | cross-file-analyzer 스킬 | Converter |
| transform-plan.schema.json | Converter | validate-and-fix |

## 디렉토리 구조

```
.claude/
  agents/         에이전트 Markdown 정의
  commands/       슬래시 커맨드 (/convert, /validate 등)
  rules/          변환 룰 + 에지케이스
  skills/         스킬 (SKILL.md + references/ + assets/)
schemas/          JSON Schema 정의
tools/
  *.py            Python 도구 (파싱, 변환, 검증, 분석, 리포트)
  *.sh            Shell 래퍼 (초기화, 배치 처리)
  mybatis-sql-extractor/   Java/Gradle MyBatis SQL 추출기
workspace/
  input/          변환 대상 XML (불변)
  output/         변환 결과 XML
  results/        버전별 중간 산출물 + 검증 결과 + 추출 결과
  reports/        최종 리포트 (HTML + Markdown)
  logs/           감사 로그
docs/
  superpowers/    설계 스펙 + 구현 플랜
```

## 새 Python 도구 추가

`tools/` 디렉토리에 Python 스크립트를 추가합니다:

1. `#!/usr/bin/env python3` + docstring에 Usage 포함
2. `argparse`로 CLI 인터페이스 구성
3. CLAUDE.md의 도구 테이블에 추가

기존 도구:
- `xml-splitter.py`, `parse-xml.py`, `query-analyzer.py` — Step 1 (파싱)
- `oracle-to-pg-converter.py` — Step 1 (40+ 변환 룰)
- `validate-queries.py` — Step 3 (`--full`, `--generate`, `--local`, `--execute`, `--parse-results`, `--extracted`)
- `generate-report.py` — Step 4 (통합 HTML 리포트)

### validate-queries.py 모드

| 모드 | 용도 |
|------|------|
| `--generate` | SQL 테스트 스크립트 생성 (EXPLAIN + 실행 + SSM 배치) |
| `--local` | psql로 EXPLAIN 로컬 실행 |
| `--compare` | **Oracle vs PG 양쪽 실행 + 결과 비교** (SELECT: row/값, DML: affected rows) |
| `--execute` | PG만 실행 (Oracle 접속 불가 시 폴백) |
| `--parse-results` | 외부 실행 결과 파싱 |
| `--extracted` | MyBatis 추출 JSON 로드 |

## 체크리스트

새 컴포넌트 추가 시 확인:
- [ ] SKILL.md에 name/description frontmatter가 있는가?
- [ ] 에이전트 .md 파일에 역할과 처리 절차가 명확한가?
- [ ] CLAUDE.md의 도구/에이전트 테이블이 업데이트되었는가?
- [ ] Python 도구가 py_compile을 통과하는가?
