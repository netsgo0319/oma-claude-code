#!/usr/bin/env python3
"""
Phase 2.5: Test Case Generator (sqlplus 기반, 다중 소스)

4가지 소스에서 바인드 값을 수집하여 다양한 테스트 케이스를 생성한다:
  1. V$SQL_BIND_CAPTURE — 실제 운영에서 캡처된 바인드 값 (가장 현실적)
  2. ALL_TAB_COL_STATISTICS — MIN/MAX/NUM_DISTINCT로 경계값 테스트
  3. ALL_CONSTRAINTS (FK) — 참조 테이블에서 실제 존재하는 값 샘플링
  4. 이름/타입 추론 — 메타데이터 없을 때 fallback

Usage:
    python3 tools/generate-test-cases.py
    python3 tools/generate-test-cases.py --results-dir workspace/results

Output:
    workspace/results/{file}/v1/test-cases.json (파일별)

Requires:
    - sqlplus + Oracle 환경변수
"""

import json
import glob
import re
import os
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime


# ──────────────────────────────────────────────
# Oracle 접속 헬퍼
# ──────────────────────────────────────────────

def _oracle_conn_str():
    """Build Oracle sqlplus connection string."""
    ora_user = os.environ.get('ORACLE_USER', '')
    ora_pass = os.environ.get('ORACLE_PASSWORD', '')
    ora_host = os.environ.get('ORACLE_HOST', '')
    ora_port = os.environ.get('ORACLE_PORT', '1521')
    ora_sid = os.environ.get('ORACLE_SID', '')
    conn_type = os.environ.get('ORACLE_CONN_TYPE', 'service')
    if conn_type == 'sid':
        return f"{ora_user}/{ora_pass}@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={ora_host})(PORT={ora_port}))(CONNECT_DATA=(SID={ora_sid})))"
    return f"{ora_user}/{ora_pass}@{ora_host}:{ora_port}/{ora_sid}"


def _find_sqlplus():
    for path in ['/opt/oracle/instantclient_23_3/sqlplus', '/usr/bin/sqlplus']:
        if os.path.exists(path):
            return path
    return 'sqlplus'


def _run_sqlplus(sql_input, timeout=120):
    """Run SQL via sqlplus, return stdout."""
    conn_str = _oracle_conn_str()
    try:
        result = subprocess.run(
            [_find_sqlplus(), '-S', conn_str],
            input=sql_input, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"  WARNING: sqlplus 실행 실패: {e}")
        return ''


def _oracle_available():
    ora_user = os.environ.get('ORACLE_USER', '')
    ora_host = os.environ.get('ORACLE_HOST', '')
    import shutil
    return bool(ora_user and ora_host and shutil.which('sqlplus'))


def _oracle_schema():
    return os.environ.get('ORACLE_SCHEMA', os.environ.get('ORACLE_USER', '')).upper()


# ──────────────────────────────────────────────
# 소스 1: ALL_TAB_COLUMNS (컬럼 타입)
# ──────────────────────────────────────────────

def get_oracle_columns():
    """Oracle ALL_TAB_COLUMNS에서 컬럼 메타데이터 수집."""
    if not _oracle_available():
        print("  WARNING: Oracle 미연결. 이름 기반으로만 TC 생성.")
        return {}

    schema = _oracle_schema()
    sql = f"""SET PAGESIZE 0 FEEDBACK OFF LINESIZE 500 TRIMSPOOL ON
SELECT TABLE_NAME || '|' || COLUMN_NAME || '|' || DATA_TYPE || '|' || NULLABLE || '|' || NVL(DATA_LENGTH, 0)
FROM ALL_TAB_COLUMNS
WHERE OWNER = '{schema}'
ORDER BY TABLE_NAME, COLUMN_NAME;
EXIT;
"""
    output = _run_sqlplus(sql)
    col_types = {}
    for line in output.split('\n'):
        parts = line.strip().split('|')
        if len(parts) >= 4:
            table, col, dtype, nullable = [p.strip() for p in parts[:4]]
            data_len = int(parts[4].strip()) if len(parts) > 4 and parts[4].strip().isdigit() else 0
            info = {'type': dtype, 'nullable': nullable, 'data_length': data_len}
            col_types[f"{table}.{col}"] = info
            col_types[col] = info
    print(f"  소스1 ALL_TAB_COLUMNS: {len(col_types)}개 컬럼")
    return col_types


