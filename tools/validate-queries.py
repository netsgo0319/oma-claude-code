#!/usr/bin/env python3
"""
Step 3: Query Validation Tool
Validates converted PostgreSQL queries using test-cases.json bind values.

Usage:
    # Generate SQL test scripts (for SSM or remote execution)
    python3 tools/validate-queries.py --generate --output workspace/results/_validation/

    # Execute EXPLAIN locally via psql (syntax check only)
    python3 tools/validate-queries.py --local --output workspace/results/_validation/

    # Execute queries locally via psql (actual execution with row counts)
    python3 tools/validate-queries.py --execute --output workspace/results/_validation/

    # Parse results from externally executed scripts
    python3 tools/validate-queries.py --parse-results workspace/results/_validation/

    # Compare Oracle vs PostgreSQL results (the core migration validation)
    python3 tools/validate-queries.py --compare --output workspace/results/_validation/

    # Use extracted SQL from mybatis-sql-extractor
    python3 tools/validate-queries.py --generate --extracted workspace/results/_extracted/ --output workspace/results/_validation/

    # Full atomic validation (generate + EXPLAIN + Execute + Oracle Compare + parse)
    python3 tools/validate-queries.py --full --output workspace/results/_validation/
"""

import xml.etree.ElementTree as ET
import json
import re
import os
import sys
import argparse
import subprocess
from pathlib import Path
from datetime import datetime


def _load_dotenv():
    """프로젝트 루트 또는 workspace/의 .env 파일을 자동 로드.
    서브에이전트가 source .env 없이 실행해도 환경변수가 설정되도록."""
    for env_path in ['.env', 'workspace/.env', '../.env']:
        p = Path(env_path)
        if p.exists():
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    # export KEY=VALUE 또는 KEY=VALUE
                    line = line.removeprefix('export').strip()
                    key, _, val = line.partition('=')
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:  # 기존 환경변수 우선
                        os.environ[key] = val


_load_dotenv()


