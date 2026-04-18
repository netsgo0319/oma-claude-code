#!/usr/bin/env python3
"""
Preflight Check — DB 연결 + PG 스키마 검증 + Phase 1 결과 읽기.

Usage:
    python3 tools/preflight-check.py
    python3 tools/preflight-check.py --config ../migration-config.json
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def _load_dotenv():
    for p in [Path('.env'), Path('../.env')]:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                line = line.removeprefix('export').strip()
                k, _, v = line.partition('=')
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
            break


def check_oracle():
    """Oracle 연결 테스트."""
    host = os.environ.get('ORACLE_HOST', '')
    if not host:
        return {'status': 'skip', 'detail': 'ORACLE_HOST 미설정'}
    try:
        import oracledb
        dsn = f"{host}:{os.environ.get('ORACLE_PORT', '1521')}/{os.environ.get('ORACLE_SID', '')}"
        conn = oracledb.connect(
            user=os.environ.get('ORACLE_USER', ''),
            password=os.environ.get('ORACLE_PASSWORD', ''), dsn=dsn)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM user_tables")
        tables = cur.fetchone()[0]
        conn.close()
        return {'status': 'pass', 'detail': f'{tables} tables'}
    except Exception as e:
        return {'status': 'fail', 'detail': str(e)[:100]}


def check_pg():
    """PostgreSQL 연결 + 스키마 스캔."""
    host = os.environ.get('PG_HOST', os.environ.get('PGHOST', ''))
    if not host:
        return {'status': 'skip', 'detail': 'PG_HOST 미설정'}
    try:
        import shutil
        if not shutil.which('psql'):
            return {'status': 'fail', 'detail': 'psql not found'}
        db = os.environ.get('PG_DATABASE', os.environ.get('PGDATABASE', ''))
        user = os.environ.get('PG_USER', os.environ.get('PGUSER', ''))
        schema = os.environ.get('PG_SCHEMA', 'public')
        env = dict(os.environ, PGPASSWORD=os.environ.get('PG_PASSWORD', os.environ.get('PGPASSWORD', '')))

        def _query(sql):
            r = subprocess.run(
                ['psql', '-h', host, '-p', os.environ.get('PG_PORT', '5432'),
                 '-U', user, '-d', db, '-t', '-A', '-c', sql],
                capture_output=True, text=True, env=env, timeout=10)
            return r.stdout.strip()

        tables = int(_query(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{schema}'") or 0)
        functions = int(_query(f"SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema='{schema}'") or 0)
        sequences = int(_query(f"SELECT COUNT(*) FROM information_schema.sequences WHERE sequence_schema='{schema}'") or 0)

        return {
            'status': 'pass',
            'schema': schema,
            'tables': tables,
            'functions': functions,
            'sequences': sequences,
            'detail': f'{tables} tables, {functions} functions, {sequences} sequences',
        }
    except Exception as e:
        return {'status': 'fail', 'detail': str(e)[:100]}


def check_phase1_config(config_path):
    """migration-config.json 읽기."""
    for p in [config_path, 'migration-config.json', '../migration-config.json']:
        if p and Path(p).exists():
            try:
                config = json.loads(Path(p).read_text(encoding='utf-8'))
                phase1 = config.get('phase1', {})
                return {
                    'status': 'found',
                    'path': str(p),
                    'phase1_status': phase1.get('status', 'unknown'),
                    'project_name': config.get('project', {}).get('name', ''),
                    'config': config,
                }
            except Exception as e:
                return {'status': 'error', 'detail': str(e)[:100]}
    return {'status': 'not_found', 'detail': 'migration-config.json 없음 (Phase 1 미완료 또는 독립 실행)'}


def main():
    ap = argparse.ArgumentParser(description='Preflight environment check')
    ap.add_argument('--config', default=None, help='migration-config.json 경로')
    ap.add_argument('--output', default=None, help='결과 JSON 출력 경로')
    args = ap.parse_args()

    _load_dotenv()

    print("=== Preflight Check ===\n")

    results = {}

    # Phase 1 config
    cfg = check_phase1_config(args.config)
    results['phase1_config'] = cfg
    if cfg['status'] == 'found':
        print(f"✅ Phase 1: {cfg['phase1_status']} (프로젝트: {cfg['project_name']})")
    else:
        print(f"⚠️ Phase 1: {cfg['detail']}")

    # Oracle
    ora = check_oracle()
    results['oracle'] = ora
    icon = '✅' if ora['status'] == 'pass' else '⚠️' if ora['status'] == 'skip' else '❌'
    print(f"{icon} Oracle: {ora['detail']}")

    # PostgreSQL
    pg = check_pg()
    results['pg'] = pg
    icon = '✅' if pg['status'] == 'pass' else '⚠️' if pg['status'] == 'skip' else '❌'
    print(f"{icon} PostgreSQL: {pg['detail']}")
    if pg.get('tables', 0) == 0 and pg['status'] == 'pass':
        print(f"   ⚠️ PG 테이블 0개 — Phase 1 미완료 가능. DBA FAIL 다수 예상.")

    # DBA FAIL 사전 예측 (Phase 1 failed_objects)
    if cfg['status'] == 'found' and cfg.get('config'):
        failed = cfg['config'].get('phase1', {}).get('failed_objects', [])
        if failed:
            print(f"\n⚠️ Phase 1 실패 오브젝트 ({len(failed)}건) — Phase 2에서 DBA FAIL 예상:")
            for obj in failed[:10]:
                print(f"   {obj.get('type','?')}: {obj.get('name','?')} — {obj.get('reason','')}")

    # Output
    results['timestamp'] = datetime.now().isoformat()
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"\n결과 저장: {args.output}")

    print("\n=== Preflight Done ===")


if __name__ == '__main__':
    main()
