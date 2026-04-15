# OMA 이전 가이드: oma-claude-code → oma-migration/app-migration

이 문서는 `oma-claude-code` (독립 레포)의 최신 코드를 `oma-migration` 레포의 `app-migration/` 서브디렉토리로 이전하는 절차입니다.

## 사전 조건

- `oma-migration` 레포 clone 완료
- `oma-claude-code` 레포 최신 main pull 완료

## 디렉토리 매핑

```
oma-claude-code/              →  oma-migration/
├── CLAUDE.md                 →  app-migration/CLAUDE.md
├── README.md                 →  app-migration/README.md
├── .claude/                  →  .claude/                    ← git root!
│   ├── agents/*.md           →  .claude/agents/*.md
│   ├── rules/*.md            →  .claude/rules/*.md
│   ├── commands/*.md         →  .claude/commands/*.md
│   ├── skills/               →  .claude/skills/
│   └── settings.json         →  .claude/settings.json
├── tools/                    →  app-migration/tools/
├── schemas/                  →  app-migration/schemas/
├── scripts/                  →  app-migration/scripts/
├── docs/                     →  app-migration/docs/
├── pipeline/                 →  app-migration/pipeline/     ← .gitkeep만
└── workspace/                →  (생성 안 함 — 런타임에 생성)
```

### 핵심: `.claude/`는 git root에 위치

Claude Code는 **git root의 `.claude/`**를 읽습니다.
`app-migration/.claude/`가 아닌 `oma-migration/.claude/`에 넣어야 합니다.
기존 구버전 `.claude/` 파일들은 덮어씁니다.

## 이전 스크립트

```bash
#!/bin/bash
# oma-claude-code → oma-migration/app-migration 이전
# 실행 위치: oma-claude-code와 oma-migration이 같은 디렉토리에 있어야 함

set -e

SRC="oma-claude-code"
DST="oma-migration"
APP="$DST/app-migration"

echo "=== OMA 이전: $SRC → $DST ==="

# 1. 대상 디렉토리 확인
[ -d "$SRC" ] || { echo "ERROR: $SRC not found"; exit 1; }
[ -d "$DST" ] || { echo "ERROR: $DST not found"; exit 1; }

# 2. 구버전 정리
echo "구버전 정리..."
# .claude/ (git root) — 구버전 에이전트 삭제 (learner, reviewer, validator 등)
rm -f "$DST/.claude/agents/learner.md" \
      "$DST/.claude/agents/reviewer.md" \
      "$DST/.claude/agents/validator.md" \
      "$DST/.claude/agents/test-generator.md" \
      "$DST/.claude/agents/healer.md"
# app-migration/ 구버전 파일 삭제
rm -f "$APP/tools/generate-healing-tickets.py" \
      "$APP/tools/pre-report-check.py"
# 구버전 rules (app-migration/rules/ → .claude/rules/로 이동)
rm -rf "$APP/rules"

# 3. .claude/ 복사 (git root)
echo ".claude/ 복사..."
cp -r "$SRC/.claude/agents/"* "$DST/.claude/agents/"
cp -r "$SRC/.claude/rules/"* "$DST/.claude/rules/"
cp -r "$SRC/.claude/commands/"* "$DST/.claude/commands/"
cp -r "$SRC/.claude/skills/" "$DST/.claude/skills/"  2>/dev/null || true
cp "$SRC/.claude/settings.json" "$DST/.claude/settings.json"

# 4. app-migration/ 복사
echo "app-migration/ 복사..."
mkdir -p "$APP"

# CLAUDE.md, README.md
cp "$SRC/CLAUDE.md" "$APP/CLAUDE.md"
cp "$SRC/README.md" "$APP/README.md"

# tools/ (전체 덮어쓰기)
rm -rf "$APP/tools"
cp -r "$SRC/tools" "$APP/tools"
# __pycache__ 제거
find "$APP/tools" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# schemas/
rm -rf "$APP/schemas"
cp -r "$SRC/schemas" "$APP/schemas"

# scripts/
rm -rf "$APP/scripts"
cp -r "$SRC/scripts" "$APP/scripts" 2>/dev/null || true

# docs/
mkdir -p "$APP/docs"
cp -r "$SRC/docs/"* "$APP/docs/"

# pipeline/ (.gitkeep만)
rm -rf "$APP/pipeline"
cp -r "$SRC/pipeline" "$APP/pipeline"
# pipeline 내 실제 데이터 제거 (.gitkeep만 유지)
find "$APP/pipeline" -type f ! -name ".gitkeep" -delete 2>/dev/null || true

# 5. 경로 조정
echo "경로 조정..."

# CLAUDE.md 내부 경로: tools/ → app-migration/tools/
# 실행 시 cd app-migration/ 하고 실행하므로 상대경로 그대로 OK
# .claude/settings.json의 hooks: workspace/ → app-migration/workspace/
# → 실행 디렉토리가 app-migration/이면 그대로 OK

# 6. .env.example 복사 (있으면)
[ -f "$SRC/.env.example" ] && cp "$SRC/.env.example" "$APP/.env.example"
[ -f "$SRC/.env" ] && echo "WARNING: .env는 복사하지 않습니다. 수동으로 설정하세요."

# 7. .gitignore 확인
if ! grep -q "workspace/" "$DST/.gitignore" 2>/dev/null; then
  echo "" >> "$DST/.gitignore"
  echo "# OMA app-migration runtime" >> "$DST/.gitignore"
  echo "app-migration/workspace/" >> "$DST/.gitignore"
  echo "app-migration/pipeline/step-*/output/*" >> "$DST/.gitignore"
  echo "app-migration/pipeline/step-*/handoff.json" >> "$DST/.gitignore"
  echo "app-migration/pipeline/supervisor-state.json" >> "$DST/.gitignore"
  echo "*.pyc" >> "$DST/.gitignore"
  echo "__pycache__/" >> "$DST/.gitignore"
fi

echo ""
echo "=== 이전 완료 ==="
echo ""
echo "다음 단계:"
echo "  1. cd $DST"
echo "  2. app-migration/.env 설정 (Oracle/PG 접속 정보)"
echo "  3. cp /path/to/mybatis/*.xml app-migration/workspace/input/"
echo "  4. cd app-migration && claude"
echo "  5. '변환해줘' 입력"
```

