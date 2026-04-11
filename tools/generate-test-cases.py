#!/usr/bin/env python3
"""
Phase 2.5: Test Case Generator (sqlplus 기반)
Oracle 딕셔너리에서 컬럼 메타데이터를 수집하고, 쿼리별 test-cases.json을 생성한다.

Usage:
    python3 tools/generate-test-cases.py
    python3 tools/generate-test-cases.py --parallel 8

Output:
    workspace/results/{file}/v1/test-cases.json (파일별)

Requires:
    - sqlplus + Oracle 환경변수 (ORACLE_HOST, ORACLE_PORT, ORACLE_SID, ORACLE_USER, ORACLE_PASSWORD)
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


def get_oracle_columns():
    """Oracle ALL_TAB_COLUMNS에서 컬럼 메타데이터 수집."""
    ora_user = os.environ.get('ORACLE_USER', '')
    ora_pass = os.environ.get('ORACLE_PASSWORD', '')
    ora_host = os.environ.get('ORACLE_HOST', '')
    ora_port = os.environ.get('ORACLE_PORT', '1521')
    ora_sid = os.environ.get('ORACLE_SID', '')

    if not ora_user or not ora_host:
        print("WARNING: Oracle 환경변수 미설정. 컬럼 메타데이터 없이 이름 기반으로만 생성.")
        return {}

    conn_str = f"{ora_user}/{ora_pass}@{ora_host}:{ora_port}/{ora_sid}"

    # Find sqlplus
    sqlplus = 'sqlplus'
    for path in ['/opt/oracle/instantclient_23_3/sqlplus', '/usr/bin/sqlplus']:
        if os.path.exists(path):
            sqlplus = path
            break

    sql_input = f"""SET PAGESIZE 0 FEEDBACK OFF LINESIZE 500 TRIMSPOOL ON
SELECT TABLE_NAME || '|' || COLUMN_NAME || '|' || DATA_TYPE || '|' || NULLABLE
FROM ALL_TAB_COLUMNS
WHERE OWNER = '{ora_user.upper()}'
ORDER BY TABLE_NAME, COLUMN_NAME;
EXIT;
"""
    try:
        result = subprocess.run(
            [sqlplus, '-S', conn_str],
            input=sql_input, capture_output=True, text=True, timeout=60
        )
        col_types = {}
        for line in result.stdout.strip().split('\n'):
            parts = line.strip().split('|')
            if len(parts) == 4:
                table, col, dtype, nullable = [p.strip() for p in parts]
                col_types[f"{table}.{col}"] = {'type': dtype, 'nullable': nullable}
                col_types[col] = {'type': dtype, 'nullable': nullable}
        print(f"  Oracle 컬럼 메타데이터: {len(col_types)}개")
        return col_types
    except Exception as e:
        print(f"WARNING: Oracle 메타데이터 수집 실패: {e}")
        return {}


def gen_value(param_name, col_info=None):
    """파라미터 이름 + 컬럼 타입으로 테스트 값 생성."""
    pn = param_name.lower()

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

    # 타입 기반
    dtype = col_info.get('type', '') if col_info else ''
    if dtype in ('NUMBER', 'NUMERIC', 'INTEGER', 'FLOAT', 'BINARY_FLOAT', 'BINARY_DOUBLE'):
        return 100
    if dtype in ('DATE', 'TIMESTAMP', 'TIMESTAMP(6)'):
        return '2026-01-15 10:30:00'

    # 이름 기반 추론
    if any(k in pn for k in ('qty', 'cnt', 'amt', 'price', 'prc', 'rate', 'seq', 'no', 'num')):
        return 100
    if any(k in pn for k in ('date', 'day', 'dt', 'time', 'tm')):
        return '20260115'
    if pn.endswith('yn') or pn in ('yn',):
        return 'Y'
    if any(k in pn for k in ('key', 'cd', 'code', 'type', 'div')):
        return 'TEST'
    if any(k in pn for k in ('nm', 'name', 'desc', 'msg', 'text', 'remark')):
        return 'TEST_VALUE'

    return 'TEST'


def gen_null_case(params, binds):
    """NULL 테스트 케이스 — 각 nullable 파라미터를 NULL로."""
    null_binds = dict(binds)
    for p in params[:3]:  # 최대 3개만
        null_binds[p] = None
    return null_binds


def main():
    parser = argparse.ArgumentParser(description='Phase 2.5: Test Case Generator')
    parser.add_argument('--results-dir', default='workspace/results', help='Results directory')
    parser.add_argument('--parallel', type=int, default=1, help='(reserved)')
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    print("=== Phase 2.5: Test Case Generator ===")

    # 1. Oracle 메타데이터 수집
    col_types = get_oracle_columns()

    # 2. parsed.json에서 쿼리별 파라미터 추출 + 테스트 케이스 생성
    total_files = 0
    total_cases = 0

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

            # 테이블명 추출 (메타데이터 매핑용)
            tables = re.findall(r'\b(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)', raw, re.IGNORECASE)
            tables = [t.upper() for t in tables
                      if t.upper() not in ('DUAL', 'SELECT', 'WHERE', 'SET', 'VALUES')]

            # 파라미터별 값 생성
            binds = {}
            for p in params:
                col_info = None
                for t in tables:
                    key = f"{t}.{p.upper()}"
                    if key in col_types:
                        col_info = col_types[key]
                        break
                if not col_info:
                    col_info = col_types.get(p.upper())
                binds[p] = gen_value(p, col_info)

            # 테스트 케이스 목록 (validate-queries.py가 기대하는 형식)
            cases = [
                {'name': 'default', 'params': binds, 'source': 'COLUMN_METADATA'},
            ]
            total_cases += 1

            # NULL 케이스 추가
            null_binds = gen_null_case(params, binds)
            if null_binds != binds:
                cases.append({'name': 'null_test', 'params': null_binds, 'source': 'NULL_SEMANTICS'})
                total_cases += 1

            # Empty string case (Oracle '' = NULL vs PG '' != NULL)
            empty_binds = dict(binds)
            for p in params[:3]:
                if isinstance(binds.get(p), str):
                    empty_binds[p] = ''
            if empty_binds != binds:
                cases.append({'name': 'empty_string', 'params': empty_binds, 'source': 'EMPTY_STRING_SEMANTICS'})
                total_cases += 1

            file_tc[qid] = cases

        if file_tc:
            tc_path = parsed_path.parent / 'test-cases.json'
            with open(tc_path, 'w', encoding='utf-8') as f:
                json.dump(file_tc, f, indent=2, ensure_ascii=False)
            total_files += 1

    print(f"\n=== 완료 ===")
    print(f"  파일: {total_files}개")
    print(f"  테스트 케이스: {total_cases}개")

    # Activity log
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('PHASE_END', agent='generate-test-cases', phase='phase_2.5',
                     detail=f"TC 생성: {total_files}파일, {total_cases}건")
    except Exception:
        pass


if __name__ == '__main__':
    main()