# ──────────────────────────────────────────────
# 소스 2: V$SQL_BIND_CAPTURE (실제 바인드 값)
# ──────────────────────────────────────────────

def get_bind_captures():
    """V$SQL_BIND_CAPTURE에서 실제 캡처된 바인드 값 수집."""
    if not _oracle_available():
        return {}

    sql = """SET PAGESIZE 0 FEEDBACK OFF LINESIZE 1000 TRIMSPOOL ON
SELECT DISTINCT
    NAME || '|' || NVL(TO_CHAR(VALUE_STRING), 'NULL') || '|' || NVL(DATATYPE_STRING, 'VARCHAR2(32)')
FROM V$SQL_BIND_CAPTURE
WHERE VALUE_STRING IS NOT NULL
  AND ROWNUM <= 5000
ORDER BY 1;
EXIT;
"""
    output = _run_sqlplus(sql, timeout=30)
    captures = {}  # {param_name: [captured_values]}
    for line in output.split('\n'):
        parts = line.strip().split('|')
        if len(parts) >= 2:
            name = parts[0].strip().lstrip(':').lower()
            value = parts[1].strip()
            if name and value != 'NULL':
                captures.setdefault(name, []).append(value)

    # 각 파라미터당 최대 5개 값만 유지
    for k in captures:
        captures[k] = list(dict.fromkeys(captures[k]))[:5]

    total = sum(len(v) for v in captures.values())
    print(f"  소스2 V$SQL_BIND_CAPTURE: {len(captures)}개 파라미터, {total}개 값")
    return captures


# ──────────────────────────────────────────────
# 소스 3: ALL_TAB_COL_STATISTICS (경계값)
# ──────────────────────────────────────────────

def get_column_stats():
    """ALL_TAB_COL_STATISTICS에서 MIN/MAX 값 수집."""
    if not _oracle_available():
        return {}

    schema = _oracle_schema()
    sql = f"""SET PAGESIZE 0 FEEDBACK OFF LINESIZE 1000 TRIMSPOOL ON
SELECT TABLE_NAME || '|' || COLUMN_NAME || '|' || NVL(TO_CHAR(LOW_VALUE), 'NULL') || '|' || NVL(TO_CHAR(HIGH_VALUE), 'NULL') || '|' || NVL(NUM_DISTINCT, 0)
FROM ALL_TAB_COL_STATISTICS
WHERE OWNER = '{schema}'
  AND LOW_VALUE IS NOT NULL
  AND ROWNUM <= 10000
ORDER BY TABLE_NAME, COLUMN_NAME;
EXIT;
"""
    output = _run_sqlplus(sql, timeout=60)
    stats = {}  # {TABLE.COLUMN: {low, high, distinct}}
    for line in output.split('\n'):
        parts = line.strip().split('|')
        if len(parts) >= 4:
            table, col = parts[0].strip(), parts[1].strip()
            low, high = parts[2].strip(), parts[3].strip()
            distinct = int(parts[4].strip()) if len(parts) > 4 and parts[4].strip().isdigit() else 0
            if low != 'NULL':
                stats[f"{table}.{col}"] = {'low': low, 'high': high, 'distinct': distinct}
                stats[col] = {'low': low, 'high': high, 'distinct': distinct}

    print(f"  소스3 ALL_TAB_COL_STATISTICS: {len(stats)}개 컬럼 통계")
    return stats


# ──────────────────────────────────────────────
# 소스 4: ALL_CONSTRAINTS (FK → 실제 값 샘플링)
# ──────────────────────────────────────────────

