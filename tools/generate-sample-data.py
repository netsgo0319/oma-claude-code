#!/usr/bin/env python3
"""
Phase 0: Sample Data Collector

MyBatis XML에서 참조된 Oracle 테이블의 샘플 데이터(10행)를 수집하여 JSON으로 저장한다.

Usage:
    python3 tools/generate-sample-data.py
    python3 tools/generate-sample-data.py --force

Output:  workspace/results/_samples/{TABLE_NAME}.json
"""

import json, re, os, sys, subprocess, argparse
from pathlib import Path
from datetime import datetime

# ── Oracle 접속 헬퍼 (generate-test-cases.py 패턴 동일) ──

def _oracle_conn_str():
    user = os.environ.get('ORACLE_USER', '')
    pw   = os.environ.get('ORACLE_PASSWORD', '')
    host = os.environ.get('ORACLE_HOST', '')
    port = os.environ.get('ORACLE_PORT', '1521')
    sid  = os.environ.get('ORACLE_SID', '')
    if os.environ.get('ORACLE_CONN_TYPE', 'service') == 'sid':
        return (f"{user}/{pw}@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)"
                f"(HOST={host})(PORT={port}))(CONNECT_DATA=(SID={sid})))")
    return f"{user}/{pw}@{host}:{port}/{sid}"

def _find_sqlplus():
    for p in ['/opt/oracle/instantclient_23_3/sqlplus', '/usr/bin/sqlplus']:
        if os.path.exists(p):
            return p
    return 'sqlplus'

