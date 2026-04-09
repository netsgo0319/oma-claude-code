# Contributing Guide — OMA Claude Code

Claude Code 에이전트 시스템의 확장 방법을 설명합니다.

## 새 변환 룰 추가

가장 간단한 기여. `steering/oracle-pg-rules.md`에 룰을 추가합니다:

```markdown
| Oracle 패턴 | PostgreSQL 패턴 | 비고 |
|------------|----------------|------|
| MY_FUNC(a) | pg_func(a) | 설명 |
```

Learner 에이전트가 자동으로 발견한 룰은 PR로 제출됩니다.

## 새 에지케이스 추가

`steering/edge-cases.md`에 항목을 추가합니다:

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

1. `skills/{skill-name}/` 디렉토리 생성
2. `SKILL.md` 작성 (YAML frontmatter 필수):

```markdown
---
name: {skill-name}
description: 스킬 설명 (에이전트가 Read로 로딩할 때 목적 파악용, 최대 1024자)
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
5. (선택) `fixtures/` — 테스트 입력/기대 출력 데이터
6. 사용할 에이전트의 `Setup: Load Knowledge` 섹션에 Read 경로 추가:

```markdown
## Setup: Load Knowledge

작업 시작 전 반드시 Read tool로 아래 파일을 로딩하라:
1. `skills/{skill-name}/SKILL.md` — 설명
```

7. CLAUDE.md의 스킬 참조 테이블에 추가:

```markdown
| {skill-name} | skills/{skill-name}/SKILL.md | Phase N |
```

### 스킬 명명 규칙
- 소문자, 숫자, 하이픈만 (최대 64자)
- 디렉토리명 = frontmatter의 name

### Claude Code에서의 스킬 로딩

Kiro와 달리 Claude Code에는 `resources` 자동 로딩이 없습니다. 대신:
- 에이전트의 프롬프트 본문에 `Read tool로 {path}를 로딩하라`고 명시
- Leader(CLAUDE.md)의 스킬 참조 테이블에 등록하면 Leader가 서브에이전트에게 관련 스킬 경로를 전달

```markdown
# 에이전트 프롬프트 내에서
## Setup: Load Knowledge
작업 시작 전 반드시 Read tool로 아래 파일을 로딩하라:
1. `skills/rule-convert/SKILL.md` — 룰 기반 변환 절차
2. `steering/oracle-pg-rules.md` — 변환 룰셋
```

## 새 에이전트 추가

### 1. 에이전트 파일 생성

`.claude/agents/{agent-name}.md` 파일을 만듭니다. Claude Code에서는 **에이전트 설정과 프롬프트가 하나의 Markdown 파일**에 통합됩니다:

```markdown
---
name: {agent-name}
model: sonnet
description: 에이전트 역할 설명
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

# {Agent Title}

당신은 {역할}을 수행하는 서브에이전트입니다.

## Setup: Load Knowledge

작업 시작 전 반드시 Read tool로 아래 파일을 로딩하라:
1. `steering/oracle-pg-rules.md` — 변환 룰셋
2. `skills/{skill-name}/SKILL.md` — 관련 스킬

## 핵심 원칙
...

## 처리 절차
...

## 로깅 (필수)
모든 활동을 workspace/logs/activity-log.jsonl에 기록.