def get_fk_samples():
    """FK 관계에서 참조 테이블의 실제 값 샘플링."""
    if not _oracle_available():
        return {}

    schema = _oracle_schema()
    # FK 컬럼 → 참조 테이블.컬럼 매핑
    sql = f"""SET PAGESIZE 0 FEEDBACK OFF LINESIZE 1000 TRIMSPOOL ON
SELECT CC.TABLE_NAME || '|' || CC.COLUMN_NAME || '|' || RC.TABLE_NAME || '|' || RC.COLUMN_NAME
FROM ALL_CONS_COLUMNS CC
JOIN ALL_CONSTRAINTS C ON CC.CONSTRAINT_NAME = C.CONSTRAINT_NAME AND CC.OWNER = C.OWNER
JOIN ALL_CONS_COLUMNS RC ON C.R_CONSTRAINT_NAME = RC.CONSTRAINT_NAME AND C.R_OWNER = RC.OWNER
WHERE C.CONSTRAINT_TYPE = 'R'
  AND C.OWNER = '{schema}'
  AND ROWNUM <= 3000
ORDER BY 1, 2;
EXIT;
"""
    output = _run_sqlplus(sql, timeout=60)
    fk_map = {}  # {TABLE.COLUMN: (ref_table, ref_col)}
    for line in output.split('\n'):
        parts = line.strip().split('|')
        if len(parts) >= 4:
            table, col, ref_table, ref_col = [p.strip() for p in parts[:4]]
            fk_map[f"{table}.{col}"] = (ref_table, ref_col)
            fk_map[col] = (ref_table, ref_col)

    # 참조 테이블에서 실제 값 샘플링 (유니크한 ref_table.ref_col 조합)
    fk_values = {}  # {column: [sampled_values]}
    sampled = set()
    for key, (ref_table, ref_col) in fk_map.items():
        sample_key = f"{ref_table}.{ref_col}"
        if sample_key in sampled:
            # 이미 샘플링된 참조 컬럼 재사용
            for k, v in fk_values.items():
                if k.endswith(f".{ref_col}") or k == ref_col:
                    fk_values[key] = v
                    break
            continue
        sampled.add(sample_key)

        sample_sql = f"""SET PAGESIZE 0 FEEDBACK OFF LINESIZE 500 TRIMSPOOL ON
SELECT DISTINCT {ref_col} FROM {schema}.{ref_table} WHERE {ref_col} IS NOT NULL AND ROWNUM <= 3;
EXIT;
"""
        sample_output = _run_sqlplus(sample_sql, timeout=10)
        values = [l.strip() for l in sample_output.split('\n') if l.strip() and 'ERROR' not in l and 'ORA-' not in l]
        if values:
            fk_values[key] = values[:3]

    total = sum(len(v) for v in fk_values.values())
    print(f"  소스4 FK 샘플링: {len(fk_values)}개 FK 컬럼, {total}개 실제 값")
    return fk_values


# ──────────────────────────────────────────────
# 값 생성
# ──────────────────────────────────────────────

def gen_value(param_name, col_info=None, captures=None, col_stats=None, fk_values=None):
    """파라미터별 최적 테스트 값 생성. 우선순위: captures > fk > stats > 타입 > 이름."""
    pn = param_name.lower()
    pu = param_name.upper()

    # 특수 파라미터 (비즈니스 관행)
    special = {
        'sysdate': '2026-01-15 10:30:00',
        'surkey': 'SYSTEM', 'inserturkey': 'SYSTEM', 'updateurkey': 'SYSTEM',
        'delyn': 'N', 'useyn': 'Y',
        'owkey': 'DS', 'ctkey': 'HE',
        'interfaceid': 'IF001', 'ifid': '1',
    }
    if pn in special:
        return special[pn]

    # 소스 1: V$SQL_BIND_CAPTURE (실제 캡처된 값 — 최우선)
    if captures:
        for key in [pn, pu, param_name]:
            if key in captures and captures[key]:
                return captures[key][0]  # 첫 번째 캡처 값

    # 소스 2: FK 샘플링 (참조 테이블에서 실제 존재하는 값)
    if fk_values:
        for key in [pu, pn, param_name]:
            if key in fk_values and fk_values[key]:
                return fk_values[key][0]

    # 소스 3: 타입 기반 (ALL_TAB_COLUMNS)
    dtype = col_info.get('type', '').upper() if col_info else ''
    data_len = col_info.get('data_length', 0) if col_info else 0

    if dtype in ('NUMBER', 'NUMERIC', 'INTEGER', 'FLOAT', 'BINARY_FLOAT', 'BINARY_DOUBLE',
                 'INT', 'BIGINT', 'SMALLINT', 'DECIMAL'):
        # 통계에서 범위 값 사용
        if col_stats:
            for key in [pu, pn]:
                if key in col_stats and col_stats[key].get('low', '').replace('.', '').replace('-', '').isdigit():
                    return int(float(col_stats[key]['low']))
        return 1
    if dtype in ('DATE', 'TIMESTAMP', 'TIMESTAMP(6)', 'TIMESTAMP WITH TIME ZONE',
                 'TIMESTAMP WITH LOCAL TIME ZONE'):
        return '2026-01-15 10:30:00'
    if dtype in ('CHAR', 'NCHAR'):
        # CHAR(N) → N글자에 맞는 값
        if data_len and data_len <= 2:
            return 'Y'
        return 'T'
    if dtype in ('VARCHAR2', 'NVARCHAR2', 'VARCHAR', 'NVARCHAR', 'CLOB', 'NCLOB'):
        if data_len and data_len <= 1:
            return 'T'
        if data_len and data_len <= 5:
            return 'A1'
        return 'TEST'
    if dtype in ('BOOLEAN',):
        return True
    if dtype in ('BLOB', 'RAW', 'LONG RAW'):
        return None

    # 소스 4: 이름 기반 추론 (fallback)
    if any(k in pn for k in ('qty', 'cnt', 'amt', 'price', 'prc', 'rate', 'seq',
                              'no', 'num', 'idx', 'id', 'size', 'len', 'weight',
                              'page', 'limit', 'offset', 'rowcnt', 'pagesize')):
        return 1
    if any(k in pn for k in ('date', 'day', 'dt', 'time', 'tm')):
        return '20260115'
    if pn.endswith('yn') or pn in ('yn',):
        return 'Y'
    if any(k in pn for k in ('key', 'cd', 'code', 'type', 'div', 'gb', 'flag', 'stat')):
        return 'A1'
    if any(k in pn for k in ('nm', 'name', 'desc', 'msg', 'text', 'remark', 'note')):
        return 'TEST'

    return 'T'