class QueryValidator:
    def __init__(self, output_dir='workspace/output', results_dir='workspace/results',
                 input_dir='workspace/input'):
        self.output_dir = Path(output_dir)
        self.results_dir = Path(results_dir)
        self.input_dir = Path(input_dir)
        self.queries = []
        self.oracle_queries = {}  # {query_id: oracle_sql} from input XML
        self.test_cases = {}

    def _resolve_tracking_dirs(self, tracking_dir):
        """Resolve tracking directory paths. If 'auto', scan for all query-tracking.json files."""
        if tracking_dir == 'auto':
            dirs = []
            for qt in self.results_dir.glob('*/v*/query-tracking.json'):
                dirs.append(str(qt.parent))
            return dirs
        else:
            return [tracking_dir]

    def load_oracle_queries(self):
        """Load original Oracle SQL from input XML files and/or query-tracking.json."""
        # Method 1: From query-tracking.json (preferred — has oracle_sql field)
        for qt_file in self.results_dir.glob('*/v*/query-tracking.json'):
            try:
                with open(qt_file, 'r', encoding='utf-8') as f:
                    tracking = json.load(f)
                for q in tracking.get('queries', []):
                    qid = q.get('query_id', '')
                    oracle_sql = q.get('oracle_sql', '')
                    if qid and oracle_sql:
                        self.oracle_queries[qid] = oracle_sql
            except Exception:
                pass

        # Method 2: From input XML files (supplement — tracking에 없는 쿼리 보충)
        if self.input_dir.exists():
            for xml_file in sorted(self.input_dir.glob('**/*.xml')):
                try:
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                except (ET.ParseError, ValueError):
                    continue
                for tag in ['select', 'insert', 'update', 'delete']:
                    for elem in root.findall(f'.//{tag}'):
                        qid = elem.get('id', 'unknown')
                        parts = []
                        for text in elem.itertext():
                            parts.append(text.strip())
                        raw_sql = ' '.join(parts)
                        raw_sql = re.sub(r'--[^\n]*', '', raw_sql)
                        raw_sql = re.sub(r'\s+', ' ', raw_sql).strip()
                        if qid and raw_sql and qid not in self.oracle_queries:
                            self.oracle_queries[qid] = raw_sql

        print(f"Loaded {len(self.oracle_queries)} Oracle (original) queries")

    @staticmethod
    def _oracle_available():
        """Check if sqlplus and Oracle env vars are available."""
        import shutil
        if not shutil.which('sqlplus'):
            return False, "sqlplus not found"
        host = os.environ.get('ORACLE_HOST', '')
        if not host:
            return False, "ORACLE_HOST not set"
        return True, "OK"

    @staticmethod
    def _pg_available():
        """Check if psql and PG env vars are available."""
        import shutil
        if not shutil.which('psql'):
            return False, "psql not found"
        host = os.environ.get('PG_HOST', os.environ.get('PGHOST', ''))
        if not host:
            return False, "PG_HOST not set"
        return True, "OK"

    @staticmethod
    def _oracle_conn_str():
        """Build Oracle connection string. Supports SID and Service Name."""
        ora_user = os.environ.get('ORACLE_USER', '')
        ora_pass = os.environ.get('ORACLE_PASSWORD', '')
        ora_host = os.environ.get('ORACLE_HOST', '')
        ora_port = os.environ.get('ORACLE_PORT', '1521')
        ora_sid = os.environ.get('ORACLE_SID', '')
        # Service Name uses /service, SID uses :sid
        # Default: treat as Service Name (host:port/service) — most common for PDB
        conn_type = os.environ.get('ORACLE_CONN_TYPE', 'service')  # 'service' or 'sid'
        if conn_type == 'sid':
            return f"{ora_user}/{ora_pass}@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={ora_host})(PORT={ora_port}))(CONNECT_DATA=(SID={ora_sid})))"
        return f"{ora_user}/{ora_pass}@{ora_host}:{ora_port}/{ora_sid}"

    def _run_oracle_sql(self, sql, timeout=30):
        """Execute SQL on Oracle via sqlplus and return output."""
        conn_str = self._oracle_conn_str()
        sqlplus_input = f"""SET LINESIZE 32767
SET PAGESIZE 50000
SET FEEDBACK ON
SET HEADING ON
{sql}
"""
        try:
            result = subprocess.run(
                ['sqlplus', '-S', conn_str],
                input=sqlplus_input, capture_output=True, text=True, timeout=timeout
            )
            return result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return "ORA-TIMEOUT: query exceeded timeout"
        except Exception as e:
            return f"ORA-ERROR: {e}"

    def _run_pg_sql(self, sql, timeout=30):
        """Execute SQL on PostgreSQL via psql and return output."""
        pg_host = os.environ.get('PG_HOST', os.environ.get('PGHOST', ''))
        pg_port = os.environ.get('PG_PORT', os.environ.get('PGPORT', '5432'))
        pg_db = os.environ.get('PG_DATABASE', os.environ.get('PGDATABASE', ''))
        pg_user = os.environ.get('PG_USER', os.environ.get('PGUSER', ''))
        pg_pass = os.environ.get('PG_PASSWORD', os.environ.get('PGPASSWORD', ''))

        env = os.environ.copy()
        env['PGPASSWORD'] = pg_pass

        try:
            result = subprocess.run(
                ['psql', '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', pg_db,
                 '-c', f"SET statement_timeout = '{timeout}s'; {sql}"],
                capture_output=True, text=True, env=env, timeout=timeout + 5
            )
            return result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return "PG-TIMEOUT: query exceeded timeout"
        except Exception as e:
            return f"PG-ERROR: {e}"

    @staticmethod
    def _parse_row_count(output, db_type='pg'):
        """Extract row count from query output."""
        if db_type == 'pg':
            # PostgreSQL: "(N rows)" or "(N row)"
            m = re.search(r'\((\d+) (?:rows?|행)\)', output)
            if m:
                return int(m.group(1))
            # DML: "INSERT 0 N", "UPDATE N", "DELETE N"
            m = re.search(r'(?:INSERT \d+ |UPDATE |DELETE )(\d+)', output)
            if m:
                return int(m.group(1))
        elif db_type == 'oracle':
            # Oracle: "N rows selected" or "N row selected"
            m = re.search(r'(\d+) (?:rows? selected|행)', output)
            if m:
                return int(m.group(1))
            # DML: "1 row created", "N rows updated", "N rows deleted"
            m = re.search(r'(\d+) rows? (?:created|updated|deleted|inserted)', output)
            if m:
                return int(m.group(1))
        return None

    def compare_queries(self, output_dir, tracking_dir=None):
        """Execute queries on BOTH Oracle and PostgreSQL, compare results.
        This is the core migration validation: before/after must match."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        ora_ok, ora_msg = self._oracle_available()
        pg_ok, pg_msg = self._pg_available()

        if not ora_ok:
            print(f"ERROR: Oracle not available: {ora_msg}")
            print("--compare requires both Oracle and PostgreSQL connections")
            sys.exit(1)
        if not pg_ok:
            print(f"ERROR: PostgreSQL not available: {pg_msg}")
            sys.exit(1)

        print(f"Comparing Oracle vs PostgreSQL results...")
        print(f"  Oracle queries loaded: {len(self.oracle_queries)}")
        print(f"  PG queries loaded: {len(self.queries)}")
        print(f"  Test cases loaded: {sum(len(v) for v in self.test_cases.values())}")

        results = []
        pass_count = 0
        fail_count = 0
        warn_count = 0
        warnings = []

        for query in self.queries:
            qid = query['id']
            pg_sql = query['sql_raw']
            qtype = query['type']
            oracle_sql = self.oracle_queries.get(qid, '')
            is_extracted = query.get('from_extracted', False)
            param_names = query.get('param_names_for_bind', [])

            if not oracle_sql:
                print(f"  SKIP {qid}: no Oracle SQL found")
                continue

            # Use _select_best_tcs for better TC selection
            # filename::qid 키 우선, bare qid fallback
            file_key = f"{query.get('file', '')}::{qid}"
            all_cases = self.test_cases.get(file_key, self.test_cases.get(qid, []))
            selected = self._select_best_tcs(all_cases, max_tcs=2)
            if not selected:
                selected = [{'name': 'default', 'params': {}}]

            for i, case in enumerate(selected):
                if isinstance(case, dict):
                    binds = case.get('binds', case.get('params', {}))
                    for skip_key in ['name', 'description', 'source', 'case_id', 'not_null_columns', 'expected']:
                        binds.pop(skip_key, None) if isinstance(binds, dict) else None
                    case_name = case.get('name', case.get('case_id', f'tc{i}'))
                else:
                    binds = {}
                    case_name = f'tc{i}'

                # Bind params: extracted SQL uses ? positional, static uses #{param}
                if is_extracted and '?' in pg_sql:
                    bound_pg = self._bind_positional(pg_sql, param_names, binds)
                else:
                    bound_pg = self.bind_params(pg_sql, binds)
                bound_oracle = self.bind_params(oracle_sql, binds, default_unbound="'1'")

                # Wrap DML in transaction
                if qtype in ('insert', 'update', 'delete'):
                    exec_oracle = f"{bound_oracle.rstrip(';')};\nROLLBACK;"
                    exec_pg = f"BEGIN; {bound_pg.rstrip(';')}; ROLLBACK;"
                else:
                    # SELECT: add LIMIT for safety on PG side
                    safe_pg = bound_pg.rstrip(';')
                    if 'LIMIT' not in safe_pg.upper():
                        safe_pg += ' LIMIT 100'
                    exec_pg = safe_pg + ';'
                    # Oracle: add ROWNUM limit
                    safe_ora = bound_oracle.rstrip(';')
                    if 'ROWNUM' not in safe_ora.upper() and 'FETCH FIRST' not in safe_ora.upper():
                        exec_oracle = f"SELECT * FROM ({safe_ora}) WHERE ROWNUM <= 100;"
                    else:
                        exec_oracle = safe_ora + ';'

                # Execute both
                ora_output = self._run_oracle_sql(exec_oracle)
                pg_output = self._run_pg_sql(exec_pg)

                # Parse results
                ora_rows = self._parse_row_count(ora_output, 'oracle')
                pg_rows = self._parse_row_count(pg_output, 'pg')
                ora_error = bool(re.search(r'(^ORA-\d|^ERROR)', ora_output, re.MULTILINE))
                pg_error = bool(re.search(r'^ERROR:', pg_output, re.MULTILINE))

                # Determine status
                test_id = f"{query['file'].replace('.xml','')}.{qid}.{case_name}"
                result = {
                    'test_id': test_id,
                    'query_id': qid,
                    'type': qtype,
                    'case': case_name,
                    'oracle_rows': ora_rows,
                    'pg_rows': pg_rows,
                    'oracle_error': ora_output.strip()[:1000] if ora_error else None,
                    'pg_error': pg_output.strip()[:1000] if pg_error else None,
                    'match': False,
                    'status': 'fail',
                }

                if ora_error and pg_error:
                    result['status'] = 'fail'
                    result['reason'] = 'both_error'
                    fail_count += 1
                elif ora_error:
                    result['status'] = 'warn'
                    result['reason'] = 'oracle_error_only'
                    warn_count += 1
                elif pg_error:
                    result['status'] = 'fail'
                    result['reason'] = 'pg_error'
                    fail_count += 1
                elif ora_rows is not None and pg_rows is not None:
                    if ora_rows == pg_rows:
                        result['match'] = True
                        result['status'] = 'pass'
                        pass_count += 1
                    else:
                        result['status'] = 'fail'
                        result['reason'] = f'row_count_mismatch: oracle={ora_rows}, pg={pg_rows}'
                        fail_count += 1
                elif ora_rows is None and pg_rows is None:
                    # Both returned no parseable rows (possibly DDL or empty)
                    result['match'] = True
                    result['status'] = 'pass'
                    pass_count += 1
                else:
                    result['status'] = 'warn'
                    result['reason'] = 'row_count_unparseable'
                    warn_count += 1

                results.append(result)

                status_icon = {'pass': 'MATCH', 'fail': 'DIFF', 'warn': 'WARN'}[result['status']]
                print(f"  {status_icon} {test_id}: oracle={ora_rows} pg={pg_rows}")

                # Integrity Guard warnings
                if result['status'] == 'pass' and ora_rows == 0 and pg_rows == 0:
                    if qtype in ('insert', 'update', 'delete'):
                        # DML: 0 affected rows on both sides is normal (data may not exist)
                        warnings.append({
                            'code': 'WARN_ZERO_BOTH_DML',
                            'severity': 'low',
                            'query_id': qid,
                            'test_case': case_name,
                            'message': f'Both Oracle and PG affected 0 rows (DML - data may not exist)',
                        })
                    else:
                        warnings.append({
                            'code': 'WARN_ZERO_BOTH',
                            'severity': 'high',
                            'query_id': qid,
                            'test_case': case_name,
                            'message': 'Both Oracle and PG returned 0 rows',
                        })

        # Aggregated per-query guards
        query_results_agg = {}  # {qid: [match_booleans]}
        for r in results:
            query_results_agg.setdefault(r['query_id'], []).append(r)

        for qid, qresults in query_results_agg.items():
            ora_rows_list = [r['oracle_rows'] for r in qresults if r['oracle_rows'] is not None]
            pg_rows_list = [r['pg_rows'] for r in qresults if r['pg_rows'] is not None]
            if ora_rows_list and all(r == 0 for r in ora_rows_list) and all(r == 0 for r in pg_rows_list):
                warnings.append({
                    'code': 'WARN_ZERO_ALL_CASES',
                    'severity': 'critical',
                    'query_id': qid,
                    'message': f'All {len(ora_rows_list)} test cases returned 0 rows on both sides',
                })
            elif pg_rows_list and sum(r == 0 for r in pg_rows_list) > len(pg_rows_list) * 0.8:
                warnings.append({
                    'code': 'WARN_MOSTLY_ZERO',
                    'severity': 'high',
                    'query_id': qid,
                    'message': f'{sum(r==0 for r in pg_rows_list)}/{len(pg_rows_list)} PG test cases returned 0 rows',
                })

        # Summary
        total = pass_count + fail_count + warn_count
        print(f"\n=== Compare Results ===")
        print(f"MATCH: {pass_count}, DIFF: {fail_count}, WARN: {warn_count} (total {total})")

        if warnings:
            print(f"\nIntegrity Guard: {len(warnings)} warnings")
            for w in warnings[:10]:
                print(f"  [{w['severity'].upper()}] {w['code']}: {w['query_id']} - {w['message']}")

        # Update query-level tracking
        if tracking_dir:
            try:
                from tracking_utils import TrackingManager
                tracking_dirs = self._resolve_tracking_dirs(tracking_dir)
                for tdir in tracking_dirs:
                    tm = TrackingManager(tdir)
                    for r in results:
                        tm.update_test_case(
                            r['query_id'], r['case'],
                            binds={},
                            oracle_result={'rows': r['oracle_rows'], 'error': r.get('oracle_error')},
                            pg_result={'rows': r['pg_rows'], 'error': r.get('pg_error')},
                            match=r['match'],
                            warnings=[w['code'] for w in warnings if w.get('query_id') == r['query_id']]
                        )
                        if r['status'] == 'pass':
                            tm.mark_success(r['query_id'])
            except Exception as e:
                print(f"  Warning: Could not update tracking: {e}")

        # Write compare_validated.json
        validated = {
            'timestamp': datetime.now().isoformat(),
            'mode': 'compare',
            'total': total,
            'pass': pass_count,
            'fail': fail_count,
            'warn': warn_count,
            'pass_rate': f"{pass_count/total*100:.1f}%" if total > 0 else "N/A",
            'results': results,
            'warnings': warnings,
        }
        with open(output_path / 'compare_validated.json', 'w') as f:
            json.dump(validated, f, indent=2, ensure_ascii=False)

        # Auto-update progress.json
        try:
            from tracking_utils import TrackingManager
            TrackingManager.update_pipeline_phase(
                'workspace/progress.json', 'phase_3_compare', 'Oracle vs PG 비교', 'done',
                compare_match=pass_count, compare_fail=fail_count, compare_warn=warn_count)
        except Exception:
            pass

        # Activity log
        try:
            from tracking_utils import log_activity
            log_activity('STEP_END', agent='validate-queries', step='step_3_compare',
                         detail=f"Compare: {pass_count} match, {fail_count} fail, {warn_count} warn (total {total})")
        except Exception:
            pass

        print(f"\nSaved: {output_path / 'compare_validated.json'}")
        return validated

    def load_queries(self):
        """Discover query IDs and types from XML files. SQL comes from MyBatis engine."""
        for xml_file in sorted(self.output_dir.glob('**/*.xml')):
            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()
            except (ET.ParseError, ValueError):
                continue
            for tag in ['select', 'insert', 'update', 'delete']:
                for elem in root.findall(f'.//{tag}'):
                    qid = elem.get('id', 'unknown')
                    self.queries.append({
                        'file': xml_file.name,
                        'id': qid,
                        'type': tag,
                        'sql_raw': '',  # Will be filled by load_extracted()
                        'params': [],
                    })
        print(f"Discovered {len(self.queries)} query IDs from {len(list(self.output_dir.glob('**/*.xml')))} files")

    def _supplement_static_queries(self, extracted_qids_by_file):
        """Add static XML queries for IDs not covered by MyBatis extraction.
        These queries have #{param} placeholders (not ?) and use the FALLBACK PATH.
        Resolves <include refid="..."/> by looking up <sql id="..."> fragments."""
        added = 0
        for xml_file in sorted(self.output_dir.glob('**/*.xml')):
            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()
            except (ET.ParseError, ValueError):
                continue
            # Build sql fragment map for <include refid="..."/> resolution
            sql_fragments = {}
            for sql_elem in root.findall('.//{http://mybatis.org/dtd/mybatis-3-mapper.dtd}sql'):
                fid = sql_elem.get('id', '')
                if fid:
                    sql_fragments[fid] = sql_elem
            for sql_elem in root.findall('.//sql'):
                fid = sql_elem.get('id', '')
                if fid:
                    sql_fragments[fid] = sql_elem

            for tag in ['select', 'insert', 'update', 'delete']:
                for elem in root.findall(f'.//{tag}'):
                    qid = elem.get('id', 'unknown')
                    key = (xml_file.name, qid)
                    if key not in extracted_qids_by_file:
                        sql_text = self._extract_sql_text(elem, sql_fragments)
                        if sql_text and sql_text.strip():
                            self.queries.append({
                                'file': xml_file.name,
                                'id': qid,
                                'type': tag,
                                'sql_raw': sql_text,
                                'params': [],
                            })
                            added += 1
        return added

    @staticmethod
    def _extract_sql_text(elem, sql_fragments=None):
        """Extract SQL text from an XML element, resolving <include refid> and stripping MyBatis tags."""
        if sql_fragments is None:
            sql_fragments = {}
        parts = []
        if elem.text:
            parts.append(elem.text)
        for child in elem:
            if child.tag == 'include':
                refid = child.get('refid', '')
                if refid and refid in sql_fragments:
                    frag_sql = QueryValidator._extract_sql_text(sql_fragments[refid], sql_fragments)
                    parts.append(frag_sql)
            else:
                if child.text:
                    parts.append(child.text)
                for sub in child.iter():
                    if sub is not child:
                        if sub.tag == 'include':
                            refid = sub.get('refid', '')
                            if refid and refid in sql_fragments:
                                frag_sql = QueryValidator._extract_sql_text(sql_fragments[refid], sql_fragments)
                                parts.append(frag_sql)
                        else:
                            if sub.text:
                                parts.append(sub.text)
                            if sub.tail:
                                parts.append(sub.tail)
            if child.tail:
                parts.append(child.tail)
        return ' '.join(parts)

    @staticmethod
    def _select_best_tcs(tc_cases, max_tcs=2):
        """Select best test cases prioritizing CUSTOM > SAMPLE > INFERRED > null/fallback."""
        if not tc_cases:
            return []
        priority_map = {'CUSTOM': 0, 'SAMPLE_DATA': 1, 'SAMPLE': 1, 'INFERRED': 2}
        buckets = {0: [], 1: [], 2: [], 9: []}
        for tc in tc_cases:
            if not isinstance(tc, dict):
                continue
            source = str(tc.get('source', tc.get('name', ''))).upper()
            params = tc.get('params', tc.get('binds', {}))
            if isinstance(params, dict) and params:
                if sum(1 for v in params.values() if v is not None) == 0:
                    buckets[9].append(tc)
                    continue
            matched = False
            for key, pri in priority_map.items():
                if key in source:
                    buckets[pri].append(tc)
                    matched = True
                    break
            if not matched:
                name = str(tc.get('name', '')).lower()
                buckets[9 if 'null' in name else 2].append(tc)
        result = []
        for pri in [0, 1, 2, 9]:
            for tc in buckets[pri]:
                if len(result) >= max_tcs:
                    break
                result.append(tc)
            if len(result) >= max_tcs:
                break
        return result

    def load_extracted(self, extracted_dir):
        """Load SQL from mybatis-sql-extractor JSON output (Phase 3.5).
        This provides accurate SQL with dynamic branches resolved by the MyBatis engine."""
        extracted_path = Path(extracted_dir)
        if not extracted_path.exists():
            print(f"ERROR: Extracted directory not found: {extracted_dir}")
            return

        json_files = sorted(extracted_path.glob('*-extracted.json'))
        if not json_files:
            print(f"WARNING: No extracted JSON files in {extracted_dir}")
            print(f"  → run-extractor.sh를 먼저 실행하세요. 없이 진행하면 동적 SQL Compare 실패.")
            return

        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if 'error' in data and 'queries' not in data:
                    print(f"  SKIP {json_file.name}: extraction error")
                    continue

                source_file = data.get('source_file', json_file.stem.replace('-extracted', '.xml'))
                queries_data = data.get('queries', [])

                # param_names for TC binding (from BoundSql.getParameterMappings)
                query_param_names = {}
                for q in queries_data:
                    qid = q.get('query_id', 'unknown')
                    pnames = q.get('param_names', [])
                    if pnames:
                        query_param_names[qid] = pnames

                for q in queries_data:
                    qid = q.get('query_id', 'unknown')
                    qtype = q.get('type', 'select')

                    # Collect unique SQL variants
                    seen_sql = set()
                    variants = q.get('sql_variants', [])
                    param_names = query_param_names.get(qid, [])

                    for variant in variants:
                        sql = variant.get('sql', '')
                        if not sql or 'error' in variant:
                            continue
                        if sql in seen_sql:
                            continue
                        seen_sql.add(sql)

                        # Also get per-variant param_mappings if available
                        v_params = [pm.get('property', '') for pm in variant.get('parameter_mappings', [])]
                        effective_params = v_params or param_names

                        variant_name = variant.get('params', 'default')
                        self.queries.append({
                            'file': source_file,
                            'id': qid,
                            'type': qtype,
                            'sql_raw': sql,
                            'params': effective_params,
                            'variant': variant_name,
                            'from_extracted': True,
                            'param_names_for_bind': effective_params,
                        })

            except (json.JSONDecodeError, Exception) as e:
                print(f"  WARN: Error loading {json_file}: {e}")

        print(f"Loaded {len(self.queries)} unique SQL variants from extracted JSON")

    def load_test_cases(self):
        """Load test cases from per-file test-cases.json AND merged-tc.json."""
        # 1. Per-file test-cases.json (results/*/v*/test-cases.json)
        found_files = list(self.results_dir.glob('*/v*/test-cases.json'))
        if not found_files:
            found_files = list(self.results_dir.glob('*/test-cases.json'))

        # 2. merged-tc.json (pipeline 모드 또는 workspace 모드)
        merged_paths = [
            self.results_dir / '_test-cases' / 'merged-tc.json',
            Path('pipeline/step-2-tc-generate/output/merged-tc.json'),
        ]
        for mp in merged_paths:
            if mp.exists():
                try:
                    with open(mp, encoding='utf-8') as _f:
                        merged = json.load(_f)
                    if isinstance(merged, dict):
                        loaded = 0
                        for qid, cases in merged.items():
                            if isinstance(cases, list) and qid not in self.test_cases:
                                # merged-tc는 [{params}, {params}] 형태 — TC 객체로 변환
                                tc_list = []
                                for i, c in enumerate(cases):
                                    if isinstance(c, dict):
                                        tc_list.append({
                                            'name': f'merged_{i}',
                                            'params': c if 'params' not in c else c['params'],
                                            'source': c.get('source', 'MERGED'),
                                        })
                                if tc_list:
                                    self.test_cases[qid] = tc_list
                                    loaded += 1
                        if loaded:
                            print(f"  Loaded {loaded} queries from {mp}")
                except Exception as e:
                    print(f"  WARN: Failed to load {mp}: {e}")
                break

        if not found_files and not self.test_cases:
            print(f"  No test-cases.json found under {self.results_dir}")
            return

        for tc_file in found_files:
            try:
                with open(tc_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                loaded_before = len(self.test_cases)

                # Handle different structures
                if isinstance(data, dict):
                    # Structure 1: {query_test_cases: [...]} or {test_cases: [...]}
                    cases = data.get('query_test_cases', data.get('test_cases', None))

                    if cases is None:
                        # Structure 2: top-level keys are query IDs directly
                        # e.g. {"selectUser": [{binds: ...}], "insertUser": [{binds: ...}]}
                        for key, val in data.items():
                            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                                # Check if it looks like test cases (has binds or params)
                                if any(k in val[0] for k in ('binds', 'params', 'case_id', 'description')):
                                    self.test_cases[key] = val

                    elif isinstance(cases, dict):
                        # Structure 3: {query_test_cases: {queryId: [...cases]}}
                        for qid, tcs in cases.items():
                            if isinstance(tcs, list):
                                self.test_cases[qid] = tcs
                            elif isinstance(tcs, dict) and 'test_cases' in tcs:
                                self.test_cases[qid] = tcs['test_cases']

                    elif isinstance(cases, list):
                        for tc in cases:
                            if isinstance(tc, dict):
                                qid = tc.get('query_id', '')
                                if qid:
                                    tcs = tc.get('test_cases', [tc])
                                    self.test_cases[qid] = tcs

                elif isinstance(data, list):
                    for tc in data:
                        if isinstance(tc, dict):
                            qid = tc.get('query_id', '')
                            if qid:
                                self.test_cases[qid] = tc.get('test_cases', [tc])

                loaded_after = len(self.test_cases)
                loaded_count = loaded_after - loaded_before
                if loaded_count > 0:
                    print(f"  Loaded from {tc_file}: {loaded_count} queries")
                else:
                    # Debug: show structure to help diagnose
                    if isinstance(data, dict):
                        keys = list(data.keys())[:5]
                        print(f"  WARN: {tc_file} loaded but 0 queries matched. Top keys: {keys}")
                    elif isinstance(data, list):
                        print(f"  WARN: {tc_file} is list with {len(data)} items but 0 queries matched")

            except (json.JSONDecodeError, Exception) as e:
                print(f"  WARN: Error loading {tc_file}: {e}")

        total_cases = sum(len(v) for v in self.test_cases.values())
        print(f"Loaded {total_cases} test cases for {len(self.test_cases)} queries")

    def bind_params(self, sql, params_dict, default_unbound='NULL'):
        """Replace #{param} with actual values from test case.
        default_unbound: value for unbound params ('NULL' or "'1'" to match PG fallback)."""
        result = sql
        for key, value in params_dict.items():
            pattern = rf'#\{{{key}(?:,[^}}]*)?\}}'
            if value is None:
                replacement = 'NULL'
            elif isinstance(value, bool):
                replacement = 'TRUE' if value else 'FALSE'
            elif isinstance(value, (int, float)):
                replacement = str(value)
            elif isinstance(value, str):
                safe_value = value.replace("'", "''")
                replacement = f"'{safe_value}'"
            elif isinstance(value, list):
                # For foreach - join as comma-separated
                items = ', '.join(f"'{v}'" if isinstance(v, str) else str(v) for v in value)
                replacement = items
            else:
                replacement = f"'{value}'"
            result = re.sub(pattern, replacement, result)

        # Replace any remaining unbound params with default_unbound
        # Framework pagination params (GRIDPAGING_*) must be empty string
        def _unbound_replace(m):
            pname = m.group(0)[2:-1].split(',')[0].lower()
            if 'gridpaging' in pname:
                return ''
            return default_unbound
        result = re.sub(r'#\{[^}]+\}', _unbound_replace, result)
        # Replace ${} dollar substitution with placeholder
        result = re.sub(r'\$\{[^}]+\}', "placeholder_tbl", result)

        return result

    @staticmethod
    def _bind_positional(sql, param_names, binds):
        """Replace ? placeholders positionally using param_names + binds dict."""
        parts = sql.split('?')
        bound_parts = [parts[0]]
        for i in range(1, len(parts)):
            pname = param_names[i-1] if i-1 < len(param_names) else ''
            val = binds.get(pname) if pname else None
            if val is None:
                bound_parts.append("'1'")
            elif isinstance(val, (int, float)):
                bound_parts.append(str(val))
            elif isinstance(val, str):
                bound_parts.append(f"'{val.replace(chr(39), chr(39)+chr(39))}'")
            else:
                bound_parts.append("'1'")
            bound_parts.append(parts[i])
        return ''.join(bound_parts)

    @staticmethod
    def _extract_dml_where(sql):
        """DML에서 SELECT COUNT(*)로 변환하여 양쪽 비교 가능하게.
        UPDATE T SET col=1 WHERE id=1 → SELECT * FROM T WHERE id=1
        DELETE FROM T WHERE id=1 → SELECT * FROM T WHERE id=1
        INSERT INTO T (cols) VALUES (...) → SELECT 1 (건수 1 비교)
        UPDATE T SET col=1 (WHERE 없음) → SELECT COUNT(*) FROM T (전체 건수)"""
        flat = re.sub(r'\s+', ' ', sql).strip().rstrip(';')
        # UPDATE table SET ... WHERE ...
        # WHERE 추출 시 마지막 WHERE를 사용 (SET 안 서브쿼리의 WHERE와 구분)
        m = re.match(r'UPDATE\s+(\S+)\s+', flat, re.IGNORECASE)
        if m:
            table = m.group(1)
            # 마지막 WHERE 절 찾기 (SET 내부 서브쿼리 WHERE 제외)
            where_idx = flat.upper().rfind(' WHERE ')
            set_idx = flat.upper().find(' SET ')
            if where_idx > set_idx and where_idx > 0:
                where_clause = flat[where_idx:]
                return f"SELECT * FROM {table} {where_clause}"
            else:
                # WHERE 없는 UPDATE → 전체 건수 비교
                return f"SELECT COUNT(*) FROM {table}"
        # DELETE FROM table WHERE ...
        m = re.match(r'DELETE\s+(?:FROM\s+)?(\S+)\s+(WHERE\s+.+)$', flat, re.IGNORECASE)
        if m:
            return f"SELECT * FROM {m.group(1)} {m.group(2)}"
        m = re.match(r'DELETE\s+(?:FROM\s+)?(\S+)\s*$', flat, re.IGNORECASE)
        if m:
            return f"SELECT COUNT(*) FROM {m.group(1)}"
        # INSERT — VALUES 건수 비교 (양쪽 동일하면 1)
        if flat.upper().startswith('INSERT'):
            return "SELECT 1"
        return None

    @staticmethod
    def _flatten_sql(sql):
        """Flatten multi-line SQL to single line for sqlplus compatibility.
        sqlplus treats newlines as command terminators, causing SP2-0734 errors."""
        return re.sub(r'\s+', ' ', sql).strip()

    def generate_scripts(self, output_dir):
        """Generate SQL test scripts for remote execution.
        Generates: explain_test.sql (PG), execute_test.sql (PG), oracle_compare.sql (Oracle)"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        all_tests = []
        # PG search_path 설정 — $user가 스키마명과 다를 수 있으므로 명시적 설정 필수
        pg_schema = os.environ.get('PG_SCHEMA', '')
        search_path_line = f"SET search_path TO {pg_schema}, public;" if pg_schema else ""
        explain_lines = ["\\set ON_ERROR_STOP off", ""]
        execute_lines = ["\\set ON_ERROR_STOP off", ""]
        if search_path_line:
            explain_lines.append(search_path_line)
            explain_lines.append("")
            execute_lines.append(search_path_line)
            execute_lines.append("")
        # Oracle compare script (sqlplus format)
        ora_schema = os.environ.get('ORACLE_SCHEMA', '')
        oracle_lines = [
            "SET PAGESIZE 0", "SET FEEDBACK ON", "SET HEADING ON",
            "SET LINESIZE 32767", "SET TRIMSPOOL ON",
        ]
        if ora_schema:
            oracle_lines.append(f"ALTER SESSION SET CURRENT_SCHEMA = {ora_schema};")
        oracle_lines.append("")

        for query in self.queries:
            qid = query['id']
            fname = query['file'].replace('.xml', '')
            sql = query['sql_raw']
            qtype = query['type']
            is_extracted = query.get('from_extracted', False)
            variant_name = query.get('variant', '')

            # MAIN PATH: Extracted SQL from MyBatis engine (has ? placeholders)
            if is_extracted:
                param_names = query.get('param_names_for_bind', [])
                tc_binds = {}
                # Always try to find TC values — even without param_names
                tc_file_key = f"{query.get('file', '')}::{qid}"
                tc_cases = self.test_cases.get(tc_file_key, self.test_cases.get(qid, []))
                best_tcs = self._select_best_tcs(tc_cases, max_tcs=1)
                if best_tcs:
                    tc_binds = best_tcs[0].get('params', best_tcs[0].get('binds', {}))

                # Replace ? with TC values positionally
                parts = sql.split('?')
                placeholder_count = len(parts) - 1
                if param_names and len(param_names) != placeholder_count:
                    print(f"  WARN: {qid} param_names({len(param_names)}) != placeholders({placeholder_count})")
                bound_parts = [parts[0]]
                for i in range(1, len(parts)):
                    pname = param_names[i-1] if i-1 < len(param_names) else ''
                    val = tc_binds.get(pname)
                    if val is None:
                        # GRIDPAGING params → empty (pagination wrapper)
                        if 'gridpaging' in pname.lower():
                            bound_parts.append('')
                        else:
                            bound_parts.append("'1'")  # fallback
                    elif isinstance(val, (int, float)):
                        bound_parts.append(str(val))
                    elif isinstance(val, str):
                        bound_parts.append(f"'{val.replace(chr(39), chr(39)+chr(39))}'")
                    else:
                        bound_parts.append("'1'")
                    bound_parts.append(parts[i])
                bound_sql = ''.join(bound_parts)
                test_id = f"{fname}.{qid}.{variant_name}" if variant_name else f"{fname}.{qid}.default"
                all_tests.append({
                    'test_id': test_id,
                    'file': query['file'],
                    'query_id': qid,
                    'type': qtype,
                    'case': variant_name or 'extracted',
                    'bound_sql': bound_sql,
                    'from_extracted': True,
                })

                explain_lines.append(f"\\echo === {test_id} ===")
                explain_lines.append(f"EXPLAIN {bound_sql.rstrip(';')};")
                explain_lines.append("")

                # Execute: SELECT → COUNT(*), DML → COUNT(*) WHERE (양쪽 대칭)
                execute_lines.append(f"\\echo === {test_id} ===")
                if qtype == 'select':
                    safe_sql = bound_sql.rstrip(';')
                    execute_lines.append(f"SET statement_timeout = '30s';")
                    execute_lines.append(f"SELECT COUNT(*) FROM ({safe_sql}) AS _cnt;")
                else:
                    dml_where_pg = self._extract_dml_where(bound_sql)
                    if dml_where_pg:
                        execute_lines.append(f"SET statement_timeout = '5s';")
                        execute_lines.append(f"SELECT COUNT(*) FROM ({dml_where_pg}) AS _cnt;")
                    else:
                        execute_lines.append(f"\\echo SKIP_DML: {test_id} (no WHERE clause)")
                execute_lines.append("")

                # Oracle compare — 동일 로직 (SELECT: COUNT, DML: COUNT WHERE)
                oracle_sql = self.oracle_queries.get(qid, '')
                if oracle_sql:
                    ora_bound = self._flatten_sql(self.bind_params(oracle_sql, tc_binds, default_unbound="'1'"))
                    oracle_lines.append(f"PROMPT === {test_id} ===")
                    if qtype == 'select':
                        safe_ora = ora_bound.rstrip(';')
                        oracle_lines.append(f"SELECT COUNT(*) FROM ({safe_ora});")
                    else:
                        dml_where = self._extract_dml_where(ora_bound)
                        if dml_where:
                            oracle_lines.append(f"SELECT COUNT(*) AS affected_rows FROM ({dml_where});")
                        else:
                            oracle_lines.append(f"PROMPT SKIP_DML: {test_id} (no WHERE clause extractable)")
                    oracle_lines.append("")

                continue

            # FALLBACK PATH: Static XML extraction (no MyBatis engine)
            # This path has limited accuracy — dynamic tags are not resolved
            if not sql:
                print(f"  WARN: {qid} has no SQL (static fallback). Skipping.")
                continue

            print(f"  WARN: {qid} using static extraction (limited accuracy)")

            # Get test cases for this query (filename::qid 우선)
            static_file_key = f"{query.get('file', '')}::{qid}"
            cases = self.test_cases.get(static_file_key, self.test_cases.get(qid, []))

            if not cases:
                # No test cases - use default dummy binding
                # Framework pagination params (GRIDPAGING_*) must be empty string
                def _dummy_bind(m):
                    pname = m.group(0)[2:-1].split(',')[0].lower()
                    if 'gridpaging' in pname:
                        return ''
                    return "'1'"
                bound_sql = re.sub(r'#\{[^}]+\}', _dummy_bind, sql)
                bound_sql = re.sub(r'\$\{[^}]+\}', "placeholder_tbl", bound_sql)

                test_id = f"{fname}.{qid}.default"
                all_tests.append({
                    'test_id': test_id,
                    'file': query['file'],
                    'query_id': qid,
                    'type': qtype,
                    'case': 'default',
                    'bound_sql': bound_sql,
                })

                # EXPLAIN (always)
                explain_lines.append(f"\\echo === {test_id} ===")
                explain_lines.append(f"EXPLAIN {bound_sql.rstrip(';')};")
                explain_lines.append("")

                # EXECUTE: SELECT → COUNT(*), DML → COUNT(*) WHERE
                execute_lines.append(f"\\echo === {test_id} ===")
                if qtype == 'select':
                    safe_sql = bound_sql.rstrip(';')
                    execute_lines.append(f"SET statement_timeout = '30s';")
                    execute_lines.append(f"SELECT COUNT(*) FROM ({safe_sql}) AS _cnt;")
                else:
                    dml_where_pg = self._extract_dml_where(bound_sql)
                    if dml_where_pg:
                        execute_lines.append(f"SET statement_timeout = '5s';")
                        execute_lines.append(f"SELECT COUNT(*) FROM ({dml_where_pg}) AS _cnt;")
                    else:
                        execute_lines.append(f"\\echo SKIP_DML: {test_id} (no WHERE clause)")
                execute_lines.append("")

                # Oracle compare (use original SQL with same binds)
                oracle_sql = self.oracle_queries.get(qid, '')
                if oracle_sql:
                    ora_bound = self._flatten_sql(self.bind_params(oracle_sql, {}, default_unbound="'1'"))
                    oracle_lines.append(f"PROMPT === {test_id} ===")
                    if qtype == 'select':
                        safe_ora = ora_bound.rstrip(';')
                        oracle_lines.append(f"SELECT COUNT(*) FROM ({safe_ora});")
                    else:
                        dml_where = self._extract_dml_where(ora_bound)
                        if dml_where:
                            oracle_lines.append(f"SELECT COUNT(*) AS affected_rows FROM ({dml_where});")
                        else:
                            oracle_lines.append(f"PROMPT SKIP_DML: {test_id} (no WHERE clause extractable)")
                    oracle_lines.append("")

            else:
                for i, case in enumerate(cases):
                    # Extract bind values
                    binds = {}
                    if isinstance(case, dict):
                        binds = case.get('binds', case.get('params', case))
                        # Remove non-param keys
                        for skip_key in ['name', 'description', 'source', 'case_id', 'not_null_columns', 'expected']:
                            binds.pop(skip_key, None)

                    case_name = case.get('name', case.get('case_id', f'tc{i}')) if isinstance(case, dict) else f'tc{i}'
                    execute_skip = case.get('execute_skip', False) if isinstance(case, dict) else False
                    skip_reason = case.get('skip_reason', '') if isinstance(case, dict) else ''
                    bound_sql = self.bind_params(sql, binds)

                    test_id = f"{fname}.{qid}.{case_name}"
                    all_tests.append({
                        'test_id': test_id,
                        'file': query['file'],
                        'query_id': qid,
                        'type': qtype,
                        'case': case_name,
                        'binds': binds,
                        'bound_sql': bound_sql,
                        'execute_skip': execute_skip,
                    })

                    # EXPLAIN (always -- even for skipped DML, syntax check is safe)
                    explain_lines.append(f"\\echo === {test_id} ===")
                    explain_lines.append(f"EXPLAIN {bound_sql.rstrip(';')};")
                    explain_lines.append("")

                    # EXECUTE -- skip if marked dangerous (large table DML)
                    if execute_skip:
                        execute_lines.append(f"\\echo === {test_id} ===")
                        execute_lines.append(f"\\echo SKIPPED: {skip_reason}")
                        execute_lines.append("")
                    elif qtype == 'select':
                        safe_sql = bound_sql.rstrip(';')
                        execute_lines.append(f"\\echo === {test_id} ===")
                        execute_lines.append(f"SET statement_timeout = '30s';")
                        execute_lines.append(f"SELECT COUNT(*) FROM ({safe_sql}) AS _cnt;")
                        execute_lines.append("")
                    else:
                        # DML: COUNT(*) WHERE로 영향 행수 예측 (Oracle과 대칭)
                        execute_lines.append(f"\\echo === {test_id} ===")
                        dml_where_pg = self._extract_dml_where(bound_sql)
                        if dml_where_pg:
                            execute_lines.append(f"SET statement_timeout = '5s';")
                            execute_lines.append(f"SELECT COUNT(*) FROM ({dml_where_pg}) AS _cnt;")
                        else:
                            execute_lines.append(f"\\echo SKIP_DML: {test_id} (no WHERE clause)")
                        execute_lines.append("")

                    # Oracle compare
                    oracle_sql = self.oracle_queries.get(qid, '')
                    if oracle_sql:
                        ora_bound = self._flatten_sql(self.bind_params(oracle_sql, binds, default_unbound="'1'"))
                        oracle_lines.append(f"PROMPT === {test_id} ===")
                        if qtype == 'select':
                            safe_ora = ora_bound.rstrip(';')
                            oracle_lines.append(f"SELECT COUNT(*) FROM ({safe_ora});")
                        else:
                            dml_where = self._extract_dml_where(ora_bound)
                            if dml_where:
                                oracle_lines.append(f"SELECT COUNT(*) AS affected_rows FROM ({dml_where});")
                            else:
                                oracle_lines.append(f"PROMPT SKIP_DML: {test_id} (no WHERE clause extractable)")
                        oracle_lines.append("")

        # Write Oracle compare script
        oracle_lines.append("EXIT;")
        with open(output_path / 'oracle_compare.sql', 'w', encoding='utf-8') as f:
            f.write('\n'.join(oracle_lines))

        # Write scripts
        with open(output_path / 'explain_test.sql', 'w', encoding='utf-8') as f:
            f.write('\n'.join(explain_lines))

        with open(output_path / 'execute_test.sql', 'w', encoding='utf-8') as f:
            f.write('\n'.join(execute_lines))

        # Write test manifest
        # Write test manifest (lightweight — bound_sql excluded to save space)
        manifest_tests = [{k: v for k, v in t.items() if k != 'bound_sql'} for t in all_tests]
        with open(output_path / 'test_manifest.json', 'w', encoding='utf-8') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'total_tests': len(all_tests),
                'tests': manifest_tests,
            }, f, indent=2, ensure_ascii=False)

        # Split into batches for SSM (max ~50KB per batch)
        batch_size = 10
        batch_dir = output_path / 'batches'
        batch_dir.mkdir(exist_ok=True)

        import base64
        explain_tests = [t for t in all_tests]
        for bi in range(0, len(explain_tests), batch_size):
            batch = explain_tests[bi:bi+batch_size]
            lines = ["\\set ON_ERROR_STOP off"]
            for t in batch:
                lines.append(f"\\echo === {t['test_id']} ===")
                lines.append(f"EXPLAIN {t['bound_sql'].rstrip(';')};")
                lines.append("")
            idx = bi // batch_size
            b64 = base64.b64encode('\n'.join(lines).encode()).decode()
            with open(batch_dir / f'explain_batch_{idx}.b64', 'w') as f:
                f.write(b64)

        total_batches = (len(explain_tests) + batch_size - 1) // batch_size
        print(f"\nGenerated:")
        print(f"  {len(all_tests)} test cases")
        print(f"  {output_path / 'explain_test.sql'} ({len(explain_lines)} lines)")
        print(f"  {output_path / 'execute_test.sql'} ({len(execute_lines)} lines)")
        print(f"  {output_path / 'oracle_compare.sql'} ({len(oracle_lines)} lines)")
        print(f"  {output_path / 'test_manifest.json'}")
        print(f"  {total_batches} SSM batches in {batch_dir}/")

        return all_tests

    def execute_local(self, output_dir, tracking_dir=None):
        """Execute validation locally via psql."""
        output_path = Path(output_dir)

        # Check env vars
        pg_host = os.environ.get('PG_HOST', os.environ.get('PGHOST', ''))
        pg_port = os.environ.get('PG_PORT', os.environ.get('PGPORT', '5432'))
        pg_db = os.environ.get('PG_DATABASE', os.environ.get('PGDATABASE', ''))
        pg_user = os.environ.get('PG_USER', os.environ.get('PGUSER', ''))
        pg_pass = os.environ.get('PG_PASSWORD', os.environ.get('PGPASSWORD', ''))

        if not pg_host or not pg_db:
            print("ERROR: PG_HOST and PG_DATABASE (or PGHOST/PGDATABASE) must be set")
            print("Set environment variables or use --generate for remote execution")
            sys.exit(1)

        explain_sql = output_path / 'explain_test.sql'
        if not explain_sql.exists():
            print("ERROR: Run --generate first")
            sys.exit(1)

        print(f"Executing EXPLAIN tests against {pg_host}:{pg_port}/{pg_db}...")

        env = os.environ.copy()
        env['PGPASSWORD'] = pg_pass

        result = subprocess.run(
            ['psql', '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', pg_db,
             '-f', str(explain_sql)],
            capture_output=True, text=True, env=env, timeout=300
        )

        # Parse results
        output = result.stdout + result.stderr
        results_path = output_path / 'explain_results.txt'
        with open(results_path, 'w') as f:
            f.write(output)

        # Count PASS/FAIL
        pass_count = 0
        fail_count = 0
        failures = []
        current_test = None

        for line in output.split('\n'):
            if line.startswith('=== '):
                current_test = line.strip('= ')
            elif 'ERROR' in line and current_test:
                fail_count += 1
                failures.append({'test': current_test, 'error': line.strip()})
                current_test = None
            elif 'QUERY PLAN' in line and current_test:
                pass_count += 1
                current_test = None

        print(f"\nResults: PASS={pass_count}, FAIL={fail_count}")
        if failures:
            print("\nFailures:")
            for f in failures[:20]:
                print(f"  {f['test']}: {f['error']}")

        # Update query-level tracking (EXPLAIN results)
        if tracking_dir:
            try:
                from tracking_utils import TrackingManager
                tracking_dirs = self._resolve_tracking_dirs(tracking_dir)
                # Build per-query explain results: collect pass/fail per query_id
                explain_results = {}  # {query_id: {'status': 'pass'/'fail', 'error': ...}}
                # Track passes from output
                current_test = None
                for line in output.split('\n'):
                    if line.startswith('=== '):
                        current_test = line.strip('= ').strip()
                    elif 'ERROR' in line and current_test:
                        parts = current_test.split('.')
                        if len(parts) >= 2:
                            qid = parts[1]
                            explain_results[qid] = {'status': 'fail', 'error': line.strip()}
                        current_test = None
                    elif 'QUERY PLAN' in line and current_test:
                        parts = current_test.split('.')
                        if len(parts) >= 2:
                            qid = parts[1]
                            if qid not in explain_results or explain_results[qid]['status'] != 'fail':
                                explain_results[qid] = {'status': 'pass', 'plan_summary': line.strip()}
                        current_test = None

                for tdir in tracking_dirs:
                    tm = TrackingManager(tdir)
                    for qid, res in explain_results.items():
                        tm.update_explain(
                            qid, res['status'],
                            plan_summary=res.get('plan_summary'),
                            error=res.get('error')
                        )
                tracked_count = len(explain_results)
                if tracked_count:
                    print(f"  Query tracking (EXPLAIN): {tracked_count} queries updated")
            except Exception as e:
                print(f"  Warning: Could not update query tracking: {e}")

        # Write validated.json
        validated = {
            'timestamp': datetime.now().isoformat(),
            'total': pass_count + fail_count,
            'pass': pass_count,
            'fail': fail_count,
            'failures': failures,
        }
        with open(output_path / 'validated.json', 'w') as f:
            json.dump(validated, f, indent=2, ensure_ascii=False)

        # Auto-update progress.json
        try:
            from tracking_utils import TrackingManager
            TrackingManager.update_pipeline_phase(
                'workspace/progress.json', 'phase_3', '검증', 'done',
                explain_pass=pass_count, explain_fail=fail_count)
        except Exception:
            pass

        # Activity log
        try:
            from tracking_utils import log_activity
            log_activity('STEP_END', agent='validate-queries', step='step_3_explain',
                         detail=f"EXPLAIN: {pass_count} pass, {fail_count} fail")
        except Exception:
            pass

        return validated

    def execute_local_queries(self, output_dir, tracking_dir=None):
        """Execute queries locally via psql (actual execution, not just EXPLAIN)."""
        output_path = Path(output_dir)

        # Check env vars
        pg_host = os.environ.get('PG_HOST', os.environ.get('PGHOST', ''))
        pg_port = os.environ.get('PG_PORT', os.environ.get('PGPORT', '5432'))
        pg_db = os.environ.get('PG_DATABASE', os.environ.get('PGDATABASE', ''))
        pg_user = os.environ.get('PG_USER', os.environ.get('PGUSER', ''))
        pg_pass = os.environ.get('PG_PASSWORD', os.environ.get('PGPASSWORD', ''))

        if not pg_host or not pg_db:
            print("ERROR: PG_HOST and PG_DATABASE (or PGHOST/PGDATABASE) must be set")
            print("Set environment variables or use --generate for remote execution")
            sys.exit(1)

        execute_sql = output_path / 'execute_test.sql'
        if not execute_sql.exists():
            print("ERROR: Run --generate first to create execute_test.sql")
            sys.exit(1)

        print(f"Executing queries against {pg_host}:{pg_port}/{pg_db}...")

        env = os.environ.copy()
        env['PGPASSWORD'] = pg_pass

        result = subprocess.run(
            ['psql', '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', pg_db,
             '-f', str(execute_sql)],
            capture_output=True, text=True, env=env, timeout=600
        )

        output = result.stdout + result.stderr
        results_path = output_path / 'execute_results.txt'
        with open(results_path, 'w') as f:
            f.write(output)

        # Parse row counts
        pass_count = 0
        fail_count = 0
        failures = []
        results_detail = []
        current_test = None

        for line in output.split('\n'):
            if line.startswith('=== ') and line.endswith(' ==='):
                current_test = line.strip('= ').strip()
            elif 'ERROR' in line and current_test:
                fail_count += 1
                failures.append({'test': current_test, 'error': line.strip()})
                current_test = None
            elif current_test:
                row_match = re.match(r'\((\d+) (?:rows?|행)\)', line.strip())
                if row_match:
                    rows = int(row_match.group(1))
                    pass_count += 1
                    results_detail.append({'test': current_test, 'rows': rows})
                    current_test = None

        print(f"\nExecution Results: PASS={pass_count}, FAIL={fail_count}")

        # Result Integrity Guard
        warnings = []
        query_rows = {}  # {query_id: [row_counts]}
        for r in results_detail:
            parts = r['test'].split('.')
            if len(parts) >= 2:
                qid = parts[1] if len(parts) >= 2 else r['test']
                query_rows.setdefault(qid, []).append(r['rows'])

        for qid, rows in query_rows.items():
            if rows and all(r == 0 for r in rows):
                warnings.append({
                    'code': 'WARN_ZERO_ALL_CASES',
                    'severity': 'critical',
                    'query_id': qid,
                    'message': f'All {len(rows)} test cases returned 0 rows',
                })
            elif rows and sum(r == 0 for r in rows) > len(rows) * 0.8:
                warnings.append({
                    'code': 'WARN_MOSTLY_ZERO',
                    'severity': 'high',
                    'query_id': qid,
                    'message': f'{sum(r==0 for r in rows)}/{len(rows)} test cases returned 0 rows',
                })

        if warnings:
            print(f"\nResult Integrity Guard: {len(warnings)} warnings")
            for w in warnings[:10]:
                print(f"  [{w['severity'].upper()}] {w['code']}: {w['query_id']} - {w['message']}")

        if failures:
            print("\nFailures:")
            for f in failures[:20]:
                print(f"  {f['test']}: {f['error'][:120]}")

        # Update query-level tracking (execution results)
        if tracking_dir:
            try:
                from tracking_utils import TrackingManager
                tracking_dirs = self._resolve_tracking_dirs(tracking_dir)
                # Build per-query execution results
                exec_results = {}  # {query_id: {'status': ..., 'row_count': ..., 'error': ...}}
                for detail in results_detail:
                    parts = detail['test'].split('.')
                    if len(parts) >= 2:
                        qid = parts[1]
                        # Keep the best result per query (pass over fail)
                        if qid not in exec_results or exec_results[qid]['status'] != 'pass':
                            exec_results[qid] = {
                                'status': 'pass',
                                'row_count': detail.get('rows')
                            }
                for fail in failures:
                    parts = fail['test'].split('.')
                    if len(parts) >= 2:
                        qid = parts[1]
                        if qid not in exec_results:
                            exec_results[qid] = {
                                'status': 'fail',
                                'error': fail.get('error', '')
                            }

                for tdir in tracking_dirs:
                    tm = TrackingManager(tdir)
                    for qid, res in exec_results.items():
                        tm.update_execution(
                            qid, res['status'],
                            row_count=res.get('row_count'),
                            error=res.get('error')
                        )
                        if res['status'] == 'pass':
                            tm.mark_success(qid)
                tracked_count = len(exec_results)
                if tracked_count:
                    print(f"  Query tracking (execution): {tracked_count} queries updated")
            except Exception as e:
                print(f"  Warning: Could not update query tracking: {e}")

        # Write execute_validated.json
        validated = {
            'timestamp': datetime.now().isoformat(),
            'mode': 'execute',
            'total': pass_count + fail_count,
            'pass': pass_count,
            'fail': fail_count,
            'pass_rate': f"{pass_count/(pass_count+fail_count)*100:.1f}%" if (pass_count+fail_count) > 0 else "N/A",
            'results': results_detail,
            'failures': failures,
            'warnings': warnings,
        }
        with open(output_path / 'execute_validated.json', 'w') as f:
            json.dump(validated, f, indent=2, ensure_ascii=False)

        # Activity log
        try:
            from tracking_utils import log_activity
            log_activity('STEP_END', agent='validate-queries', step='step_3_execute',
                         detail=f"Execute: {pass_count} pass, {fail_count} fail, {len(warnings)} warnings")
        except Exception:
            pass

        print(f"\nSaved: {output_path / 'execute_validated.json'}")
        return validated

    def full_validate(self, output_dir, tracking_dir=None):
        """Full atomic validation: generate + EXPLAIN + Execute + Oracle Compare + parse.
        One command does everything, no intermediate stopping."""
        import shutil
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Step 1: generate scripts (explain_test.sql, execute_test.sql, oracle_compare.sql)
        print("\n[full] Step 1/5: Generating SQL scripts...")
        self.generate_scripts(output_dir)

        # Helper: resolve PG connection params
        pg_host = os.environ.get('PG_HOST', os.environ.get('PGHOST', ''))
        pg_port = os.environ.get('PG_PORT', os.environ.get('PGPORT', '5432'))
        pg_db = os.environ.get('PG_DATABASE', os.environ.get('PGDATABASE', ''))
        pg_user = os.environ.get('PG_USER', os.environ.get('PGUSER', ''))
        pg_pass = os.environ.get('PG_PASSWORD', os.environ.get('PGPASSWORD', ''))

        def run_psql(sql_file, result_file, timeout=300):
            """Run psql against a .sql file, write output to result_file.
            Large files are split by test markers (=== test_id ===) to prevent output truncation."""
            if not shutil.which('psql'):
                print(f"  ERROR: psql not found")
                return False
            env = os.environ.copy()
            env['PGPASSWORD'] = pg_pass

            with open(sql_file, 'r', encoding='utf-8') as f:
                sql_content = f.read()

            # Count test cases — if > 500, split into batches
            test_count = sql_content.count('\\echo ===')
            if test_count <= 500:
                # Small file: run as-is (stderr merged into stdout for proper interleaving)
                try:
                    result = subprocess.run(
                        ['psql', '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', pg_db,
                         '-f', str(sql_file)],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, env=env, timeout=timeout
                    )
                    with open(result_file, 'w', encoding='utf-8') as f:
                        f.write(result.stdout)
                    return True
                except Exception as e:
                    print(f"  ERROR running psql: {e}")
                    return False

            # Large file: split by \\echo === markers and run in batches
            print(f"  Large SQL ({test_count} tests): splitting into batches of 200...")
            lines = sql_content.split('\n')
            batches = []
            current_batch = []
            batch_test_count = 0
            header_lines = []

            for line in lines:
                if line.startswith('\\echo ==='):
                    batch_test_count += 1
                    if batch_test_count > 200 and current_batch:
                        batches.append(header_lines + current_batch)
                        current_batch = []
                        batch_test_count = 1
                if line.startswith('\\set ') and not batches:
                    header_lines.append(line)
                current_batch.append(line)
            if current_batch:
                batches.append(header_lines + current_batch)

            print(f"  Split into {len(batches)} batches")
            all_output = []
            for bi, batch in enumerate(batches):
                batch_file = output_path / f'{Path(sql_file).stem}_batch{bi}.sql'
                with open(batch_file, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(batch))
                try:
                    result = subprocess.run(
                        ['psql', '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', pg_db,
                         '-f', str(batch_file)],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, env=env, timeout=timeout
                    )
                    all_output.append(result.stdout)
                    batch_file.unlink(missing_ok=True)
                except Exception as e:
                    print(f"  ERROR batch {bi}: {e}")
                    all_output.append(f"ERROR: batch {bi} failed: {e}")

            with open(result_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(all_output))
            print(f"  All {len(batches)} batches complete")
            return True

        def run_oracle(sql_file, result_file, timeout=300):
            """Run Oracle SQL file, write output to result_file."""
            # Try oracledb first
            try:
                import oracledb
                ora_host = os.environ.get('ORACLE_HOST', '')
                ora_port = os.environ.get('ORACLE_PORT', '1521')
                ora_sid = os.environ.get('ORACLE_SID', '')
                ora_user = os.environ.get('ORACLE_USER', '')
                ora_pass = os.environ.get('ORACLE_PASSWORD', '')
                dsn = f"{ora_host}:{ora_port}/{ora_sid}"
                conn = oracledb.connect(user=ora_user, password=ora_pass, dsn=dsn)
                cur = conn.cursor()
                with open(sql_file, 'r', encoding='utf-8') as f:
                    sql_content = f.read()
                # Parse PROMPT markers and SQL statements
                output_lines = []
                for block in re.split(r'(?m)^PROMPT\s+', sql_content):
                    block = block.strip()
                    if not block or block.startswith('SET ') or block == 'EXIT;':
                        continue
                    lines = block.split('\n', 1)
                    if len(lines) == 2:
                        output_lines.append(lines[0])  # The marker (=== test_id ===)
                        stmt = lines[1].strip().rstrip(';')
                        if stmt and not stmt.startswith('PROMPT') and not stmt.startswith('SET '):
                            try:
                                cur.execute(stmt)
                                rows = cur.fetchall() if cur.description else []
                                for row in rows:
                                    output_lines.append(' '.join(str(c) for c in row))
                                if cur.description:
                                    output_lines.append(f"{len(rows)} rows selected.")
                            except Exception as e:
                                output_lines.append(f"ORA-ERROR: {e}")
                conn.close()
                with open(result_file, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(output_lines))
                return True
            except ImportError:
                pass
            except Exception:
                pass
            # Fallback: sqlplus binary
            if not shutil.which('sqlplus'):
                print(f"  ERROR: sqlplus not found and oracledb fallback failed")
                return False
            conn_str = self._oracle_conn_str()
            try:
                with open(sql_file, 'r', encoding='utf-8') as f:
                    sql_input = f.read()
                result = subprocess.run(
                    ['sqlplus', '-S', conn_str],
                    input=sql_input, capture_output=True, text=True, timeout=timeout
                )
                with open(result_file, 'w', encoding='utf-8') as f:
                    f.write(result.stdout + result.stderr)
                return True
            except Exception as e:
                print(f"  ERROR running sqlplus: {e}")
                return False

        # Step 2: EXPLAIN
        explain_sql = output_path / 'explain_test.sql'
        explain_out = output_path / 'explain_results.txt'
        if pg_host and pg_db and explain_sql.exists():
            print("[full] Step 2/5: Running EXPLAIN via psql...")
            run_psql(explain_sql, explain_out)
        else:
            print("[full] Step 2/5: SKIP EXPLAIN (PG_HOST/PG_DATABASE not set or no script)")

        # Step 3: Execute
        execute_sql = output_path / 'execute_test.sql'
        execute_out = output_path / 'execute_results.txt'
        if pg_host and pg_db and execute_sql.exists():
            print("[full] Step 3/5: Running Execute via psql...")
            run_psql(execute_sql, execute_out, timeout=600)
        else:
            print("[full] Step 3/5: SKIP Execute (PG_HOST/PG_DATABASE not set or no script)")

        # Step 4: Oracle Compare
        oracle_sql = output_path / 'oracle_compare.sql'
        oracle_out = output_path / 'oracle_results.txt'
        ora_host = os.environ.get('ORACLE_HOST', '')
        if ora_host and oracle_sql.exists():
            print("[full] Step 4/5: Running Oracle Compare...")
            run_oracle(oracle_sql, oracle_out, timeout=600)
        else:
            print("[full] Step 4/5: SKIP Oracle Compare (ORACLE_HOST not set or no script)")

        # Step 5: Parse all results
        print("[full] Step 5/5: Parsing results...")
        result = self.parse_results(output_dir)

        # Update query tracking
        if tracking_dir and result:
            try:
                from tracking_utils import TrackingManager
                tracking_dirs = self._resolve_tracking_dirs(tracking_dir)
                explain_results = {}
                for p in result.get('passes', []):
                    parts = (p if isinstance(p, str) else '').split('.')
                    if len(parts) >= 2:
                        qid = parts[1]
                        if qid not in explain_results:
                            explain_results[qid] = {'status': 'pass'}
                for f_item in result.get('failures', []):
                    parts = f_item.get('test', '').split('.')
                    if len(parts) >= 2:
                        explain_results[parts[1]] = {'status': 'fail', 'error': f_item.get('error', '')}

                compare_path = output_path / 'compare_validated.json'
                compare_pass_qids = set()
                if compare_path.exists():
                    with open(compare_path) as _f:
                        cdata = json.load(_f)
                    for cr in cdata.get('results', []):
                        if cr.get('match'):
                            compare_pass_qids.add(cr.get('query_id', ''))

                for tdir in tracking_dirs:
                    tm = TrackingManager(tdir)
                    for qid, res in explain_results.items():
                        tm.update_explain(qid, res['status'], error=res.get('error'))
                        if res['status'] == 'pass' and qid in compare_pass_qids:
                            tm.mark_success(qid)
                    tm._save()
                print(f"  Query tracking updated: {len(explain_results)} queries")
            except Exception as e:
                print(f"  Warning: Could not update tracking: {e}")

        total = result.get('total', 0) if result else 0
        p = result.get('pass', 0) if result else 0
        fl = result.get('fail', 0) if result else 0
        print(f"\n[full] DONE — {p} pass, {fl} fail (total {total})")
        print(f"  Output: {output_path}")
        return result

    def parse_results(self, output_dir):
        """Parse results from externally executed SQL scripts."""
        output_path = Path(output_dir)

        results_file = output_path / 'explain_results.txt'
        if not results_file.exists():
            # Try to find batch results
            print("Looking for batch result files...")
            all_output = []
            for rf in sorted(output_path.glob('batch_*_result.txt')):
                with open(rf) as f:
                    all_output.append(f.read())
            if all_output:
                combined = '\n'.join(all_output)
                with open(results_file, 'w') as f:
                    f.write(combined)
            else:
                print(f"No result files found in {output_path}")
                return

        with open(results_file) as f:
            output = f.read()

        # Parse
        pass_count = 0
        fail_count = 0
        passes = []
        failures = []
        current_test = None

        for line in output.split('\n'):
            if line.startswith('=== ') and line.endswith(' ==='):
                current_test = line.strip('= ')
            elif 'ERROR' in line and current_test:
                fail_count += 1
                failures.append({'test': current_test, 'error': line.strip()})
                current_test = None
            elif ('QUERY PLAN' in line or 'Seq Scan' in line or 'Index Scan' in line) and current_test:
                pass_count += 1
                passes.append(current_test)
                current_test = None

        print(f"\nParsed Results: PASS={pass_count}, FAIL={fail_count}")

        # Categorize failures
        categories = {}
        for f in failures:
            # Extract error type
            error = f['error']
            if 'syntax error' in error:
                cat = 'SYNTAX_ERROR'
            elif 'does not exist' in error:
                cat = 'MISSING_OBJECT'
            elif 'cannot be matched' in error or 'operator does not exist' in error:
                cat = 'TYPE_MISMATCH'
            elif 'permission denied' in error:
                cat = 'PERMISSION'
            else:
                cat = 'OTHER'
            categories.setdefault(cat, []).append(f)

        if categories:
            print("\nFailure categories:")
            for cat, items in sorted(categories.items()):
                print(f"  {cat}: {len(items)} failures")
                for item in items[:3]:
                    print(f"    - {item['test']}: {item['error'][:100]}")

        # Result Integrity Guard warnings
        warnings = []

        # Load test manifest to check expected rows
        manifest_path = output_path / 'test_manifest.json'
        manifest = {}
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)

        # WARN_ZERO_ALL_CASES: All test cases for a query return 0 rows
        # (Check execute results if available)
        execute_results_file = output_path / 'execute_results.txt'
        if execute_results_file.exists():
            with open(execute_results_file) as f:
                exec_output = f.read()

            # Parse row counts per test
            query_results = {}  # {query_id: [row_counts]}
            current_test = None
            for line in exec_output.split('\n'):
                if line.startswith('=== ') and line.endswith(' ==='):
                    current_test = line.strip('= ')
                    # Extract query_id (format: file.queryId.caseName)
                    parts = current_test.split('.')
                    if len(parts) >= 2:
                        qid = parts[1]
                        query_results.setdefault(qid, [])
                elif current_test and '(0 rows)' in line:
                    parts = current_test.split('.')
                    if len(parts) >= 2:
                        query_results.setdefault(parts[1], []).append(0)
                elif current_test and re.match(r'\((\d+) (?:rows?|행)\)', line):
                    m = re.match(r'\((\d+) (?:rows?|행)\)', line)
                    parts = current_test.split('.')
                    if len(parts) >= 2:
                        query_results.setdefault(parts[1], []).append(int(m.group(1)))

            for qid, rows in query_results.items():
                if rows and all(r == 0 for r in rows):
                    warnings.append({
                        'code': 'WARN_ZERO_ALL_CASES',
                        'severity': 'critical',
                        'query_id': qid,
                        'message': f'All {len(rows)} test cases returned 0 rows',
                        'test_case_count': len(rows),
                    })
                elif rows and sum(r == 0 for r in rows) > len(rows) * 0.8:
                    warnings.append({
                        'code': 'WARN_MOSTLY_ZERO',
                        'severity': 'high',
                        'query_id': qid,
                        'message': f'{sum(r==0 for r in rows)}/{len(rows)} test cases returned 0 rows',
                    })

        # Parse Oracle vs PG compare results
        compare_results = []
        oracle_results_file = output_path / 'oracle_results.txt'
        if execute_results_file.exists() and oracle_results_file.exists():
            print("\nParsing Oracle vs PG compare results...")
            # Parse PG row counts (COUNT(*) results)
            pg_rows = {}  # {test_id: row_count}
            current_test = None
            for line in exec_output.split('\n'):
                if line.startswith('=== ') and line.endswith(' ==='):
                    current_test = line.strip('= ')
                elif current_test:
                    stripped = line.strip()
                    # COUNT(*) result: just a number on its own line (e.g., "   50")
                    if stripped.isdigit():
                        pg_rows[current_test] = int(stripped)
                        current_test = None
                    # Old format: (N rows) — still support for non-COUNT queries
                    elif re.match(r'\((\d+) (?:rows?|행)\)', stripped):
                        m = re.match(r'\((\d+) (?:rows?|행)\)', stripped)
                        pg_rows[current_test] = int(m.group(1))
                        current_test = None
                    elif 'ERROR' in line:
                        pg_rows[current_test] = -1
                        current_test = None

            # Parse Oracle row counts
            with open(oracle_results_file) as f:
                ora_output = f.read()
            ora_rows = {}
            current_test = None
            for line in ora_output.split('\n'):
                if line.startswith('=== ') and line.endswith(' ==='):
                    current_test = line.strip('= ')
                elif current_test:
                    # Oracle COUNT(*) result: just a number on its own line
                    stripped = line.strip()
                    if stripped.isdigit():
                        ora_rows[current_test] = int(stripped)
                        current_test = None
                    elif 'SP2-' in line or 'ORA-' in line or 'ERROR' in line:
                        ora_rows[current_test] = -1
                        current_test = None

            # Compare
            all_test_ids = set(pg_rows.keys()) | set(ora_rows.keys())
            for tid in sorted(all_test_ids):
                parts = tid.split('.')
                qid = parts[1] if len(parts) >= 2 else tid
                pg_r = pg_rows.get(tid)
                ora_r = ora_rows.get(tid)

                if pg_r is None or ora_r is None:
                    # 한쪽 파싱 실패 — 조용히 스킵하지 않고 기록
                    reason_parts = []
                    if ora_r is None:
                        reason_parts.append('oracle_parse_fail')
                    if pg_r is None:
                        reason_parts.append('pg_parse_fail')
                    compare_results.append({
                        'query_id': qid, 'test_id': tid, 'match': False,
                        'oracle_rows': ora_r, 'pg_rows': pg_r,
                        'reason': '+'.join(reason_parts),
                    })
                    continue
                if pg_r == -1 or ora_r == -1:
                    compare_results.append({
                        'query_id': qid, 'test_id': tid, 'match': False,
                        'oracle_rows': ora_r, 'pg_rows': pg_r,
                        'reason': 'execution_error'
                    })
                elif pg_r == ora_r:
                    result_entry = {
                        'query_id': qid, 'test_id': tid, 'match': True,
                        'oracle_rows': ora_r, 'pg_rows': pg_r
                    }
                    if pg_r == 0:
                        result_entry['warning'] = 'both_zero_rows'
                    compare_results.append(result_entry)
                else:
                    compare_results.append({
                        'query_id': qid, 'test_id': tid, 'match': False,
                        'oracle_rows': ora_r, 'pg_rows': pg_r,
                        'reason': f'row_count_diff: oracle={ora_r} pg={pg_r}'
                    })

            if compare_results:
                match_count = sum(1 for c in compare_results if c['match'])
                fail_count_cmp = len(compare_results) - match_count
                compare_data = {
                    'timestamp': datetime.now().isoformat(),
                    'total': len(compare_results),
                    'pass': match_count,
                    'matched': match_count,
                    'fail': fail_count_cmp,
                    'mismatched': fail_count_cmp,
                    'results': compare_results,
                }
                with open(output_path / 'compare_validated.json', 'w') as f:
                    json.dump(compare_data, f, indent=2, ensure_ascii=False)
                print(f"  Compare: {match_count} match, {fail_count_cmp} mismatch out of {len(compare_results)}")
                print(f"  Saved: {output_path / 'compare_validated.json'}")

        if warnings:
            print(f"\nResult Integrity Guard: {len(warnings)} warnings")
            for w in warnings[:10]:
                print(f"  [{w['severity'].upper()}] {w['code']}: {w['query_id']} - {w['message']}")

        # Deduplicate passes to query level for smaller JSON
        # passes list can be 20,000+ test_ids — compress to unique query_ids
        pass_query_ids = list(set(
            '.'.join(tid.split('.')[:-1]) if '.' in tid else tid
            for tid in passes
        ))

        # Write validated.json
        validated = {
            'timestamp': datetime.now().isoformat(),
            'total': pass_count + fail_count,
            'pass': pass_count,
            'fail': fail_count,
            'pass_rate': f"{pass_count/(pass_count+fail_count)*100:.1f}%" if (pass_count+fail_count) > 0 else "N/A",
            'failure_categories': {k: len(v) for k, v in categories.items()},
            'passes': passes,
            'pass_query_ids': pass_query_ids,
            'failures': failures,
            'warnings': warnings,
            'warning_count': len(warnings),
        }
        with open(output_path / 'validated.json', 'w') as f:
            json.dump(validated, f, indent=2, ensure_ascii=False)

        print(f"\nSaved: {output_path / 'validated.json'}")
        return validated


