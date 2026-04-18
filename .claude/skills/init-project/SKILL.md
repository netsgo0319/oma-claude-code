---
name: init-project
description: 마이그레이션 프로젝트 초기화. 프로젝트명, 고객사, DB 연결정보, S3 경로를 설정하고 .env와 migration-config.json을 생성합니다. Phase 1/2 시작 전 반드시 실행.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Init Project (/init-project)

마이그레이션 프로젝트를 초기화합니다. Phase 1/2 시작 전 **반드시 1회** 실행.

## 사용자에게 입력받을 정보

1. **프로젝트명** (필수): e.g., `daiso-2026Q2`
2. **고객사명** (선택): e.g., `다이소`
3. **고객 바인드변수 리스트 경로** (선택): e.g., `/path/to/bind-variable-samples/`

## 실행 절차

### 1. .env 확인/생성

```bash
if [ ! -f .env ]; then
  echo ".env 파일이 없습니다. .env.example에서 복사합니다."
  cp .env.example .env
  echo "★ .env를 열어 DB 연결정보와 AWS 설정을 입력하세요."
fi
```

.env가 이미 있으면 핵심 변수만 확인:
```bash
python3 -c "
from dotenv import load_dotenv; import os; load_dotenv()
required = ['ORACLE_HOST','ORACLE_USER','PG_HOST','PG_DATABASE']
missing = [k for k in required if not os.environ.get(k)]
if missing: print(f'⚠️ .env에 미설정: {missing}')
else: print('✅ .env 핵심 변수 OK')
"
```

### 2. migration-config.json 초기 생성

```bash
python3 -c "
import json, os
from datetime import datetime
config = {
    'project': {
        'name': '$PROJECT_NAME',
        'customer': '$CUSTOMER_NAME',
        's3_bucket': os.environ.get('DMS_SC_S3_BUCKET', 'oma-reports'),
        'bind_samples_dir': '$BIND_SAMPLES_DIR',
        'created_at': datetime.now().isoformat(),
    },
    'phase1': {'status': 'not_started'},
    'db': {
        'oracle': {
            'host': os.environ.get('ORACLE_HOST',''),
            'port': int(os.environ.get('ORACLE_PORT','1521')),
            'sid': os.environ.get('ORACLE_SID',''),
            'schema': os.environ.get('ORACLE_SCHEMA',''),
        },
        'pg': {
            'host': os.environ.get('PG_HOST',''),
            'port': int(os.environ.get('PG_PORT','5432')),
            'database': os.environ.get('PG_DATABASE',''),
            'schema': os.environ.get('PG_SCHEMA','public'),
        },
    },
}
with open('migration-config.json', 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print(f'✅ migration-config.json 생성: {config[\"project\"][\"name\"]}')
"
```

### 3. S3 경로 확인

```bash
S3_BUCKET=$(python3 -c "import json; print(json.load(open('migration-config.json'))['project']['s3_bucket'])")
PROJECT=$(python3 -c "import json; print(json.load(open('migration-config.json'))['project']['name'])")
echo "S3 경로: s3://$S3_BUCKET/$PROJECT/"
echo "  phase1-schema/{timestamp}/"
echo "  phase2-app/{timestamp}/"
aws s3 ls "s3://$S3_BUCKET/" 2>/dev/null && echo "✅ S3 접근 OK" || echo "⚠️ S3 접근 불가"
```

### 4. 고객 바인드변수 확인 (있으면)

```bash
BIND_DIR=$(python3 -c "import json; print(json.load(open('migration-config.json'))['project'].get('bind_samples_dir',''))")
if [ -n "$BIND_DIR" ] && [ -d "$BIND_DIR" ]; then
  echo "✅ 바인드변수: $(ls $BIND_DIR/*.json 2>/dev/null | wc -l) 파일"
fi
```

## 출력

- `migration-config.json` (루트)
- `.env` (없었으면 생성)
