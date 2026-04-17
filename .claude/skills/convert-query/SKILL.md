---
name: convert-query
description: 단일 쿼리 변환 + TC 생성 + 검증. SQL 하나를 던지면 Oracle→PG 변환, LLM TC 생성, EXPLAIN/Compare까지 한번에 수행합니다. /convert-query로 호출.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Convert Query (단일 쿼리 테스트)

SQL 하나를 Oracle→PostgreSQL 변환하고 검증까지 한번에.

## 사용법

```
/convert-query SELECT NVL(NAME, 'N/A') FROM TB_USER WHERE ROWNUM <= 10
```

## 실행 순서

### 1. 변환

```bash
python3 -c "
import sys; sys.path.insert(0, 'tools')
from oracle_to_pg_converter import OracleToPgConverter
c = OracleToPgConverter()
sql = '''$ARGUMENTS'''
converted, report = c.convert_sql(sql)
print('=== 변환 결과 ===')
print(converted)
print()
print('=== 적용 룰 ===')
for rule, count in report.get('rules_applied', {}).items():
    print(f'  {rule}: {count}')
residual = report.get('residual_oracle_patterns', [])
if residual:
    print()
    print('=== 잔존 Oracle 패턴 (LLM 변환 필요) ===')
    for r in residual:
        print(f'  {r[\"pattern\"]}: {r[\"context\"][:60]}')
"
```

### 2. TC 생성 (LLM)

```bash
python3 -c "
import sys, json; sys.path.insert(0, 'tools')
from llm_tc_generator import generate_tcs_for_query
sql = '''$ARGUMENTS'''
import re
params = list(dict.fromkeys(re.findall(r'#\{(\w+)\}', sql)))
tcs = generate_tcs_for_query(sql, params)
print('=== TC ===')
for tc in tcs:
    print(f'  {tc[\"name\"]}: {json.dumps(tc[\"params\"], ensure_ascii=False)}')
"
```

### 3. EXPLAIN 검증 (PG 접속 시)

```bash
# PG 환경변수가 설정되어 있으면
if [ -n "$PG_HOST" ]; then
  # 변환된 SQL로 EXPLAIN
  CONVERTED_SQL="<2단계에서 나온 변환 결과>"
  PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p ${PG_PORT:-5432} -U $PG_USER -d $PG_DATABASE \
    -c "EXPLAIN $CONVERTED_SQL" 2>&1
fi
```

### 4. Compare (Oracle + PG 모두 접속 시)

양쪽 DB에 TC 바인딩 후 실행하여 행수 비교.

## 출력 예시

```
=== 변환 결과 ===
SELECT COALESCE(NAME, 'N/A') FROM TB_USER LIMIT 10

=== 적용 룰 ===
  NVL->COALESCE: 1
  ROWNUM->LIMIT: 1

=== TC ===
  tc_llm_1: {"name": "홍길동", "status": "ACTIVE"}
  tc_llm_2: {"name": "", "status": "INACTIVE"}

=== EXPLAIN ===
Seq Scan on tb_user  (cost=0.00..1.10 rows=10 width=32)

=== Compare ===
Oracle: 10행, PG: 10행 → MATCH ✅
```
