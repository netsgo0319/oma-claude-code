---
name: preflight
description: Phase 2(앱 마이그레이션) 사전 환경 점검. PG 스키마 검증, Phase 1 결과 확인, DB 연결 테스트, XML 수집. /preflight로 호출.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Preflight (/preflight)

Phase 2(앱 마이그레이션) 실행 전 환경 점검. Phase 1 완료 여부와 PG 스키마 준비 상태를 확인.

## 실행 절차

### 1. migration-config.json 확인

```bash
CONFIG="../migration-config.json"
[ ! -f "$CONFIG" ] && CONFIG="migration-config.json"
if [ -f "$CONFIG" ]; then
  python3 -c "
import json
c = json.load(open('$CONFIG'))
print(f'프로젝트: {c[\"project\"][\"name\"]}')
p1 = c.get('phase1', {})
print(f'Phase 1: {p1.get(\"status\",\"unknown\")}')
if p1.get('status') == 'completed':
    print(f'  테이블: {p1.get(\"schema_migration\",{}).get(\"tables_total\",\"?\")}')
    print(f'  데이터: {p1.get(\"data_migration\",{}).get(\"tables_migrated\",\"?\")} tables')
"
else
  echo "⚠️ migration-config.json 없음 — Phase 1 결과 없이 독립 실행"
fi
```

### 2. DB 연결 테스트

```bash
python3 tools/preflight-check.py 2>&1
```

### 3. PG 스키마 검증 (★ 핵심)

```bash
python3 -c "
import subprocess, os, json
pg_host = os.environ.get('PG_HOST','')
pg_db = os.environ.get('PG_DATABASE','')
pg_user = os.environ.get('PG_USER','')
pg_schema = os.environ.get('PG_SCHEMA','public')
if not (pg_host and pg_db):
    print('⚠️ PG 환경변수 미설정')
    exit()
env = dict(os.environ, PGPASSWORD=os.environ.get('PG_PASSWORD',''))
# 테이블 수
r = subprocess.run(['psql','-h',pg_host,'-p',os.environ.get('PG_PORT','5432'),'-U',pg_user,'-d',pg_db,'-t','-A','-c',
    f\"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{pg_schema}'\"],
    capture_output=True, text=True, env=env, timeout=10)
tables = r.stdout.strip()
# 함수 수
r2 = subprocess.run(['psql','-h',pg_host,'-p',os.environ.get('PG_PORT','5432'),'-U',pg_user,'-d',pg_db,'-t','-A','-c',
    f\"SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema='{pg_schema}'\"],
    capture_output=True, text=True, env=env, timeout=10)
functions = r2.stdout.strip()
print(f'PG 스키마 ({pg_schema}): {tables} tables, {functions} functions')
if int(tables or 0) == 0:
    print('⚠️ PG 테이블 0개 — Phase 1 미완료 가능. DBA FAIL 다수 예상.')
"
```

### 4. XML 파일 확인

```bash
XML_COUNT=$(ls pipeline/shared/input/*.xml 2>/dev/null | wc -l)
echo "XML 파일: $XML_COUNT"
if [ "$XML_COUNT" -eq 0 ]; then
  echo "⚠️ pipeline/shared/input/에 XML 없음. 원본 XML을 복사하세요."
fi
```

### 5. LLM TC 환경 확인

```bash
python3 -c "
import os
regions = os.environ.get('LLM_TC_REGIONS','')
enabled = os.environ.get('LLM_TC_ENABLED','1')
print(f'LLM_TC_ENABLED={enabled}')
print(f'LLM_TC_REGIONS={regions or \"⚠️ 미설정 (단일 리전 throttling 위험)\"}')
try:
    import boto3; print('✅ boto3 OK')
except: print('❌ boto3 없음 — LLM TC 불가')
"
```

### 6. 결과 요약

```
Phase 2 Preflight 체크리스트:
- [ ] migration-config.json (Phase 1 결과)
- [ ] Oracle 연결 OK
- [ ] PostgreSQL 연결 OK
- [ ] PG 스키마에 테이블 존재
- [ ] XML 파일 존재
- [ ] LLM TC 환경 (boto3 + 멀티리전)
- [ ] .env 핵심 변수 OK
```

## 다음 단계

```bash
/convert          # 전체 파이프라인 (Step 0~4)
# 또는
"변환해줘"
```
