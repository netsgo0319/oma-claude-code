# Contributing Guide — OMA Kiro

Kiro 에이전트 시스템의 확장 방법을 설명합니다.

## 새 변환 룰 추가

가장 간단한 기여. `.kiro/steering/oracle-pg-rules.md`에 룰을 추가합니다:

```markdown
| Oracle 패턴 | PostgreSQL 패턴 | 비고 |
|------------|----------------|------|
| MY_FUNC(a) | pg_func(a) | 설명 |
```

Learner 에이전트가 자동으로 발견한 룰은 PR로 제출됩니다.

## 새 에지케이스 추가

`.kiro/steering/edge-cases.md`에 항목을 추가합니다:

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

1. `.kiro/skills/{skill-name}/` 디렉토리 생성
2. `SKILL.md` 작성 (YAML frontmatter 필수):

```markdown
---
name: {skill-name}
description: 스킬 설명 (Kiro가 요청에 매칭할 때 사용, 최대 1024자)
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
5. 사용할 에이전트의 `resources`에 추가:

```json
"resources": [
  "skill://.kiro/skills/{skill-name}/SKILL.md"
]
```

### 스킬 명명 규칙
- 소문자, 숫자, 하이픈만 (최대 64자)
- 디렉토리명 = frontmatter의 name

## 새 에이전트 추가

1. `.kiro/agents/{agent-name}.json` 생성:

```json
{
  "name": "{agent-name}",
  "description": "에이전트 설명",
  "prompt": "file://../prompts/{agent-name}.md",
  "model": "claude-sonnet-4.6",
  "tools": ["read", "write"],
  "allowedTools": ["read"],
  "resources": [
    "file://.kiro/steering/oracle-pg-rules.md",
    "skill://.kiro/skills/{skill-name}/SKILL.md"
  ]
}
```

2. `.kiro/prompts/{agent-name}.md` 작성 — 역할, 입력, 처리 절차, 출력 형식, 안전 규칙

3. Leader에 등록 (서브에이전트로 사용할 경우):
   - `oracle-pg-leader.json`의 `toolsSettings.subagent.availableAgents`에 추가
   - 자동 실행 허용 시 `trustedAgents`에도 추가

### 에이전트 필수 필드
| 필드 | 필수 | 설명 |
|------|------|------|
| name | O | 에이전트 식별자 |
| description | O | 역할 설명 |
| prompt | O | 프롬프트 파일 경로 (`file://` URI) |
| model | O | 모델 (claude-sonnet-4.6 또는 claude-opus-4.6) |
| tools | O | 사용 가능한 도구 배열 |
| allowedTools | - | 자동 허용 도구 (나머지는 사용자 확인 필요) |
| resources | - | 참조할 steering/skill 파일 |
| hooks | - | 라이프사이클 훅 |
| toolsSettings | - | 도구별 세부 설정 |

### DB 접근이 필요한 에이전트
shell 도구 + db-oracle/db-postgresql 스킬을 사용합니다:

```json
{
  "tools": ["read", "write", "shell"],
  "toolsSettings": {
    "shell": {
      "allowedCommands": ["psql", "sqlplus", "echo"],
      "deniedCommands": ["rm", "mv", "chmod", "chown", "curl", "wget", "sudo", "kill"]
    }
  },
  "resources": [
    "skill://.kiro/skills/db-postgresql/SKILL.md"
  ]
}
```

**반드시 SQL 안전 훅을 추가하세요:**

```json
"hooks": {
  "preToolUse": [
    {
      "matcher": "execute_bash",
      "command": "printf '%s' \"$KIRO_TOOL_INPUT\" | python3 -c \"import sys; data=sys.stdin.read().upper(); dangerous=['DROP ','TRUNCATE ','ALTER ','CREATE ','GRANT ','REVOKE ']; matches=[d for d in dangerous if d in data]; sys.exit(1) if matches else sys.exit(0)\" || (echo 'BLOCKED: Destructive SQL detected' && exit 1)"
    }
  ]
}
```

## 새 Steering 파일 추가

`.kiro/steering/{name}.md` 생성:

```markdown
---
inclusion: always | manual
---

# 제목
...
```

| inclusion | 용도 |
|-----------|------|
| always | 모든 에이전트에 항상 로드 (지식, 규칙) |
| manual | 사용자가 #name으로 명시적 호출 시에만 로드 (설정, 민감 정보) |

## JSON Schema 검증

에이전트 간 통신 아티팩트는 `.kiro/schemas/`에 정의된 JSON Schema를 따릅니다:

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

## 디렉토리 구조

```
.kiro/
  agents/         에이전트 JSON 설정
  prompts/        에이전트 프롬프트
  skills/         스킬 (SKILL.md + references/ + assets/)
  steering/       스티어링 (persistent context)
  schemas/        JSON Schema 정의
tools/
  *.py            Python 도구 (파싱, 변환, 검증, 분석, 리포트)
  *.sh            Shell 래퍼 (초기화, Phase 7)
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
3. Leader 프롬프트(`oracle-pg-leader.md`)의 도구 테이블에 추가
4. tech.md 도구 테이블에도 추가

기존 도구:
- `xml-splitter.py`, `parse-xml.py`, `query-analyzer.py` — Phase 1/1.5
- `oracle-to-pg-converter.py` — Phase 2 (40+ 변환 룰)
- `validate-queries.py` — Phase 3 (`--generate`, `--local`, `--execute`, `--parse-results`, `--extracted`)
- `generate-report.py` — Phase 6 (통합 HTML 리포트)

### validate-queries.py 모드

| 모드 | 용도 |
|------|------|
| `--generate` | SQL 테스트 스크립트 생성 (EXPLAIN + 실행 + SSM 배치) |
| `--local` | psql로 EXPLAIN 로컬 실행 |
| `--execute` | psql로 실제 쿼리 실행 (row count 수집) |
| `--parse-results` | 외부 실행 결과 파싱 |
| `--extracted` | Phase 7 MyBatis 추출 JSON 로드 |

## 체크리스트

새 컴포넌트 추가 시 확인:
- [ ] JSON 파일은 유효한가? (`python3 -c "import json; json.load(open('file'))"`)
- [ ] SKILL.md에 name/description frontmatter가 있는가?
- [ ] 에이전트 JSON의 prompt 파일이 존재하는가?
- [ ] resources에 참조한 steering/skill 파일이 존재하는가?
- [ ] DB 접근 에이전트에 SQL 안전 훅이 있는가?
- [ ] shell 사용 에이전트에 deniedCommands가 설정되었는가?