## Return
한 줄 요약: "..."
```

### 2. CLAUDE.md에 등록

서브에이전트로 사용할 경우 CLAUDE.md의 에이전트 테이블에 추가합니다:

```markdown
| {agent-name} | .claude/agents/{agent-name}.md | {model} | {역할} |
```

그리고 해당 Phase 섹션에 위임 패턴을 기술합니다:

```markdown
**Agent tool로 서브에이전트 위임:**
- Phase N {설명} → {agent-name} (model: {model})
```

### 3. Leader에서 호출

CLAUDE.md(Leader 역할)에서 Agent tool의 `subagent_type`으로 호출합니다:

```
Agent({
  description: "Phase N: {설명} - {filename}",
  subagent_type: "{agent-name}",
  prompt: "대상 파일: {filename}, 버전: v{n}, {구체적 지시}"
})
```

### 에이전트 frontmatter 필드

| 필드 | 필수 | 설명 |
|------|------|------|
| name | O | 에이전트 식별자 (`subagent_type`으로 사용) |
| model | O | `sonnet` 또는 `opus` |
| description | O | 역할 설명 |
| allowed-tools | O | 사용 가능한 도구 배열 |

### Kiro와의 차이점

| Kiro 방식 | Claude Code 방식 |
|-----------|-----------------|
| `agents/{name}.json` (설정) + `prompts/{name}.md` (프롬프트) 분리 | `.claude/agents/{name}.md` 하나에 통합 (frontmatter = 설정, body = 프롬프트) |
| `"prompt": "file://../prompts/{name}.md"` 참조 | 프롬프트가 파일 본문 자체 |
| `"resources": ["skill://...", "file://..."]` 자동 로딩 | 프롬프트 내 `Setup: Load Knowledge`에서 Read tool로 명시적 로딩 |
| `"tools": ["read", "write", "shell"]` | `allowed-tools:` YAML 배열 (`Read`, `Write`, `Bash` 등 Claude Code 도구명) |
| `"toolsSettings": { "shell": { ... } }` | `.claude/settings.json`의 `permissions` 섹션 (전역) |
| `"hooks": { "preToolUse": [...] }` | `.claude/settings.json`의 `hooks` 섹션 (전역) |
| `kiro-cli --agent X` | `claude` (CLAUDE.md가 Leader로 자동 로드) |
| Kiro subagent tool | `Agent` tool + `subagent_type` 파라미터 |

### 모델 선택 가이드

| 용도 | 모델 | 이유 |
|------|------|------|
| 기계적 변환, 검증, 학습 | sonnet | 비용 효율 + 충분한 정확도 |
| 복잡 분석, 리뷰, 테스트 생성 | opus | 추론 깊이 필요 |

### DB 접근이 필요한 에이전트

Bash tool + db-oracle/db-postgresql 스킬을 사용합니다:

```markdown
---
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
---

## Setup: Load Knowledge
1. `skills/db-postgresql/SKILL.md` — DB 접속 절차
2. `steering/db-config.md` — 접속 정보
```

**SQL 안전 제어는 `.claude/settings.json`에서 전역으로 관리됩니다** (에이전트별 훅 불필요):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c '... DDL 블로킹 스크립트 ...'"
          }
        ]
      }
    ]
  },
  "permissions": {
    "deny": ["Bash(rm *)", "Bash(chmod *)", "Bash(curl *)", "Bash(wget *)", "Bash(sudo *)", "Bash(kill *)"]
  }
}
```

## 새 Steering 파일 추가

`steering/{name}.md` 생성:

```markdown
# 제목

내용...
```

Claude Code에서 steering 파일은 자동 로딩되지 않습니다. 반드시 아래 두 곳에 등록해야 합니다:

1. **CLAUDE.md**에 참조 경로 기록 (Leader가 인지하도록):

```markdown
## 스킬 참조
...
| {name} | steering/{name}.md | 전체 또는 특정 Phase |
```

2. **에이전트 프롬프트**의 `Setup: Load Knowledge`에 추가:

```markdown
## Setup: Load Knowledge
N. `steering/{name}.md` — 설명
```

### steering vs skills 구분

| 유형 | 위치 | 용도 | 예시 |
|------|------|------|------|
| steering | `steering/` | 지식/룰/설정 (수정 가능, Learner가 갱신) | oracle-pg-rules.md, edge-cases.md, db-config.md |
| skill | `skills/*/SKILL.md` | 절차 정의 (입력→처리→출력 구조화) | rule-convert, llm-convert, explain-test |

## 새 커맨드 추가

`.claude/commands/{command-name}.md` 파일을 생성합니다. 사용자가 `/command-name`으로 호출합니다:

```markdown
{커맨드가 수행할 내용에 대한 자연어 지시}

## Instructions

1. {단계 1}
2. {단계 2}
3. ...

## Arguments

$ARGUMENTS

인자가 제공되면:
- `--flag` — 설명
```

기존 커맨드:

