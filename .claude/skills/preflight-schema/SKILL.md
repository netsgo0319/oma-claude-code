---
name: preflight-schema
description: Phase 1(스키마 마이그레이션) 사전 환경 점검. Python 3.11+, Strands SDK, DynamoDB, S3, DMS, DB 연결을 확인합니다. /preflight-schema로 호출.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Preflight Schema (/preflight-schema)

Phase 1(스키마 마이그레이션) 실행 전 환경 점검.

## 체크리스트

### 1. 프로젝트 초기화 확인
```bash
if [ ! -f migration-config.json ]; then
  echo "❌ migration-config.json 없음. /init-project 먼저 실행하세요."
  exit 1
fi
echo "✅ 프로젝트: $(python3 -c 'import json; print(json.load(open(\"migration-config.json\"))[\"project\"][\"name\"])')"
```

### 2. Python 3.11+ 확인
```bash
python3.11 --version 2>/dev/null || python3 --version
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [ "$(echo "$PYVER >= 3.11" | bc)" -eq 1 ] 2>/dev/null; then
  echo "✅ Python $PYVER"
else
  echo "⚠️ Python $PYVER — 3.11+ 권장 (Strands SDK 호환)"
fi
```

### 3. Python 패키지 설치
```bash
cd schema-migration/
pip install -r requirements.txt --quiet 2>&1 | tail -3
python3 -c "import strands; print(f'✅ strands-agents {strands.__version__}')" 2>/dev/null || echo "❌ strands-agents 미설치"
python3 -c "import oracledb; print('✅ oracledb')" 2>/dev/null || echo "❌ oracledb 미설치"
python3 -c "import asyncpg; print('✅ asyncpg')" 2>/dev/null || echo "❌ asyncpg 미설치"
python3 -c "import boto3; print('✅ boto3')" 2>/dev/null || echo "❌ boto3 미설치"
cd ..
```

### 4. .env 로드 + DB 연결 테스트
```bash
source .env 2>/dev/null

# Oracle
python3 -c "
import oracledb, os
dsn = f\"{os.environ['ORACLE_HOST']}:{os.environ.get('ORACLE_PORT','1521')}/{os.environ['ORACLE_SID']}\"
conn = oracledb.connect(user=os.environ['ORACLE_USER'], password=os.environ['ORACLE_PASSWORD'], dsn=dsn)
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM user_tables')
print(f'✅ Oracle 연결 OK — {cur.fetchone()[0]} tables')
conn.close()
" 2>&1 || echo "❌ Oracle 연결 실패"

# PostgreSQL
PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p ${PG_PORT:-5432} -U $PG_USER -d $PG_DATABASE \
  -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${PG_SCHEMA:-public}'" 2>&1 | head -3 \
  && echo "✅ PG 연결 OK" || echo "❌ PG 연결 실패"
```

### 5. AWS 리소스 확인
```bash
# DynamoDB
aws dynamodb describe-table --table-name oma-migration-state --query 'Table.TableStatus' --output text 2>&1 \
  && echo "✅ DynamoDB: oma-migration-state" || echo "❌ DynamoDB 테이블 없음 — 생성 필요"

aws dynamodb describe-table --table-name oma-pattern-memory --query 'Table.TableStatus' --output text 2>&1 \
  && echo "✅ DynamoDB: oma-pattern-memory" || echo "⚠️ oma-pattern-memory 없음 (RAG 선택적)"

# S3
S3_BUCKET=$(python3 -c "import json; print(json.load(open('migration-config.json'))['project']['s3_bucket'])")
aws s3 ls "s3://$S3_BUCKET/" 2>/dev/null && echo "✅ S3: $S3_BUCKET" || echo "❌ S3 접근 불가"

# DMS (선택)
DMS_ARN=${DMS_MIGRATION_PROJECT_ARN:-}
if [ -n "$DMS_ARN" ]; then
  aws dms describe-migration-projects --filters Name=migration-project-arn,Values=$DMS_ARN 2>/dev/null \
    && echo "✅ DMS Migration Project" || echo "⚠️ DMS 접근 불가"
fi

# Bedrock
aws bedrock list-foundation-models --query 'modelSummaries[?contains(modelId,`claude-opus`)].modelId' --output text 2>/dev/null | head -1 \
  && echo "✅ Bedrock Claude 접근 OK" || echo "❌ Bedrock 접근 불가"
```

### 6. 결과 요약
```
Preflight Schema 체크리스트:
- [ ] migration-config.json 존재
- [ ] Python 3.11+ 설치
- [ ] Strands SDK + DB 드라이버 설치
- [ ] Oracle 연결 OK
- [ ] PostgreSQL 연결 OK
- [ ] DynamoDB 테이블 존재
- [ ] S3 버킷 접근 OK
- [ ] Bedrock 접근 OK
```

## 다음 단계

모든 체크 통과 시:
```bash
cd schema-migration/
python3 scripts/run_migration.py
```