def gen_boundary_case(params, binds, col_stats):
    """경계값 테스트: MIN/MAX 값 사용."""
    boundary = dict(binds)
    changed = False
    for p in params:
        pu = p.upper()
        if pu in col_stats and col_stats[pu].get('high'):
            high = col_stats[pu]['high']
            # 숫자면 숫자로, 아니면 문자열로
            try:
                boundary[p] = int(float(high))
            except ValueError:
                boundary[p] = str(high)[:50]
            changed = True
        if changed and len([k for k in boundary if boundary[k] != binds.get(k)]) >= 3:
            break
    return boundary if changed else None


def gen_capture_case(params, binds, captures):
    """캡처된 실제 바인드 값으로 TC 생성."""
    captured = dict(binds)
    changed = False
    for p in params:
        for key in [p.lower(), p.upper(), p]:
            if key in captures and len(captures[key]) > 1:
                # 두 번째 캡처 값 사용 (첫 번째는 default에서 사용)
                captured[p] = captures[key][1]
                changed = True
                break
    return captured if changed else None


def gen_fk_case(params, binds, fk_values):
    """FK에서 샘플링한 실제 값으로 TC 생성."""
    fk_binds = dict(binds)
    changed = False
    for p in params:
        for key in [p.upper(), p.lower(), p]:
            if key in fk_values and fk_values[key]:
                vals = fk_values[key]
                # default와 다른 값 선택
                for v in vals:
                    if v != str(binds.get(p, '')):
                        fk_binds[p] = v
                        changed = True
                        break
                break
    return fk_binds if changed else None


# ──────────────────────────────────────────────
# 소스 5: 테이블 행수 (DML 위험도 판단)
# ──────────────────────────────────────────────

def get_table_row_counts():
    """ALL_TABLES에서 NUM_ROWS 수집. DML이 대량 행에 영향줄 위험 판단용."""
    if not _oracle_available():
        return {}

    schema = _oracle_schema()
    sql = f"""SET PAGESIZE 0 FEEDBACK OFF LINESIZE 500 TRIMSPOOL ON
SELECT TABLE_NAME || '|' || NVL(NUM_ROWS, 0)
FROM ALL_TABLES
WHERE OWNER = '{schema}'
ORDER BY NUM_ROWS DESC NULLS LAST;
EXIT;
"""
    output = _run_sqlplus(sql, timeout=30)
    row_counts = {}
    for line in output.split('\n'):
        parts = line.strip().split('|')
        if len(parts) == 2 and parts[1].strip().isdigit():
            row_counts[parts[0].strip()] = int(parts[1].strip())
    print(f"  소스5 ALL_TABLES: {len(row_counts)}개 테이블 행수")
    return row_counts