| 커맨드 | 파일 | 용도 |
|--------|------|------|
| /convert | `.claude/commands/convert.md` | 전체 파이프라인 실행 (Phase 0~7) |
| /status | `.claude/commands/status.md` | progress.json 기반 현황 조회 |
| /reset | `.claude/commands/reset.md` | workspace 초기화 |
| /validate | `.claude/commands/validate.md` | Phase 3 검증만 실행 |
| /report | `.claude/commands/report.md` | Phase 6 리포트만 생성 |

### 커맨드 작성 규칙
- 커맨드 파일은 CLAUDE.md의 지시를 반복하지 않는다 — "CLAUDE.md를 Read하라"로 위임
- `$ARGUMENTS`로 사용자 인자를 받을 수 있다
- 복잡한 로직은 커맨드에 넣지 않고 CLAUDE.md + 에이전트에 위임

## JSON Schema 검증

에이전트 간 통신 아티팩트는 `schemas/`에 정의된 JSON Schema를 따릅니다:

| 스키마 | 생성 에이전트 | 소비 에이전트 |
|--------|-------------|-------------|
| parsed.schema.json | Leader (parse-xml) | Converter |
| converted.schema.json | Converter | Validator |
| test-cases.schema.json | Test Generator | Validator |
| validated.schema.json | Validator | Reviewer, Leader |
| review.schema.json | Reviewer | Converter (재시도) |
| dependency-graph.schema.json | Leader (query-analyzer) | Converter |
| complexity-scores.schema.json | Leader (query-analyzer) | Converter |
| conversion-order.schema.json | Leader (query-analyzer) | Converter |
| cross-file-graph.schema.json | Leader (cross-file-analyzer) | Converter |
| transform-plan.schema.json | Converter | Validator |

### 새 스키마 추가

1. `schemas/{name}.schema.json` 생성 (JSON Schema Draft 2020-12):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "{Name}",
  "description": "설명",
  "type": "object",
  "required": ["version", "timestamp", ...],
  "properties": {
    "version": { "type": "integer" },
    "timestamp": { "type": "string", "format": "date-time" },
    ...
  }
}
```

2. 생성 에이전트 프롬프트에 출력 규칙 추가:

```markdown
## 결과 기록
- **출력 JSON은 schemas/{name}.schema.json에 맞게 작성**
```

3. 소비 에이전트 프롬프트에 입력 명세 추가:

```markdown
## 입력
- workspace/results/{filename}/v{n}/{name}.json (schemas/{name}.schema.json 준수)
```

4. 이 파일(CONTRIBUTING.md)의 스키마 테이블 갱신

## settings.json 훅 관리

`.claude/settings.json`은 전역 훅과 권한을 정의합니다. Kiro에서는 에이전트별 hooks가 있었지만, Claude Code에서는 **settings.json에 전역으로 통합**됩니다.

### 훅 종류

| 훅 | 시점 | 현재 용도 |
|----|------|----------|
| PreToolUse | 도구 실행 직전 | DDL(DROP/TRUNCATE/ALTER 등) 차단 |
| PostToolUse | 도구 실행 직후 | DB 쿼리 실행 감사 로깅 |
| Stop | 에이전트 응답 완료 시 | 파이프라인 진행 상황 요약 |

### 새 훅 추가 예시

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c '... 검증 스크립트 ...'"
          }
        ]
      }
    ]
  }
}
```

- `matcher`: 훅이 적용될 도구 이름 (`Bash`, `Write`, `Edit` 등). 빈 문자열 `""`은 모든 도구에 적용
- 훅 command는 stdin으로 도구 입력을 받고, exit 1이면 도구 실행을 차단
- PostToolUse 훅은 도구 출력을 stdin으로 받음

