# Part 4: Integration + Verification

## Task 13: 통합 검증 + 최종 커밋

**Files:**
- Verify: `.kiro/agents/*.json` (5개)
- Verify: `.kiro/prompts/*.md` (5개)
- Verify: `.kiro/skills/*/SKILL.md` (8개)
- Verify: `.kiro/steering/*.md` (5개)
- Verify: `.gitignore`

- [ ] **Step 1: 전체 파일 구조 검증**

```bash
echo "=== Agents ===" && ls -la .kiro/agents/
echo "=== Prompts ===" && ls -la .kiro/prompts/
echo "=== Skills ===" && find .kiro/skills -name "SKILL.md" | sort
echo "=== Steering ===" && ls -la .kiro/steering/
echo "=== References ===" && find .kiro/skills -name "*.md" -not -name "SKILL.md" | sort
echo "=== Assets ===" && find .kiro/skills -name "*.json" | sort
```

Expected:
```
=== Agents ===
oracle-pg-leader.json
converter.json
validator.json
reviewer.json
learner.json

=== Prompts ===
oracle-pg-leader.md
converter.md
validator.md
reviewer.md
learner.md

=== Skills ===
.kiro/skills/compare-test/SKILL.md
.kiro/skills/execute-test/SKILL.md
.kiro/skills/explain-test/SKILL.md
.kiro/skills/learn-edge-case/SKILL.md
.kiro/skills/llm-convert/SKILL.md
.kiro/skills/parse-xml/SKILL.md
.kiro/skills/report/SKILL.md
.kiro/skills/rule-convert/SKILL.md

=== Steering ===
db-config.md
edge-cases.md
oracle-pg-rules.md
product.md
tech.md
```

- [ ] **Step 2: 모든 에이전트 JSON 유효성 검증**

```bash
for f in .kiro/agents/*.json; do
  echo -n "$f: "
  python3 -c "import json; json.load(open('$f')); print('OK')" 2>&1
done
```

Expected: 5개 모두 `OK`

- [ ] **Step 3: 에이전트 JSON 필수 필드 검증**

```bash
for f in .kiro/agents/*.json; do
  echo "--- $(basename $f) ---"
  python3 -c "
import json
with open('$f') as fh:
    d = json.load(fh)
    required = ['name', 'description', 'prompt', 'model', 'tools']
    for r in required:
        status = 'OK' if r in d else 'MISSING'
        print(f'  {r}: {status}')
    # prompt 파일 존재 확인
    prompt = d.get('prompt', '')
    if prompt.startswith('file://'):
        import os
        # file://../prompts/X.md → .kiro/prompts/X.md
        rel_path = prompt.replace('file://../', '.kiro/')
        exists = 'OK' if os.path.exists(rel_path) else 'NOT FOUND'
        print(f'  prompt_file ({rel_path}): {exists}')
"
done
```

Expected: 모든 필드 `OK`, 모든 프롬프트 파일 존재

- [ ] **Step 4: 스킬 SKILL.md frontmatter 검증**

```bash
for f in $(find .kiro/skills -name "SKILL.md"); do
  echo -n "$f: "
  python3 -c "
content = open('$f').read()
has_frontmatter = content.startswith('---')
if has_frontmatter:
    end = content.index('---', 3)
    fm = content[3:end]
    has_name = 'name:' in fm
    has_desc = 'description:' in fm
    if has_name and has_desc:
        print('OK')
    else:
        missing = []
        if not has_name: missing.append('name')
        if not has_desc: missing.append('description')
        print(f'MISSING: {missing}')
else:
    print('NO FRONTMATTER')
"
done
```

Expected: 8개 모두 `OK`

- [ ] **Step 5: steering frontmatter 검증**

```bash
for f in .kiro/steering/*.md; do
  echo -n "$(basename $f): "
  head -3 "$f" | grep -q "inclusion:" && echo "OK" || echo "MISSING inclusion"
done
```

Expected: 5개 모두 `OK`

- [ ] **Step 6: 에이전트 간 참조 무결성 검증**

```bash
python3 -c "
import json, os

# Leader의 availableAgents가 모두 실제 에이전트 파일로 존재하는지
leader = json.load(open('.kiro/agents/oracle-pg-leader.json'))
available = leader.get('toolsSettings', {}).get('subagent', {}).get('availableAgents', [])
print('Leader availableAgents:')
for agent in available:
    path = f'.kiro/agents/{agent}.json'
    exists = 'OK' if os.path.exists(path) else 'NOT FOUND'
    print(f'  {agent}: {exists}')

# 각 에이전트의 resources가 참조하는 steering/skill 파일 존재 여부
print()
for agent_file in sorted(os.listdir('.kiro/agents')):
    if not agent_file.endswith('.json'):
        continue
    agent = json.load(open(f'.kiro/agents/{agent_file}'))
    print(f'{agent_file} resources:')
    for res in agent.get('resources', []):
        if res.startswith('file://') and '**' not in res:
            path = res.replace('file://', '')
            exists = 'OK' if os.path.exists(path) else 'NOT FOUND'
            print(f'  {res}: {exists}')
        else:
            print(f'  {res}: (glob/skill pattern, skip)')
"
```

Expected: 모든 참조 `OK`

- [ ] **Step 7: Git 전체 상태 확인**

```bash
git status
git log --oneline
```

Expected:
- working tree clean
- 커밋 히스토리에 Task 1~12 커밋 존재

- [ ] **Step 8: 최종 태그 (선택)**

```bash
git tag v0.1.0 -m "Initial Kiro agent setup for Oracle→PostgreSQL migration"
```