DML_ROW_LIMIT = 10000  # 이 이상이면 DML TC를 EXPLAIN_ONLY로 표시


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Phase 2.5: Test Case Generator (다중 소스)')
    parser.add_argument('--results-dir', default='workspace/results', help='Results directory')
    parser.add_argument('--skip-oracle', action='store_true', help='Oracle 접속 없이 이름 기반으로만 생성')
    parser.add_argument('--dml-row-limit', type=int, default=10000,
                        help='DML 대상 테이블이 이 행수 이상이면 execute 스킵 (기본: 10000)')
    args = parser.parse_args()

    global DML_ROW_LIMIT
    DML_ROW_LIMIT = args.dml_row_limit

    results_dir = Path(args.results_dir)
    print("=== Phase 2.5: Test Case Generator (다중 소스) ===\n")

    # 1. Oracle 메타데이터 수집 (5소스)
    if args.skip_oracle or not _oracle_available():
        col_types, captures, col_stats, fk_values, table_rows = {}, {}, {}, {}, {}
        print("  Oracle 미연결 — 이름 기반으로만 TC 생성\n")
    else:
        print("  Oracle 메타데이터 수집 중...")
        col_types = get_oracle_columns()
        captures = get_bind_captures()
        col_stats = get_column_stats()
        fk_values = get_fk_samples()
        table_rows = get_table_row_counts()
        print()

    # 2. parsed.json에서 쿼리별 TC 생성
    total_files = 0
    total_cases = 0
    source_counts = {'COLUMN_METADATA': 0, 'NULL_SEMANTICS': 0, 'EMPTY_STRING': 0,
                     'BIND_CAPTURE': 0, 'BOUNDARY': 0, 'FK_SAMPLE': 0}

    for parsed_path in sorted(results_dir.glob('*/v1/parsed.json')):
        try:
            with open(parsed_path, 'r', encoding='utf-8') as f:
                parsed = json.load(f)
        except Exception:
            continue

        fname = parsed.get('source_file', parsed_path.parent.parent.name)
        queries = parsed.get('queries', [])
        file_tc = {}

        for q in queries:
            qid = q.get('query_id', '')
            raw = q.get('sql_raw', '')
            for b in q.get('sql_branches', []):
                raw += ' ' + b.get('sql', '')

            params = list(set(re.findall(r'#\{(\w+)\}', raw)))
            if not params:
                continue

            # 테이블명 추출
            tables = re.findall(r'\b(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)', raw, re.IGNORECASE)
            tables = [t.upper() for t in tables
                      if t.upper() not in ('DUAL', 'SELECT', 'WHERE', 'SET', 'VALUES')]

            # 파라미터별 메타데이터 매핑
            param_col_info = {}
            for p in params:
                col_info = None
                for t in tables:
                    key = f"{t}.{p.upper()}"
                    if key in col_types:
                        col_info = col_types[key]
                        break
                if not col_info:
                    col_info = col_types.get(p.upper())
                param_col_info[p] = col_info

            # --- DML 위험도 판단 ---
            qtype = q.get('type', 'select').lower()
            is_dml = qtype in ('insert', 'update', 'delete')
            dml_large_table = False
            if is_dml and table_rows:
                for t in tables:
                    if table_rows.get(t, 0) >= DML_ROW_LIMIT:
                        dml_large_table = True
                        break

            # --- TC 생성 ---
            cases = []

            # TC 1: Default (타입/캡처 기반)
            binds = {}
            for p in params:
                binds[p] = gen_value(p, param_col_info.get(p), captures, col_stats, fk_values)
            tc_meta = {'name': 'default', 'params': binds, 'source': 'COLUMN_METADATA'}
            if dml_large_table:
                tc_meta['execute_skip'] = True
                tc_meta['skip_reason'] = f'DML on large table ({max(table_rows.get(t,0) for t in tables):,} rows)'
            cases.append(tc_meta)
            source_counts['COLUMN_METADATA'] += 1

            # TC 2: NULL 케이스 — DML에서는 생성하지 않음
            # DML + NULL 바인딩: MyBatis <if test="param != null"> 분기를 타면
            # WHERE 절 조건이 빠져서 풀스캔 UPDATE/DELETE 위험
            if not is_dml:
                null_binds = dict(binds)
                for p in params[:3]:
                    null_binds[p] = None
                if null_binds != binds:
                    cases.append({'name': 'null_test', 'params': null_binds, 'source': 'NULL_SEMANTICS'})
                    source_counts['NULL_SEMANTICS'] += 1

            # TC 3: Empty string — DML에서는 생성하지 않음!
            # Oracle '' = NULL이므로 WHERE key = '' → WHERE key IS NULL → 풀스캔 UPDATE 위험
            if not is_dml:
                empty_binds = dict(binds)
                for p in params[:3]:
                    if isinstance(binds.get(p), str):
                        empty_binds[p] = ''
                if empty_binds != binds:
                    cases.append({'name': 'empty_string', 'params': empty_binds, 'source': 'EMPTY_STRING'})
                    source_counts['EMPTY_STRING'] += 1

            # TC 4: Bind Capture (실제 캡처된 값)
            if captures:
                cap_case = gen_capture_case(params, binds, captures)
                if cap_case:
                    tc_cap = {'name': 'bind_capture', 'params': cap_case, 'source': 'BIND_CAPTURE'}
                    if dml_large_table:
                        tc_cap['execute_skip'] = True
                        tc_cap['skip_reason'] = 'DML on large table'
                    cases.append(tc_cap)
                    source_counts['BIND_CAPTURE'] += 1

            # TC 5: Boundary (MIN/MAX) — DML에서는 경계값이 위험할 수 있으므로 스킵
            if col_stats and not is_dml:
                bound_case = gen_boundary_case(params, binds, col_stats)
                if bound_case:
                    cases.append({'name': 'boundary', 'params': bound_case, 'source': 'BOUNDARY'})
                    source_counts['BOUNDARY'] += 1

            # TC 6: FK sample (참조 테이블 실제 값)
            if fk_values:
                fk_case = gen_fk_case(params, binds, fk_values)
                if fk_case:
                    tc_fk = {'name': 'fk_sample', 'params': fk_case, 'source': 'FK_SAMPLE'}
                    if dml_large_table:
                        tc_fk['execute_skip'] = True
                        tc_fk['skip_reason'] = 'DML on large table'
                    cases.append(tc_fk)
                    source_counts['FK_SAMPLE'] += 1

            total_cases += len(cases)
            file_tc[qid] = cases

        if file_tc:
            tc_path = parsed_path.parent / 'test-cases.json'
            with open(tc_path, 'w', encoding='utf-8') as f:
                json.dump(file_tc, f, indent=2, ensure_ascii=False)
            total_files += 1

    # Write merged TC for MyBatis extractor (--params)
    merged_tc = {}
    for parsed_path in sorted(results_dir.glob('*/v1/parsed.json')):
        tc_path = parsed_path.parent / 'test-cases.json'
        if tc_path.exists():
            try:
                with open(tc_path) as f:
                    file_tcs = json.load(f)
                # Convert to MyBatis-consumable format: {queryId: [{param_map}, ...]}
                for qid, cases in file_tcs.items():
                    mybatis_params = []
                    for c in cases:
                        params = c.get('params', {})
                        if params and not c.get('execute_skip'):
                            mybatis_params.append(params)
                    if mybatis_params:
                        merged_tc[qid] = mybatis_params
            except Exception:
                pass

    merged_path = results_dir / '_test-cases' / 'merged-tc.json'
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    with open(merged_path, 'w', encoding='utf-8') as f:
        json.dump(merged_tc, f, indent=2, ensure_ascii=False)
    print(f"\n  Merged TC for MyBatis: {merged_path} ({len(merged_tc)} queries)")

    print(f"\n=== 완료 ===")
    print(f"  파일: {total_files}개")
    print(f"  테스트 케이스: {total_cases}개")
    print(f"  소스별:")
    for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
        if cnt > 0:
            print(f"    {src}: {cnt}")

    # Activity log
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('PHASE_END', agent='generate-test-cases', phase='phase_2.5',
                     detail=f"TC: {total_files}파일, {total_cases}건 "
                            f"(capture:{source_counts['BIND_CAPTURE']}, "
                            f"boundary:{source_counts['BOUNDARY']}, "
                            f"fk:{source_counts['FK_SAMPLE']})")
    except Exception:
        pass


if __name__ == '__main__':
    main()
