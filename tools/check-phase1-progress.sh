#!/usr/bin/env bash
# Phase 1 (Schema Migration) 진행 상태 체크.
# schema-migration/scripts/run_migration.py 실행 중 Claude Code가 호출하여 상태 파악.
set -euo pipefail

SCHEMA_DIR="${1:-../schema-migration}"

echo "== Phase 1 Progress ======================================="

# 1. 프로세스 확인
PID=$(pgrep -f "run_migration.py" 2>/dev/null || true)
if [ -n "$PID" ]; then
    ELAPSED=$(ps -o etimes= -p "$PID" 2>/dev/null | tr -d ' ')
    echo " Status: RUNNING (PID $PID, ${ELAPSED}s elapsed)"
else
    echo " Status: NOT RUNNING"
fi

# 2. 로그 마지막 줄
LOG_FILES=$(ls -t "$SCHEMA_DIR"/workspace/logs/*.log "$SCHEMA_DIR"/*.log 2>/dev/null | head -1)
if [ -n "$LOG_FILES" ]; then
    echo ""
    echo " Last 10 log lines:"
    tail -10 "$LOG_FILES" 2>/dev/null | sed 's/^/   /'
fi

# 3. migration_result.json 있으면 결과
RESULT="$SCHEMA_DIR/migration_result.json"
if [ -f "$RESULT" ]; then
    echo ""
    echo "-- Result (완료됨) --"
    python3 -c "
import json
r = json.loads(open('$RESULT').read())
print(f'  Migration ID: {r.get(\"migration_id\", \"?\")}')
print(f'  Duration: {r.get(\"total_duration_seconds\", 0):.0f}s')
sm = r.get('schema_migration', {})
if isinstance(sm, dict):
    print(f'  Schema status: {sm.get(\"status\", \"?\")}')
    nodes = sm.get('execution_order', [])
    if nodes: print(f'  Nodes: {\", \".join(nodes)}')
dm = r.get('data_migration', {})
if isinstance(dm, dict):
    print(f'  Data status: {dm.get(\"status\", \"?\")}')
dv = r.get('data_verification', {})
if isinstance(dv, dict) and dv.get('success'):
    dd = dv.get('data_verification', {})
    print(f'  Verification: {dd.get(\"overall_status\", \"?\")}')
" 2>/dev/null
fi

# 4. DynamoDB 체크포인트 (boto3 있으면)
python3 -c "
import boto3, os, json
region = os.environ.get('AWS_DEFAULT_REGION', 'ap-northeast-2')
ddb = boto3.resource('dynamodb', region_name=region)
table = ddb.Table('oma-migration-state')
resp = table.scan(Limit=5)
items = resp.get('Items', [])
if items:
    print()
    print(' DynamoDB checkpoints:')
    for item in sorted(items, key=lambda x: x.get('timestamp', 0), reverse=True)[:3]:
        print(f'   {item.get(\"migration_id\", \"?\")} / {item.get(\"node_name\", \"?\")} -> {item.get(\"status\", \"?\")}')
" 2>/dev/null || true

echo "========================================================="