def main():
    parser = argparse.ArgumentParser(description='Step 3: Query Validation Tool')
    parser.add_argument('--generate', action='store_true', help='Generate SQL test scripts')
    parser.add_argument('--local', action='store_true', help='Execute EXPLAIN locally via psql')
    parser.add_argument('--execute', action='store_true', help='Execute queries locally via psql (actual execution)')
    parser.add_argument('--compare', action='store_true', help='Execute on BOTH Oracle AND PostgreSQL, compare results')
    parser.add_argument('--parse-results', action='store_true', help='Parse results from executed scripts')
    parser.add_argument('--full', action='store_true', help='Full validation: generate + EXPLAIN + Execute + Compare + parse (atomic)')
    parser.add_argument('--output', default='workspace/results/_validation', help='Output directory')
    parser.add_argument('--xml-dir', default='workspace/output', help='Converted XML directory')
    parser.add_argument('--input-dir', default='workspace/input', help='Original Oracle XML directory')
    parser.add_argument('--files', default=None, help='Comma-separated list of XML filenames to process (for parallel batching)')
    parser.add_argument('--results-dir', default='workspace/results', help='Results directory')
    parser.add_argument('--extracted', default=None, help='Extracted SQL dir from mybatis-sql-extractor (Phase 3.5)')
    parser.add_argument('--tracking-dir', default=None, help='Path to results dir for query-level tracking, or "auto"')

    args = parser.parse_args()

    validator = QueryValidator(args.xml_dir, args.results_dir, args.input_dir)

    # --files filter: only process specified files
    file_filter = None
    if args.files:
        file_filter = set(f.strip() for f in args.files.split(','))
        print(f"File filter: {len(file_filter)} files")

    def apply_file_filter():
        if file_filter:
            before = len(validator.queries)
            validator.queries = [q for q in validator.queries if q.get('file', '') in file_filter]
            print(f"  Filtered: {before} -> {len(validator.queries)} queries")

    def load_queries_with_extracted_priority():
        """Always try load_extracted() first. Supplement missing queries from static XML."""
        # Auto-detect extracted dir if not specified
        extracted_dir = args.extracted
        if not extracted_dir:
            # Search common locations for extracted SQL
            candidates = [
                Path(args.results_dir) / '_extracted',
                Path('workspace/results/_extracted'),
            ]
            for c in candidates:
                if c.exists() and list(c.glob('*-extracted.json')):
                    extracted_dir = str(c)
                    break

        extracted_count = 0
        if extracted_dir:
            validator.load_extracted(extracted_dir)
            extracted_count = len(validator.queries)

        if not validator.queries:
            print("WARNING: No MyBatis extracted SQL found. Using static extraction (limited). "
                  "Install Java 11+ for accurate validation.")
            validator.load_queries()
        else:
            # Supplement: extracted에서 빈 SQL로 skip된 쿼리를 static XML에서 보충
            # include refid 해석 포함 (PR #1 반영)
            extracted_qids_by_file = {(q['file'], q['id']) for q in validator.queries}
            added = validator._supplement_static_queries(extracted_qids_by_file)
            if added:
                print(f"  Supplemented {added} queries from static XML with include refid resolution "
                      f"(MyBatis rendered: {extracted_count}, static fallback: {added})")

        validator.load_test_cases()

    if args.compare:
        load_queries_with_extracted_priority()
        apply_file_filter()
        validator.load_oracle_queries()
        validator.compare_queries(args.output, tracking_dir=args.tracking_dir)

    elif args.generate:
        load_queries_with_extracted_priority()
        validator.load_oracle_queries()  # For oracle_compare.sql generation
        apply_file_filter()
        validator.generate_scripts(args.output)

    elif args.local:
        load_queries_with_extracted_priority()
        apply_file_filter()
        validator.generate_scripts(args.output)
        validator.execute_local(args.output, tracking_dir=args.tracking_dir)

    elif args.execute:
        load_queries_with_extracted_priority()
        apply_file_filter()
        validator.generate_scripts(args.output)
        validator.execute_local_queries(args.output, tracking_dir=args.tracking_dir)

    elif args.full:
        load_queries_with_extracted_priority()
        apply_file_filter()
        validator.load_oracle_queries()
        validator.full_validate(args.output, tracking_dir=args.tracking_dir)

    elif args.parse_results:
        result = validator.parse_results(args.output)

        # Update query-level tracking from parsed results
        if args.tracking_dir and result:
            try:
                tracking_dir = args.tracking_dir
                if tracking_dir == 'auto':
                    tracking_dirs = list(Path(args.results_dir).glob('*/v*/'))
                else:
                    tracking_dirs = list(Path(tracking_dir).glob('*/v*/'))

                from tracking_utils import TrackingManager
                explain_results = {}
                for p in result.get('passes', []):
                    tid = p if isinstance(p, str) else ''
                    parts = tid.split('.')
                    if len(parts) >= 2:
                        qid = parts[-2] if len(parts) >= 3 else parts[-1]
                        if qid not in explain_results:
                            explain_results[qid] = {'status': 'pass'}
                for f in result.get('failures', []):
                    tid = f.get('test', '')
                    parts = tid.split('.')
                    if len(parts) >= 2:
                        qid = parts[-2] if len(parts) >= 3 else parts[-1]
                        explain_results[qid] = {'status': 'fail', 'error': f.get('error', '')}

                # Also load compare results for success marking
                compare_path = Path(args.output) / 'compare_validated.json'
                compare_pass_qids = set()
                if compare_path.exists():
                    with open(compare_path) as _f:
                        cdata = json.load(_f)
                    for cr in cdata.get('results', []):
                        if cr.get('match'):
                            compare_pass_qids.add(cr.get('query_id', ''))

                for tdir in tracking_dirs:
                    tm = TrackingManager(tdir)
                    for qid, res in explain_results.items():
                        tm.update_explain(qid, res['status'], error=res.get('error'))
                        # EXPLAIN pass + Compare pass → success
                        if res['status'] == 'pass' and qid in compare_pass_qids:
                            tm.mark_success(qid)
                    tm._save()
                success_count = sum(1 for qid in explain_results if explain_results[qid]['status'] == 'pass' and qid in compare_pass_qids)
                print(f"  Query tracking updated: {len(explain_results)} queries ({success_count} marked success)")
            except Exception as e:
                print(f"  Warning: Could not update query tracking: {e}")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