### 권한 관리

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 tools/*)",
      "Bash(bash tools/*)",
      "Read",
      "Write"
    ],
    "deny": [
      "Bash(rm *)",
      "Bash(sudo *)"
    ]
  }
}
```

- `allow`: 사용자 확인 없이 자동 실행 허용
- `deny`: 완전 차단 (실행 불가)
- allow/deny 모두에 없는 도구 호출은 사용자에게 확인 요청

## 새 Python 도구 추가

`tools/` 디렉토리에 Python 스크립트를 추가합니다:

1. `#!/usr/bin/env python3` + docstring에 Usage 포함
2. `argparse`로 CLI 인터페이스 구성
3. CLAUDE.md의 도구 테이블에 추가:

```markdown
| `tools/{name}.py` | {Phase} | `python3 tools/{name}.py {args}` |
```

4. `.claude/settings.json`의 `permissions.allow`에 실행 허용 추가:

```json
"Bash(python3 tools/*)"
```

(현재 와일드카드 `tools/*`로 전체 허용되어 있으므로 별도 추가 불필요)

5. (선택) docs/tech.md 도구 테이블에도 추가

기존 도구:

| 도구 | Phase | 용도 |
|------|-------|------|
| `xml-splitter.py` | 1 | 대형 XML 분할 |
| `parse-xml.py` | 1 | MyBatis XML → parsed.json |
| `query-analyzer.py` | 1.5 | 의존성 분석 + 복잡도 분류 |
| `oracle-to-pg-converter.py` | 2 | 40+ 룰 기반 기계적 변환 |
| `validate-queries.py` | 3 | EXPLAIN/실행/비교 검증 |
| `view-results.py` | — | 결과 조회 유틸리티 |
| `generate-report.py` | 6 | 통합 HTML 리포트 |
| `run-extractor.sh` | 7 | MyBatis 엔진 SQL 추출 |
| `reset-workspace.sh` | 초기화 | workspace 리셋 |

### validate-queries.py 모드

| 모드 | 용도 |
|------|------|
| `--generate` | SQL 테스트 스크립트 생성 (EXPLAIN + 실행 + SSM 배치) |
| `--local` | psql로 EXPLAIN 로컬 실행 |
| `--execute` | psql로 실제 쿼리 실행 (row count 수집) |
| `--parse-results` | 외부 실행 결과 파싱 |
| `--extracted` | Phase 7 MyBatis 추출 JSON 로드 |

## 디렉토리 구조

```
.claude/
  agents/          에이전트 Markdown (frontmatter + 프롬프트 통합)
  commands/        커맨드 정의 (/convert, /status 등)
  settings.json    전역 훅 + 권한 관리
skills/            스킬 (SKILL.md + references/ + assets/ + fixtures/)
steering/          스티어링 (변환 룰셋 + 에지케이스 + DB 설정)
schemas/           JSON Schema 정의 (에이전트 간 통신 계약)
tools/
  *.py             Python 도구 (파싱, 변환, 검증, 분석, 리포트)
  *.sh             Shell 래퍼 (초기화, Phase 7)
  mybatis-sql-extractor/   Java/Gradle MyBatis SQL 추출기
workspace/
  input/           변환 대상 XML (불변)
  output/          변환 결과 XML
  results/         버전별 중간 산출물 + 검증 결과 + 추출 결과
  reports/         최종 리포트 (HTML + Markdown)
  logs/            감사 로그
  progress.json    파이프라인 진행 상황
CLAUDE.md          Leader 에이전트 프롬프트 (진입점, 자동 로드)
docs/
  CONTRIBUTING.md  이 파일
```

### Kiro → Claude Code 경로 매핑

| Kiro 경로 | Claude Code 경로 |
|-----------|-----------------|
| `.kiro/agents/*.json` | `.claude/agents/*.md` |
| `.kiro/prompts/*.md` | `.claude/agents/*.md` (본문에 포함) |
| `.kiro/skills/*/SKILL.md` | `skills/*/SKILL.md` |
| `.kiro/steering/*.md` | `steering/*.md` |
| `.kiro/schemas/*.json` | `schemas/*.json` |
| `.kiro/settings/cli.json` | `.claude/settings.json` |

## 체크리스트

### 새 에이전트 추가 시

- [ ] `.claude/agents/{name}.md` 파일 생성
- [ ] frontmatter에 `name`, `model`, `description`, `allowed-tools` 포함
- [ ] 프롬프트 본문에 `Setup: Load Knowledge` 섹션 (Read할 파일 목록)
- [ ] 프롬프트에 `처리 절차`, `로깅 (필수)`, `Return` 섹션 포함
- [ ] CLAUDE.md 에이전트 테이블에 등록
- [ ] CLAUDE.md 해당 Phase 워크플로우에 위임 패턴 추가
- [ ] DB 접근 에이전트인 경우 `.claude/settings.json`에 DDL 차단 훅 확인

### 새 스킬 추가 시

- [ ] `skills/{name}/` 디렉토리 생성
- [ ] `SKILL.md`에 `name`/`description` frontmatter 포함
- [ ] `입력`, `처리 절차`, `출력` (또는 `주의사항`) 섹션 포함
- [ ] 참조 문서가 있으면 `references/` 하위에 배치
- [ ] 사용할 에이전트의 `Setup: Load Knowledge`에 Read 경로 추가
- [ ] CLAUDE.md 스킬 참조 테이블에 등록

### 새 steering 파일 추가 시

- [ ] `steering/{name}.md` 파일 생성
- [ ] CLAUDE.md에 참조 경로 기록
- [ ] 사용할 에이전트의 `Setup: Load Knowledge`에 추가
- [ ] Learner가 갱신할 수 있는 파일이면 learner.md 프롬프트에도 경로 추가

### 새 스키마 추가 시

- [ ] `schemas/{name}.schema.json` 생성 (JSON Schema Draft 2020-12)
- [ ] `python3 -c "import json; json.load(open('schemas/{name}.schema.json'))"` 검증 통과
- [ ] 생성 에이전트 프롬프트에 출력 규칙 추가
- [ ] 소비 에이전트 프롬프트에 입력 명세 추가
- [ ] 이 파일(CONTRIBUTING.md)의 스키마 테이블에 추가

### 새 Python 도구 추가 시

- [ ] `tools/{name}.py` 생성 (shebang + docstring + argparse)
- [ ] CLAUDE.md 도구 테이블에 추가
- [ ] `.claude/settings.json`의 `permissions.allow`에서 패턴 매칭 확인 (`Bash(python3 tools/*)`)
- [ ] 실행 권한 부여: `chmod +x tools/{name}.py`

### 새 커맨드 추가 시

- [ ] `.claude/commands/{name}.md` 파일 생성
- [ ] Instructions 섹션에 단계별 지시 작성
- [ ] `$ARGUMENTS` 플레이스홀더로 사용자 인자 수신 처리
- [ ] 복잡한 로직은 CLAUDE.md/에이전트에 위임하고 커맨드는 진입점만

### 새 훅 추가 시

- [ ] `.claude/settings.json`의 적절한 훅 섹션(PreToolUse/PostToolUse/Stop)에 추가
- [ ] `matcher`가 올바른 도구명인지 확인 (빈 문자열 = 전체 도구)
- [ ] 훅 command가 stdin 입력을 올바르게 처리하는지 확인
- [ ] PreToolUse 차단 훅은 실패 시 exit 1 + stderr 메시지 출력
- [ ] 기존 훅과 충돌하지 않는지 확인

## 에이전트 시스템 아키텍처 요약

```
사용자 → claude CLI → CLAUDE.md (Leader, 자동 로드)
                         │
                         ├── 직접 실행: Bash tool → tools/*.py, tools/*.sh
                         │
                         ├── Agent tool (subagent_type: "converter")
                         │     └── .claude/agents/converter.md
                         │           ├── frontmatter: model, allowed-tools
                         │           ├── Setup: Read → steering/, skills/
                         │           └── 프롬프트 본문 (역할, 절차, 출력)
                         │
                         ├── Agent tool (subagent_type: "validator")
                         │     └── .claude/agents/validator.md
                         │
                         ├── Agent tool (subagent_type: "test-generator")
                         │     └── .claude/agents/test-generator.md
                         │
                         ├── Agent tool (subagent_type: "reviewer")
                         │     └── .claude/agents/reviewer.md
                         │
                         └── Agent tool (subagent_type: "learner")
                               └── .claude/agents/learner.md

전역 제어: .claude/settings.json
  ├── hooks.PreToolUse  → DDL 차단
  ├── hooks.PostToolUse → DB 감사 로깅
  ├── hooks.Stop        → 진행 요약
  └── permissions       → allow/deny 목록
```