def _run_sqlplus(sql_input, timeout=120):
    conn = _oracle_conn_str()
    try:
        r = subprocess.run([_find_sqlplus(), '-S', conn],
                           input=sql_input, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        print(f"  WARNING: sqlplus 실행 실패: {e}")
        return ''

def _oracle_schema():
    return os.environ.get('ORACLE_SCHEMA', os.environ.get('ORACLE_USER', '')).upper()

# ── XML에서 테이블명 추출 ──

_TABLE_RE = re.compile(
    r'\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_]*)', re.IGNORECASE)

_SKIP_WORDS = frozenset({
    'DUAL', 'SELECT', 'WHERE', 'SET', 'VALUES', 'AND', 'OR', 'NOT',
    'NULL', 'ON', 'AS', 'IN', 'EXISTS', 'INNER', 'LEFT', 'RIGHT',
    'OUTER', 'CROSS', 'FULL', 'ORDER', 'GROUP', 'HAVING', 'UNION',
})

def extract_tables_from_xml(xml_path):
    try:
        content = Path(xml_path).read_text(encoding='utf-8')
    except Exception:
        return set()
    return {m.group(1).upper() for m in _TABLE_RE.finditer(content)
            if m.group(1).upper() not in _SKIP_WORDS and len(m.group(1)) >= 2}

def collect_all_tables(input_dir):
    all_tables, xml_count = set(), 0
    for xml_file in sorted(Path(input_dir).glob('**/*.xml')):
        all_tables.update(extract_tables_from_xml(xml_file))
        xml_count += 1
    return sorted(all_tables), xml_count

# ── Oracle 샘플 데이터 수집 ──

def _get_oracle_connection():
    """oracledb Python 패키지로 Oracle 접속. 없으면 None."""
    try:
        import oracledb
    except ImportError:
        return None, 'oracledb not installed'
    host = os.environ.get('ORACLE_HOST', '')
    port = os.environ.get('ORACLE_PORT', '1521')
    sid = os.environ.get('ORACLE_SID', '')
    user = os.environ.get('ORACLE_USER', '')
    pwd = os.environ.get('ORACLE_PASSWORD', '')
    if not host or not user:
        return None, 'ORACLE_HOST/USER not set'
    try:
        dsn = f"{host}:{port}/{sid}"
        conn = oracledb.connect(user=user, password=pwd, dsn=dsn)
        return conn, None
    except Exception as e:
        return None, str(e)


def query_sample_rows(table_name, schema):
    """테이블에서 최대 10행. oracledb 우선, sqlplus fallback."""
    # Priority 1: oracledb (깔끔, 파싱 불필요)
    conn, err = _get_oracle_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {schema}.{table_name} WHERE ROWNUM <= 10")
            columns = [col[0] for col in cur.description]
            raw_rows = cur.fetchall()
            rows = []
            for row in raw_rows:
                rows.append({col: (str(v) if v is not None else None) for col, v in zip(columns, row)})
            cur.close()
            conn.close()
            return {'table': table_name, 'columns': columns, 'rows': rows, 'row_count': len(rows)}, None
        except Exception as e:
            conn.close()
            err_str = str(e)
            if 'ORA-00942' in err_str:
                return None, 'table or view does not exist (ORA-00942)'
            if 'ORA-01031' in err_str:
                return None, 'insufficient privileges (ORA-01031)'
            return None, err_str

    # Priority 2: sqlplus (fallback — 텍스트 파싱)
    sql = (f"SET PAGESIZE 50000 FEEDBACK OFF LINESIZE 32767 TRIMSPOOL ON\n"
           f"SET COLSEP '|'\nSET HEADING ON\nSET UNDERLINE OFF\n"
           f"SELECT * FROM {schema}.{table_name} WHERE ROWNUM <= 10;\nEXIT;\n")
    output = _run_sqlplus(sql, timeout=60)

    if not output:
        return None, 'empty response from sqlplus'
    for code, msg in [('ORA-00942', 'table or view does not exist'),
                      ('ORA-01031', 'insufficient privileges')]:
        if code in output:
            return None, f'{msg} ({code})'
    if 'ORA-' in output:
        m = re.search(r'(ORA-\d+[^\n]*)', output)
        return None, m.group(1) if m else 'unknown Oracle error'

    data_lines = [l for l in output.split('\n')
                  if l.strip() and not l.strip().startswith('SQL>')]
    if not data_lines:
        return None, 'no data lines in output'

    columns = [c.strip() for c in data_lines[0].split('|') if c.strip()]
    if not columns:
        return None, 'could not parse column headers'

    row_start = 1
    for i in range(1, min(3, len(data_lines))):
        if not data_lines[i].replace('-', '').replace(' ', '').replace('|', ''):
            row_start = i + 1
        else:
            break

    rows = []
    for line in data_lines[row_start:]:
        vals = [v.strip() for v in line.split('|')]
        if len(vals) < len(columns):
            continue
        rows.append({col: (v if v else None) for col, v in zip(columns, vals[:len(columns)])})

    return {'table': table_name, 'columns': columns, 'rows': rows, 'row_count': len(rows)}, None

# ── 메인 ──

def main():
    ap = argparse.ArgumentParser(description='Phase 0: Sample Data Collector')
    ap.add_argument('--input-dir', default='workspace/input', help='MyBatis XML 입력 디렉토리')
    ap.add_argument('--output-dir', default='workspace/results/_samples', help='출력 디렉토리')
    ap.add_argument('--force', action='store_true', help='기존 캐시 무시하고 재수집')
    args = ap.parse_args()

    start_time = datetime.now()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    schema = _oracle_schema()
    if not schema:
        print("ERROR: ORACLE_SCHEMA (또는 ORACLE_USER) 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    print("=== Phase 0: Sample Data Collector ===\n")
    print(f"  Input:  {args.input_dir}")
    print(f"  Output: {args.output_dir}")
    print(f"  Schema: {schema}")
    print(f"  Force:  {args.force}\n")

    # 1. XML에서 테이블명 수집
    tables, xml_count = collect_all_tables(args.input_dir)
    print(f"  XML 파일 스캔: {xml_count}개 파일, {len(tables)}개 유니크 테이블\n")
    if not tables:
        print("  테이블이 발견되지 않았습니다. 종료합니다.")
        sys.exit(0)

    # 2. 테이블별 샘플 수집
    sampled, skipped, errored = 0, 0, 0
    errors = {}

    for i, table in enumerate(tables, 1):
        out_path = output_dir / f'{table}.json'
        prefix = f"  [{i}/{len(tables)}] {table}"

        if out_path.exists() and not args.force:
            print(f"{prefix} ... cached (skip)")
            skipped += 1
            continue

        print(f"{prefix} ... ", end='', flush=True)
        result, error = query_sample_rows(table, schema)

        if error:
            print(f"ERROR: {error}")
            errored += 1
            errors[table] = error
        else:
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f"OK ({result['row_count']} rows, {len(result['columns'])} cols)")
            sampled += 1

    # 3. Summary
    elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    print(f"\n=== 완료 ({elapsed_ms}ms) ===")
    print(f"  테이블 발견: {len(tables)}개")
    print(f"  샘플 수집:   {sampled}개")
    print(f"  캐시 스킵:   {skipped}개")
    print(f"  에러:        {errored}개")
    if errors:
        print("\n  에러 상세:")
        for tbl, msg in sorted(errors.items()):
            print(f"    {tbl}: {msg}")

    # 4. Activity log
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('PHASE_END', agent='generate-sample-data', phase='phase_0',
                     detail=f"tables:{len(tables)}, sampled:{sampled}, "
                            f"skipped:{skipped}, errored:{errored}",
                     duration_ms=elapsed_ms)
    except Exception:
        pass


if __name__ == '__main__':
    main()