## 이전 후 실행 방법

```bash
# 1. oma-migration 클론
git clone https://github.com/netsgo0319/oma-migration.git
cd oma-migration

# 2. 환경 설정
cp app-migration/.env.example app-migration/.env
vi app-migration/.env   # Oracle/PG 접속 정보 입력

# 3. 입력 XML 복사
mkdir -p app-migration/workspace/input
cp /path/to/mybatis/*.xml app-migration/workspace/input/

# 4. pipeline 심링크 설정
ln -sfn $(pwd)/app-migration/workspace/input app-migration/pipeline/shared/input

# 5. Claude Code 실행 (app-migration 디렉토리에서)
cd app-migration
claude
> 변환해줘
```

## 이전 후 확인 체크리스트

```bash
# .claude/ 에이전트 확인 (git root)
ls oma-migration/.claude/agents/
# → converter.md, tc-generator.md, validate-and-fix.md, reporter.md

# 구버전 에이전트 삭제 확인
ls oma-migration/.claude/agents/ | grep -E "learner|reviewer|validator|test-generator|healer"
# → 결과 없어야 함

# tools/ 확인
ls oma-migration/app-migration/tools/
# → assemble-workspace.sh, generate-handoff.py 등 신규 파일 존재

# schemas/ 확인
ls oma-migration/app-migration/schemas/handoff.schema.json
# → 존재

# pipeline/ 구조 확인
find oma-migration/app-migration/pipeline -name ".gitkeep" | wc -l
# → 11

# 설정 확인
cat oma-migration/.claude/settings.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('model','?'), d.get('env',{}).get('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS','?'))"
# → opus 1
```

## 주의사항

1. **`.claude/`는 git root에** — `app-migration/.claude/`가 아님
2. **`.env`는 복사 안 함** — 보안. 수동 설정 필수
3. **`workspace/`는 .gitignore** — 런타임 데이터
4. **`pipeline/` 데이터도 .gitignore** — handoff.json, output 등
5. **실행은 `cd app-migration && claude`** — 상대경로가 tools/, pipeline/ 등을 참조
6. **schema-migration/ 영향 없음** — app-migration/만 덮어쓰기
