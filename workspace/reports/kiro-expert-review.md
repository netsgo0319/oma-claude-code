# Kiro Agent System Expert Review

**프로젝트:** Oracle -> PostgreSQL Migration Accelerator  
**리뷰 일자:** 2026-04-09  
**검토 범위:** `.kiro/` 내 전체 에이전트 시스템 (agents, prompts, skills, steering, schemas, settings)  
**리뷰어:** Kiro Expert (Opus 4.6)

---

## 목차

1. [Agent JSON 스펙 준수](#1-agent-json-스펙-준수)
2. [Skill SKILL.md 형식](#2-skill-skillmd-형식)
3. [Steering inclusion 모드](#3-steering-inclusion-모드)
4. [Hook 설계](#4-hook-설계)
5. [Subagent 설정](#5-subagent-설정)
6. [Resource 경로](#6-resource-경로)
7. [tools/allowedTools 설정](#7-toolsallowedtools-설정)
8. [settings/cli.json](#8-settingsclijson)
9. [welcomeMessage](#9-welcomemessage)
10. [개선 가능점](#10-개선-가능점)

---

## 1. Agent JSON 스펙 준수

### 1.1 전체 평가: **양호 (주의사항 있음)**

6개 에이전트 JSON 파일을 모두 검토하였다. 기본적인 구조(name, description, prompt, model, tools, resources)는 올바르게 작성되어 있다.

### 1.2 발견된 이슈

#### ISSUE-1: model 필드의 비표준 모델명 (모든 에이전트)

| 파일 | 라인 | 현재 값 | 비고 |
|------|------|---------|------|
| `oracle-pg-leader.json` | 6 | `claude-opus-4.6` | Kiro 표준 모델 식별자 확인 필요 |
| `converter.json` | 5 | `claude-sonnet-4.6` | 동일 |
| `test-generator.json` | 5 | `claude-opus-4.6` | 동일 |
| `validator.json` | 5 | `claude-sonnet-4.6` | 동일 |
| `reviewer.json` | 5 | `claude-opus-4.6` | 동일 |
| `learner.json` | 5 | `claude-sonnet-4.6` | 동일 |

**분석:** Kiro IDE/CLI에서 사용 가능한 모델 식별자는 런타임 환경에 따라 다를 수 있다. `claude-opus-4.6`과 `claude-sonnet-4.6`은 공식 Anthropic 모델명으로 유효하지만, Kiro가 내부적으로 다른 식별자(예: `claude-sonnet-4-20250514`)를 사용할 수 있으므로 실행 시 `model not found` 에러가 발생하지 않는지 확인이 필요하다.

**권장:** 첫 실행 시 모델 바인딩이 정상인지 확인하고, Kiro CLI의 `--list-models` 출력과 대조한다.

#### ISSUE-2: tool 이름 `shell` vs `execute_bash` 불일치 (잠재적)

| 파일 | 라인 | tools 배열 | hook matcher |
|------|------|-----------|-------------|
| `test-generator.json` | 9 | `"shell"` | N/A |
| `validator.json` | 9 | `"shell"` | `"execute_bash"` (라인 47) |
| `reviewer.json` | 9 | `"shell"` | `"execute_bash"` (라인 42) |
| `learner.json` | 11 | `"shell"` | N/A |

**분석:** `tools` 배열에서는 `"shell"`로 정의하고, `hooks.preToolUse.matcher`에서는 `"execute_bash"`를 사용한다. Kiro CLI에서 shell 도구의 내부 식별자가 `execute_bash`인 경우에는 문제가 없다. 그러나 `"shell"`이 올바른 도구명이라면 matcher도 `"shell"`이어야 하며, 반대로 `"execute_bash"`가 올바른 도구명이라면 tools 배열에서도 `"execute_bash"`를 사용해야 한다.

**위험도:** 중간. hook가 fire되지 않으면 Destructive SQL Guard가 작동하지 않게 되어 **보안 취약점**이 된다.

**권장:** Kiro CLI 환경에서 shell 도구의 정확한 식별자를 확인하여 tools 배열과 matcher를 통일한다.

#### ISSUE-3: prompt 경로의 상대 참조 방식

| 파일 | 라인 | 값 |
|------|------|----|
| `oracle-pg-leader.json` | 4 | `"file://../prompts/oracle-pg-leader.md"` |
| `converter.json` | 4 | `"file://../prompts/converter.md"` |
| (기타 4개 에이전트) | 4 | 동일 패턴 |

**분석:** `file://` 프로토콜에서 `..` 상대 경로를 사용한다. 이 경로의 기준점은 에이전트 JSON 파일의 위치(`.kiro/agents/`)인데, `../prompts/`로 가면 `.kiro/prompts/`가 된다. Kiro CLI가 이 상대 경로를 에이전트 JSON 기준으로 해석하는지, 아니면 프로젝트 루트 기준으로 해석하는지에 따라 동작이 달라진다.

**권장:** 프로젝트 루트 기준 절대 경로 `file://.kiro/prompts/oracle-pg-leader.md` 형식으로 통일하면 안전하다. resources 배열에서는 이미 `file://.kiro/steering/**/*.md` 처럼 루트 기준 경로를 사용하고 있으므로, prompt 필드도 동일 방식이 일관성 있다.

#### ISSUE-4: oracle-pg-leader.json의 resources에 중복 skill 참조

**파일:** `oracle-pg-leader.json` 라인 36-39
```json
"resources": [
    "file://.kiro/steering/**/*.md",
    "skill://.kiro/skills/**/SKILL.md",      // 모든 스킬
    "skill://.kiro/skills/audit-log/SKILL.md",  // 중복
    "skill://.kiro/skills/query-analyzer/SKILL.md"  // 중복
]
```

**분석:** `skill://.kiro/skills/**/SKILL.md` 글로브가 이미 모든 스킬을 포함하므로, audit-log과 query-analyzer를 개별 명시하는 것은 중복이다.

**영향:** 기능적 문제는 없으나, 유지보수 시 혼란을 줄 수 있다.

**권장:** 글로브 패턴 하나로 충분하므로 개별 항목을 제거하거나, 반대로 글로브를 제거하고 필요한 스킬만 개별 명시한다 (최소 권한 원칙 관점에서 후자 권장).

### 1.3 양호한 점

- 모든 에이전트에 `name`, `description`, `prompt`, `model`, `tools` 필수 필드가 존재한다.
- 서브에이전트 전용 에이전트(converter, validator 등)에는 `subagent` 도구가 없어 재귀 호출을 방지한다.
- `toolsSettings.shell.deniedCommands`로 위험 명령어를 일관되게 차단한다.

---

## 2. Skill SKILL.md 형식

### 2.1 전체 평가: **양호**

17개 스킬 파일 모두 YAML frontmatter에 `name`과 `description`이 존재한다.

### 2.2 검토 결과

| 스킬 | name | description | 형식 준수 |
|------|------|-------------|----------|
| parse-xml | O | O (상세) | 정상 |
| rule-convert | O | O (상세) | 정상 |
| llm-convert | O | O (상세) | 정상 |
| generate-test-cases | O | O (상세) | 정상 |
| explain-test | O | O (상세) | 정상 |
| execute-test | O | O (상세) | 정상 |
| compare-test | O | O (상세) | 정상 |
| learn-edge-case | O | O (상세) | 정상 |
| db-oracle | O | O (상세) | 정상 |
| db-postgresql | O | O (상세) | 정상 |
| audit-log | O | O (상세) | 정상 |
| extract-sql | O | O (상세) | 정상 |
| query-analyzer | O | O (상세) | 정상 |
| report | O | O (상세) | 정상 |
| param-type-convert | O | O (상세) | 정상 |
| cross-file-analyzer | O | O (상세) | 정상 |
| complex-query-decomposer | O | O (상세) | 정상 |

### 2.3 권장 추가 필드

Kiro 스킬 시스템에서 frontmatter에 추가할 수 있는 유용한 필드:

1. **`version`**: 스킬 버전 관리. 현재 스킬 문서가 진화할 때 버전 추적이 없다.
2. **`tags`**: 검색/분류를 위한 태그 (예: `["sql", "oracle", "conversion"]`)
3. **`requires`**: 이 스킬이 의존하는 다른 스킬이나 도구 (예: `requires: [db-oracle, sqlplus]`)
4. **`input_schema`**: 입력 JSON 스키마 참조 (예: `input_schema: parsed.schema.json`)
5. **`output_schema`**: 출력 JSON 스키마 참조

현재 스킬-스키마 간 연결이 암묵적(스킬 본문에서 텍스트로 언급)이다. frontmatter에 명시하면 자동 검증이 가능해진다.

### 2.4 스킬 참조 무결성

**parse-xml/SKILL.md 라인 53**: "assets/parsed-template.json 형식 참조"라고 기술하는데, 실제 파일 `.kiro/skills/parse-xml/assets/parsed-template.json`이 존재한다 -- **정상**.

**extract-sql/SKILL.md 라인 32**: `tools/mybatis-sql-extractor/build/libs/mybatis-sql-extractor-1.0.0.jar`를 참조하는데, `tools/mybatis-sql-extractor/` 디렉토리는 존재하지만 빌드 산출물(build/libs/)은 없다. 이는 정상이다 (사용자가 빌드해야 하므로).

---

## 3. Steering inclusion 모드

### 3.1 현재 상태

| 파일 | inclusion | 비고 |
|------|-----------|------|
| `oracle-pg-rules.md` | `always` | 변환 룰 -- 항상 필요 |
| `edge-cases.md` | `always` | 에지케이스 -- 항상 필요 |
| `product.md` | `always` | 제품 개요 -- 항상 필요 |
| `db-config.md` | `manual` | DB 접속 설정 -- 필요 시 참조 |
| `tech.md` | `always` | 기술 스택 -- 항상 필요 |

### 3.2 `fileMatch` 모드 활용 가능 영역

#### 권장-1: `oracle-pg-rules.md` -> `fileMatch`

```yaml
---
inclusion: fileMatch
fileMatchPattern: ["workspace/input/**/*.xml", "workspace/results/**/*.json", "workspace/output/**/*.xml"]
---
```

**근거:** 변환 룰은 XML 파일이나 변환 결과를 다룰 때만 필요하다. 일반적인 프로젝트 설정 대화에서는 불필요하게 컨텍스트를 소비한다. 다만, 이 프로젝트의 에이전트가 **거의 항상** XML 변환 작업을 수행하므로 `always`도 합리적이다. 파일이 커지면(룰 100+개) `fileMatch`로 전환하는 것이 좋다.

#### 권장-2: `edge-cases.md` -> `auto` 또는 `fileMatch`

```yaml
---
inclusion: auto
name: edge-cases
description: Oracle에서 PostgreSQL로 변환 시 발견된 에지케이스 패턴. 변환 실패, LLM 변환, 복잡한 패턴에 대한 선례를 포함한다.
---
```

**근거:** `auto` 모드를 사용하면 Kiro가 대화의 맥락에서 에지케이스가 관련 있을 때만 자동으로 포함한다. 현재 `always`이면 빈 문서(초기 상태)도 매번 로드된다.

#### 권장-3: `tech.md` -> `auto`

```yaml
---
inclusion: auto
name: tech-stack
description: 에이전트 구성, 모델 선택, DB 연결 방법, 디렉토리 규약 등 기술 스택과 인프라 관련 정보.
---
```

**근거:** 기술 스택 정보는 초기 설정이나 디버깅 시에만 필요하다. 일상적 변환 작업에서는 불필요하다.

### 3.3 컨텍스트 비용 분석

현재 `always` 3개 파일의 추정 토큰 크기:

| 파일 | 추정 크기 | always 필요성 |
|------|----------|-------------|
| `oracle-pg-rules.md` | ~3,000 토큰 | 높음 (거의 매번 사용) |
| `edge-cases.md` | ~200 토큰 (초기) -> 수천 (축적 후) | 중간 |
| `product.md` | ~300 토큰 | 높음 (전체 흐름 이해에 필수) |
| `tech.md` | ~400 토큰 | 낮음 (설정 시에만) |

초기에는 총 ~4,000 토큰으로 부담이 적지만, `edge-cases.md`가 축적되면 수천~수만 토큰으로 증가할 수 있다. **edge-cases.md는 축적형 문서이므로 `auto` 전환을 강력히 권장한다.**

---

## 4. Hook 설계

### 4.1 전체 평가: **양호 (개선 가능)**

### 4.2 Hook Event 이름 검증

| 이벤트 | 사용 위치 | Kiro 스펙 준수 |
|--------|----------|-------------|
| `agentSpawn` | leader.json:43 | Kiro 문서에서 "agent turn" 관련 이벤트 확인됨. Kiro IDE에서는 UI 기반 hook 설정을 사용하므로 JSON 방식은 CLI 전용일 수 있음. 이벤트명 자체는 합리적. |
| `userPromptSubmit` | leader.json:48 | Kiro 문서에 "User prompt submission" 이벤트 언급됨. 정상. |
| `preToolUse` | leader.json:53, validator.json:45, reviewer.json:41 | Kiro 문서에 "Before tool invocations" 언급됨. 정상. |
| `postToolUse` | leader.json:59, validator.json:51 | Kiro 문서에 "After tool invocations" 언급됨. 정상. |
| `stop` | leader.json:64, learner.json:44 | Kiro 문서에 "agent turn completion" 언급됨. 정상. |

**결론:** 5개 이벤트명 모두 Kiro의 문서화된 hook 이벤트와 일치한다.

### 4.3 Matcher 패턴 검증

| 파일 | matcher | 매칭 대상 | 판단 |
|------|---------|----------|------|
| leader.json:55 | `"subagent"` | subagent 도구 호출 | 정상 (tools에 `"subagent"` 있음) |
| validator.json:47 | `"execute_bash"` | shell 도구 실행 | **잠재적 불일치** (ISSUE-2 참조) |
| reviewer.json:42 | `"execute_bash"` | shell 도구 실행 | **잠재적 불일치** (ISSUE-2 참조) |

### 4.4 Hook Command 검토

#### ISSUE-5: postToolUse hook에 하드코딩된 시간

**파일:** `oracle-pg-leader.json` 라인 61
```json
"command": "echo \"[08:50:37] Subagent completed.\""
```

**문제:** `08:50:37`이 하드코딩되어 있다. 이것은 개발/테스트 중 남은 흔적으로 보인다. `$(date +%H:%M:%S)`로 교체해야 한다.

**위험도:** 낮음 (기능에 영향 없으나 로그 혼란 유발).

#### ISSUE-6: userPromptSubmit hook의 복잡한 인라인 Python

**파일:** `oracle-pg-leader.json` 라인 48-50

인라인 Python 스크립트가 JSON 문자열 안에 이스케이프되어 있어 가독성이 매우 낮다. hook command는 단순한 셸 명령어가 적합하며, 복잡한 로직은 외부 스크립트로 분리하는 것이 좋다.

**권장:**
```json
{
  "command": "python3 tools/hooks/show-progress.py 2>/dev/null || echo '[상태] 아직 시작 전'"
}
```

#### ISSUE-7: agentSpawn hook에서 XML 카운트 방식

**파일:** `oracle-pg-leader.json` 라인 44

```bash
XML_COUNT=$(ls workspace/input/*.xml 2>/dev/null | wc -l)
```

`ls`의 출력을 파이프로 `wc -l`에 전달하는 방식은 파일명에 줄바꿈이 포함된 경우 오작동할 수 있다 (극단적 케이스).

**권장:** `find workspace/input -name '*.xml' -maxdepth 1 2>/dev/null | wc -l` 또는 글로브 카운트 사용.

### 4.5 누락된 Hook

#### 권장-4: converter에 preToolUse Destructive SQL Guard 추가

현재 `validator.json`과 `reviewer.json`에는 `execute_bash` matcher로 destructive SQL guard가 있지만, **converter.json에는 없다**. converter는 `write` 도구만 사용하므로 shell을 직접 실행하지 않아 현재는 문제 없다. 그러나 향후 converter에 shell 도구가 추가될 경우를 대비해 방어적으로 추가하는 것이 좋다.

---

## 5. Subagent 설정

### 5.1 현재 설정 (oracle-pg-leader.json)

```json
"availableAgents": ["converter", "test-generator", "validator", "reviewer", "learner"],
"trustedAgents": ["converter", "test-generator", "validator"]
```

### 5.2 분석

| 에이전트 | available | trusted | 판단 |
|---------|-----------|---------|------|
| converter | O | O | **적절.** 변환은 자동 실행 필요. |
| test-generator | O | O | **적절.** Oracle 딕셔너리 조회는 읽기 전용. |
| validator | O | O | **적절.** 검증은 읽기 전용 + ROLLBACK. |
| reviewer | O | X | **적절.** 실패 분석은 수정안을 생성하므로 사용자 확인이 유용. |
| learner | O | X | **매우 적절.** steering 파일 수정 + git commit + PR 생성은 반드시 사용자 확인 필요. |

### 5.3 보안/편의 균형 평가: **우수**

- reviewer를 untrusted로 둔 것은 좋은 판단이다. 수정안이 잘못될 경우 사용자가 개입할 수 있다.
- learner를 untrusted로 둔 것은 **핵심적으로 올바르다**. steering 파일 변경과 git 작업은 반드시 사람이 확인해야 한다.
- converter를 trusted로 둔 것은 대량 파일 처리 시 효율에 필수적이다.

### 5.4 개선 권장

#### 권장-5: reviewer를 trusted로 전환 고려

**근거:** Phase 4 셀프 힐링 루프에서 `Reviewer -> Converter -> Validator`가 최대 3회 자동 반복된다. reviewer가 untrusted이면 매 반복마다 사용자 확인이 필요하여 자동화가 끊긴다.

**대안:** reviewer를 trusted로 전환하되, `max_attempts: 3` 제한은 프롬프트에서 유지한다. 또는 Phase 4 진입 시 사용자에게 "3회 자동 재시도를 허용하시겠습니까?" 확인 후 진행하는 방식도 가능하다.

---

## 6. Resource 경로

### 6.1 경로 프로토콜 검증

| 에이전트 | 경로 | 프로토콜 | 파일 존재 | 판단 |
|---------|------|---------|----------|------|
| leader | `file://.kiro/steering/**/*.md` | file:// | O (5개 파일) | 정상 |
| leader | `skill://.kiro/skills/**/SKILL.md` | skill:// | O (17개 파일) | 정상 |
| leader | `skill://.kiro/skills/audit-log/SKILL.md` | skill:// | O | **중복** (ISSUE-4) |
| leader | `skill://.kiro/skills/query-analyzer/SKILL.md` | skill:// | O | **중복** (ISSUE-4) |
| converter | `file://.kiro/steering/oracle-pg-rules.md` | file:// | O | 정상 |
| converter | `file://.kiro/steering/edge-cases.md` | file:// | O | 정상 |
| converter | `skill://.kiro/skills/rule-convert/SKILL.md` | skill:// | O | 정상 |
| converter | `skill://.kiro/skills/llm-convert/SKILL.md` | skill:// | O | 정상 |
| converter | `file://.kiro/skills/parse-xml/references/mybatis-ibatis-tag-reference.md` | file:// | O | 정상 |
| converter | `skill://.kiro/skills/audit-log/SKILL.md` | skill:// | O | 정상 |
| test-gen | `file://.kiro/steering/oracle-pg-rules.md` | file:// | O | 정상 |
| test-gen | `skill://.kiro/skills/generate-test-cases/SKILL.md` | skill:// | O | 정상 |
| test-gen | `skill://.kiro/skills/db-oracle/SKILL.md` | skill:// | O | 정상 |
| test-gen | `skill://.kiro/skills/audit-log/SKILL.md` | skill:// | O | 정상 |
| validator | `file://.kiro/steering/oracle-pg-rules.md` | file:// | O | 정상 |
| validator | `file://.kiro/steering/edge-cases.md` | file:// | O | 정상 |
| validator | `skill://.kiro/skills/explain-test/SKILL.md` | skill:// | O | 정상 |
| validator | `skill://.kiro/skills/execute-test/SKILL.md` | skill:// | O | 정상 |
| validator | `skill://.kiro/skills/compare-test/SKILL.md` | skill:// | O | 정상 |
| validator | `skill://.kiro/skills/db-oracle/SKILL.md` | skill:// | O | 정상 |
| validator | `skill://.kiro/skills/db-postgresql/SKILL.md` | skill:// | O | 정상 |
| validator | `skill://.kiro/skills/audit-log/SKILL.md` | skill:// | O | 정상 |
| reviewer | `file://.kiro/steering/oracle-pg-rules.md` | file:// | O | 정상 |
| reviewer | `file://.kiro/steering/edge-cases.md` | file:// | O | 정상 |
| reviewer | `skill://.kiro/skills/db-postgresql/SKILL.md` | skill:// | O | 정상 |
| reviewer | `skill://.kiro/skills/audit-log/SKILL.md` | skill:// | O | 정상 |
| learner | `file://.kiro/steering/oracle-pg-rules.md` | file:// | O | 정상 |
| learner | `file://.kiro/steering/edge-cases.md` | file:// | O | 정상 |
| learner | `skill://.kiro/skills/audit-log/SKILL.md` | skill:// | O | 정상 |

### 6.2 결론

- **존재하지 않는 파일을 참조하는 경우는 없다.** 모든 resource 경로가 실제 파일로 해석된다.
- ISSUE-4의 중복 참조 외에는 문제 없다.

### 6.3 누락 가능성이 있는 resource

| 에이전트 | 누락 후보 | 근거 |
|---------|----------|------|
| converter | `skill://.kiro/skills/param-type-convert/SKILL.md` | converter 프롬프트에서 "param-type-convert 스킬 참조"라고 명시하지만 resources에 없다 |
| converter | `skill://.kiro/skills/complex-query-decomposer/SKILL.md` | L3-L4 쿼리 변환 시 transform-plan 참조하지만 resources에 없다 |
| leader | `skill://.kiro/skills/cross-file-analyzer/SKILL.md` | 프롬프트에서 "cross-file-analyzer 스킬 실행"이라고 명시, 글로브로 포함되지만 명시적 참조가 더 명확 |

#### ISSUE-8: converter의 param-type-convert 스킬 누락

**파일:** `converter.json` 라인 14-21 (resources 배열)

converter 프롬프트 (`converter.md` 라인 132-141)에서 "파라미터 타입 변환 - param-type-convert 스킬 참조"를 명시하지만, converter의 resources에 이 스킬이 포함되어 있지 않다. 에이전트가 스킬의 상세 지침에 접근하지 못하면 타입 매핑을 정확하게 수행하지 못할 수 있다.

**권장:** converter.json의 resources에 `"skill://.kiro/skills/param-type-convert/SKILL.md"` 추가.

---

## 7. tools/allowedTools 설정

### 7.1 최소 권한 원칙 분석

| 에이전트 | tools (전체) | allowedTools (자동) | 확인 필요 도구 | 판단 |
|---------|-------------|-------------------|--------------|------|
| leader | read, write, glob, grep, subagent | read, glob, grep | write, subagent | **적절.** write(progress.json)와 subagent는 사용자 확인 적절. |
| converter | read, write | read, write | - | **주의.** write가 자동 허용되어 output XML을 자유롭게 수정 가능. 대량 처리 시 필요하므로 합리적이나, 실수 시 원본 덮어쓰기 위험. |
| test-gen | read, write, shell | read, write | shell | **적절.** shell(sqlplus)은 사용자 확인 적절. |
| validator | read, write, shell | read | write, shell | **우수.** write와 shell 모두 사용자 확인. |
| reviewer | read, write, shell | read, write | shell | **적절.** shell(psql)은 사용자 확인 적절. |
| learner | read, write, grep, glob, shell | read, grep, glob | write, shell | **우수.** steering 파일 수정(write)과 git/gh(shell) 모두 사용자 확인 필요. |

### 7.2 개선 권장

#### 권장-6: converter의 write 제한 고려

converter의 `allowedTools`에서 `write`가 자동 허용되어 있다. trusted agent이면서 write 자동이면, 이론적으로 프로젝트 내 어떤 파일이든 수정 가능하다.

**대안:** Kiro의 향후 기능으로 `writableDirectories` 같은 제한이 가능해지면 `workspace/output/`, `workspace/results/`만 허용하는 것이 안전하다.

#### 권장-7: leader에 `shell` 도구 추가 검토

leader의 프롬프트(Phase 0)에서 `which sqlplus`, `which psql`, 환경변수 확인 등 셸 명령을 직접 실행하도록 기술되어 있다. 그러나 leader의 tools에 `shell`이 없다. 이는 **프롬프트와 도구 설정의 불일치**이다.

두 가지 해석 가능:
1. Phase 0의 셸 명령은 `agentSpawn` hook에서 실행된다 (실제로 hook에 유사 명령이 있음).
2. 프롬프트의 셸 명령은 에이전트가 직접 실행하도록 의도되었으나 도구가 빠져있다.

**권장:** 해석 1이 의도라면 프롬프트에서 "hook이 자동 실행한 결과를 확인한다"로 수정. 해석 2라면 tools에 shell 추가 + allowedTools에서 제외 (사용자 확인 필요).

---

## 8. settings/cli.json

### 8.1 현재 설정

```json
{
  "chat.defaultAgent": "oracle-pg-leader",
  "chat.defaultModel": "claude-opus-4.6",
  "chat.greeting.enabled": true,
  "chat.enableTodoList": true,
  "chat.enableDelegate": true
}
```

### 8.2 분석

| 설정 | 값 | 판단 |
|------|---|------|
| `chat.defaultAgent` | `oracle-pg-leader` | **정상.** `.kiro/agents/oracle-pg-leader.json`과 일치. |
| `chat.defaultModel` | `claude-opus-4.6` | **정상.** leader의 model과 일치. |
| `chat.greeting.enabled` | `true` | **정상.** welcomeMessage 활용. |
| `chat.enableTodoList` | `true` | **정상.** 대규모 파이프라인에서 진행 추적에 유용. |
| `chat.enableDelegate` | `true` | **정상.** subagent 위임 활성화. |

### 8.3 추가 설정 권장

#### 권장-8: `chat.enableTangent` 추가

```json
"chat.enableTangent": true
```

**근거:** Kiro의 tangent mode는 현재 작업 흐름에서 벗어나 별도 탐색을 수행할 수 있게 한다. 에스컬레이션 건의 수동 디버깅이나 특정 쿼리 분석 시 유용하다.

#### 권장-9: `chat.maxTokens` 또는 `chat.contextWindow` 설정

1M context window를 사용하는 opus 모델이지만, 대량 XML 처리 시 컨텍스트 관리가 중요하다. 명시적 설정이 있으면 예측 가능한 동작을 보장한다.

---

## 9. welcomeMessage

### 9.1 현재 상태

`oracle-pg-leader.json`의 welcomeMessage는 약 2,200자의 상세한 가이드를 포함한다.

### 9.2 렌더링 검증

#### ISSUE-9: JSON 문자열 내 `\n` 줄바꿈 렌더링

JSON에서 `\n`은 유효한 줄바꿈 이스케이프이다. Kiro CLI가 이를 실제 줄바꿈으로 렌더링하는지는 구현에 따라 다르다.

**확인 사항:**
- `\n\n[전체 흐름]\n\n` -- 이중 줄바꿈이 빈 줄로 표시되는지
- ASCII art 형태의 흐름도(`│`, `├──`, `└──`)가 모노스페이스로 정렬되는지
- `[셀프 힐링 상세]`, `[학습 루프]`, `[사용법]` 같은 구분이 시각적으로 명확한지

**잠재적 문제:**
1. 터미널 너비에 따라 흐름도가 깨질 수 있다.
2. `│`, `├`, `└` 유니코드 문자가 일부 터미널에서 깨질 수 있다.

#### 권장-10: welcomeMessage 간소화

현재 welcomeMessage는 전체 파이프라인 흐름도를 포함하여 매우 길다 (약 80줄). 사용자가 처음 보는 화면에서 이 정보가 모두 필요한지 의문이다.

**권장 구조:**
```
Oracle -> PostgreSQL Migration Agent 준비 완료.

workspace/input/에 XML 파일을 배치하고 '변환해줘'로 시작하세요.

사용 가능한 명령:
- '변환해줘' -- 전체 자동 수행 (Phase 0~6)
- 'X파일만 변환해줘' -- 특정 파일만 처리
- '현재 진행 상황' -- 현황 확인
- 'Phase 1~2만 해줘' -- DB 없이 파싱+변환만

상세 흐름은 'Phase 설명해줘'로 확인하세요.
```

장문 설명은 steering이나 별도 스킬로 이동하면 첫 인상이 깔끔해진다.

---

## 10. 개선 가능점

### 10.1 Kiro 최신 기능 활용

#### A. Knowledge Base 활용

**현재:** steering 파일 + 스킬 내 references/ 디렉토리에 패턴 문서를 두고 있다.

**개선:** Kiro의 knowledge base 기능이 있다면, `connect-by-patterns.md`, `merge-into-patterns.md`, `plsql-patterns.md`, `rownum-pagination-patterns.md`, `mybatis-ibatis-tag-reference.md`, `oracle-dictionary-queries.md`, `jdbc-type-mapping.md`, `rule-catalog.md` 등 참조 문서를 knowledge base에 등록하면:
- 에이전트가 RAG 기반으로 관련 패턴을 자동 검색
- 현재의 정적 `resources` 배열 대신 동적 참조 가능
- 패턴 문서 추가/수정이 에이전트 JSON 수정 없이 반영

#### B. Delegate Mode 최적화

**현재:** `chat.enableDelegate: true`로 설정되어 있으나, 실제 delegate 동작 방식이 프롬프트에 명시되어 있지 않다.

**개선:** leader 프롬프트에 delegate mode 지침 추가:
```markdown
## Delegate Mode 활용
- Phase 2에서 같은 레이어의 쿼리들을 병렬로 converter에 delegate
- Phase 3에서 검증을 병렬로 validator에 delegate
- delegate 결과를 취합하여 progress.json 갱신
```

#### C. `#[[file:...]]` 라이브 파일 참조

Kiro steering에서 `#[[file:<path>]]` 문법으로 워크스페이스 파일을 라이브 참조할 수 있다.

**활용 가능:**
- `product.md`에서 `#[[file:workspace/progress.json]]`으로 현재 진행 상황을 실시간 참조
- `edge-cases.md`에서 `#[[file:.kiro/steering/oracle-pg-rules.md]]`로 룰셋 크로스 참조

### 10.2 구조적 개선

#### D. 스키마 참조를 리소스에 명시

현재 `.kiro/schemas/` 디렉토리에 10개 JSON 스키마가 있지만, 어떤 에이전트의 resources에도 스키마가 포함되어 있지 않다.

**권장:**
```json
// converter.json resources에 추가
"file://.kiro/schemas/parsed.schema.json",
"file://.kiro/schemas/converted.schema.json"

// validator.json resources에 추가
"file://.kiro/schemas/validated.schema.json",
"file://.kiro/schemas/test-cases.schema.json"
```

**근거:** 에이전트가 스키마를 참조하면 출력 JSON의 정확성이 높아진다. 프롬프트에서 "형식 참조"라고만 하는 것보다 실제 스키마를 로드하는 것이 효과적이다.

#### E. extract-sql 스킬을 leader의 리소스에 추가

**현재:** extract-sql 스킬이 존재하지만 어떤 에이전트의 resources에도 없다.

**분석:** extract-sql은 Java 기반 도구로, `tools/mybatis-sql-extractor/` 빌드가 필요하다. Phase 1에서 parse-xml 대신 또는 병행하여 사용할 수 있다고 스킬 문서에 기술되어 있다.

**권장:** leader의 resources에 추가하되, Java 런타임이 없는 환경에서는 폴백하도록 Phase 0에 Java 체크를 추가한다.

#### F. Steering AGENTS.md 활용

Kiro 문서에 따르면 `AGENTS.md` 파일은 항상 포함(inclusion mode 없이)된다. 프로젝트 루트나 `.kiro/steering/`에 `AGENTS.md`를 두면 모든 에이전트가 자동으로 참조한다.

**활용:** 현재 `product.md`의 내용을 `AGENTS.md`로 이동하면 inclusion 설정 없이 항상 로드되어 더 간결해진다.

### 10.3 보안 강화

#### G. 환경변수 유출 방지

**현재 위험:** `db-oracle` 스킬의 sqlplus 명령어:
```bash
sqlplus -S ${ORACLE_USER}/${ORACLE_PASSWORD}@${ORACLE_HOST}:${ORACLE_PORT}/${ORACLE_SID}
```

이 명령은 프로세스 목록(`ps aux`)에 비밀번호가 노출된다.

**권장:** Oracle connection string file이나 wallet 사용:
```bash
sqlplus -S /@CONN_ALIAS
```
또는 최소한 환경변수를 파일로 전달:
```bash
echo "${ORACLE_PASSWORD}" | sqlplus -S -L ${ORACLE_USER}@... 
```

#### H. Hook의 KIRO_TOOL_INPUT 환경변수

**파일:** `validator.json` 라인 47, `reviewer.json` 라인 42

```bash
printf '%s' "$KIRO_TOOL_INPUT" | python3 -c "..."
```

`$KIRO_TOOL_INPUT`이 Kiro가 hook에 전달하는 공식 환경변수인지 확인이 필요하다. Kiro 문서에서 hook에 사용 가능한 환경변수 목록이 명확하지 않다.

**위험:** 이 변수가 비어있거나 존재하지 않으면 Destructive SQL Guard가 우회된다.

**권장:** 방어적 코딩 추가:
```bash
[ -z \"$KIRO_TOOL_INPUT\" ] && exit 0;
```

---

## 요약: 이슈 및 권장사항 우선순위

### Critical (즉시 확인 필요)

| ID | 내용 | 파일 |
|----|------|------|
| ISSUE-2 | `shell` vs `execute_bash` matcher 불일치 가능성 (보안 guard 비활성화 위험) | validator.json:47, reviewer.json:42 |
| ISSUE-8 | converter의 param-type-convert 스킬 resource 누락 | converter.json:14-21 |

### High (개선 권장)

| ID | 내용 | 파일 |
|----|------|------|
| ISSUE-3 | prompt 경로의 상대 참조 (`../`) -- 루트 기준 절대 경로로 통일 | 모든 agent JSON |
| ISSUE-5 | postToolUse hook에 하드코딩된 시간 `08:50:37` | leader.json:61 |
| 권장-5 | reviewer를 trusted로 전환하여 셀프 힐링 루프 자동화 보장 | leader.json:29 |
| 권장-7 | leader 프롬프트의 Phase 0 셸 명령과 도구 설정 불일치 해소 | leader.json, converter.md |
| 권장 D | 스키마 파일을 관련 에이전트 resources에 추가 | converter.json, validator.json |

### Medium (개선 시 효과 있음)

| ID | 내용 |
|----|------|
| ISSUE-1 | model 식별자 런타임 호환성 확인 |
| ISSUE-4 | leader resources 중복 제거 |
| ISSUE-6 | userPromptSubmit hook 인라인 Python 외부 스크립트 분리 |
| 권장-2 | edge-cases.md를 `auto` inclusion으로 전환 (축적형 문서) |
| 권장-3 | tech.md를 `auto` inclusion으로 전환 |
| 권장-10 | welcomeMessage 간소화 |
| 권장 A | Knowledge base 기반 패턴 문서 관리 |
| 권장 F | AGENTS.md 활용 |

### Low (향후 고려)

| ID | 내용 |
|----|------|
| ISSUE-7 | agentSpawn hook의 ls 기반 XML 카운트 개선 |
| 권장-1 | oracle-pg-rules.md fileMatch 전환 (파일 증가 시) |
| 권장-4 | converter에 방어적 preToolUse hook 추가 |
| 권장-6 | converter write 권한 디렉토리 제한 (Kiro 기능 지원 시) |
| 권장-8 | tangent mode 활성화 |
| 권장-9 | context window 명시적 설정 |
| 권장 B | Delegate mode 프롬프트 지침 추가 |
| 권장 C | #[[file:...]] 라이브 참조 활용 |
| 권장 E | extract-sql 스킬 resources 통합 |
| 권장 G | Oracle 비밀번호 프로세스 목록 노출 방지 |
| 권장 H | KIRO_TOOL_INPUT 환경변수 방어적 검증 |

---

## 종합 평가

| 항목 | 등급 | 코멘트 |
|------|------|--------|
| Agent JSON 구조 | B+ | 핵심 필드 완비. prompt 경로/resource 중복 등 마이너 이슈. |
| Skill 설계 | A | 17개 스킬 모두 YAML frontmatter 정상. 참조 문서 체계적. |
| Steering 활용 | B | always/manual 기본 구성 양호. auto/fileMatch 미활용. |
| Hook 설계 | B | 5개 이벤트 활용 양호. matcher 불일치 잠재 리스크. |
| Subagent 보안 | A | trusted/untrusted 분리 우수. learner untrusted 핵심 정확. |
| Resource 무결성 | A- | 전체 경로 유효. param-type-convert 누락 1건. |
| 도구 권한 | A- | 최소 권한 원칙 대체로 준수. 일부 개선 가능. |
| Settings | B+ | 기본 설정 정상. 추가 최적화 여지. |
| 전체 아키텍처 | A | 6-agent 오케스트레이션, 레이어별 변환, 셀프 힐링, 학습 루프 우수. |

**총평:** 전체적으로 높은 수준의 Kiro 에이전트 시스템이다. 멀티 에이전트 오케스트레이션, 보안 가드, 학습 루프 등 고급 패턴을 적절히 활용하고 있다. Critical 이슈 2건(matcher 불일치, resource 누락)을 우선 해결하고, High 권장사항을 순차적으로 적용하면 프로덕션 수준의 안정성을 확보할 수 있다.
