---
name: phase-transition
description: Phase 1(스키마)→Phase 2(앱) 전환. Phase 1 결과 요약, migration-config 갱신, 컨텍스트 정리, Phase 2 시작 준비. /phase-transition으로 호출.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Phase Transition (/phase-transition)

Phase 1(스키마 마이그레이션) 완료 후 Phase 2(앱 마이그레이션) 시작을 위한 전환 절차.

**같은 세션이든 다른 세션이든 동작합니다.**

## 실행 절차

### 1. Phase 1 결과 확인

```bash
# migration_result.json (Phase 1이 자동 생성)
RESULT_FILE="schema-migration/migration_result.json"
if [ -f "$RESULT_FILE" ]; then
  python3 -c "
import json
r = json.load(open('$RESULT_FILE'))
print('=== Phase 1 결과 요약 ===')
print(f'Migration ID: {r.get(\"migration_id\",\"?\")}')
s = r.get('schema_migration', {})
print(f'스키마: {s.get(\"status\",\"?\")}')
d = r.get('data_migration', {})
if isinstance(d, dict):
    print(f'데이터: {d.get(\"tables_migrated\",\"?\")}/{d.get(\"tables_total\",\"?\")} tables')
v = r.get('data_verification', {})
if isinstance(v, dict):
    print(f'검증: {v.get(\"status\",\"?\")}')
print(f'소요: {r.get(\"total_duration_seconds\",\"?\")}초')
"
else
  echo "⚠️ migration_result.json 없음 — Phase 1 미완료이거나 다른 경로"
fi
```

### 2. migration-config.json 갱신

```bash
python3 -c "
import json, os
from datetime import datetime

config = json.load(open('migration-config.json'))

# Phase 1 결과 반영
result_file = 'schema-migration/migration_result.json'
if os.path.exists(result_file):
    r = json.load(open(result_file))
    config['phase1'] = {
        'status': 'completed' if r.get('schema_migration',{}).get('status') != 'FAILED' else 'failed',
        'completed_at': datetime.now().isoformat(),
        'migration_id': r.get('migration_id', ''),
        'schema_migration': r.get('schema_migration', {}),
        'data_migration': r.get('data_migration', {}),
        'data_verification': r.get('data_verification', {}),
        'total_duration_seconds': r.get('total_duration_seconds', 0),
    }
else:
    config['phase1']['status'] = 'unknown'

with open('migration-config.json', 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print(f'✅ migration-config.json 갱신 (Phase 1: {config[\"phase1\"][\"status\"]})')
"
```

### 3. Phase 1 결과 S3 업로드

```bash
PROJECT=$(python3 -c "import json; print(json.load(open('migration-config.json'))['project']['name'])")
BUCKET=$(python3 -c "import json; print(json.load(open('migration-config.json'))['project']['s3_bucket'])")
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
S3_PREFIX="s3://$BUCKET/$PROJECT/phase1-schema/$TIMESTAMP"

# Phase 1 보고서 + 결과 업로드
for f in schema-migration/migration_result.json schema-migration/workspace/reports/*.html migration-config.json; do
  [ -f "$f" ] && aws s3 cp "$f" "$S3_PREFIX/$(basename $f)" 2>/dev/null && echo "  ↑ $f"
done
echo "S3: $S3_PREFIX"
```

### 4. 컨텍스트 정리 (★ 중요)

**같은 세션에서 계속하는 경우:**
Phase 1의 수 시간 대화가 컨텍스트에 남아있어 Phase 2에 방해됩니다.

```
★ 아래 내용만 기억하면 됩니다:
1. migration-config.json에 Phase 1 결과가 저장됨
2. .env에 DB 연결정보가 있음
3. cd app-migration/ 후 /preflight 실행
4. /convert 또는 "변환해줘"로 Phase 2 시작

나머지 Phase 1 대화는 잊어도 됩니다.
```

**다른 세션에서 시작하는 경우:**
그냥 `cd app-migration/ && /preflight` 실행.
migration-config.json이 있으면 자동으로 Phase 1 결과를 읽습니다.

### 5. Phase 2 시작 안내

```
=== Phase 2: 앱 마이그레이션 준비 완료 ===

다음 명령으로 시작:
  cd app-migration/
  /preflight          (PG 스키마 검증 + 환경 체크)
  /convert            (전체 파이프라인 실행)
  또는 "변환해줘"
```
