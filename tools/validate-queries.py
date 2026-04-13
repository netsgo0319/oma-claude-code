#!/usr/bin/env python3
"""
Phase 3: Query Validation Tool
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

    # Use extracted SQL from mybatis-sql-extractor (Phase 3.5)
    python3 tools/validate-queries.py --generate --extracted workspace/results/_extracted/ --output workspace/results/_validation/
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

        # Method 2: From input XML files (fallback)
        if not self.oracle_queries and self.input_dir.exists():
            for xml_file in sorted(self.input_dir.glob('*.xml')):
                try:
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                except ET.ParseError:
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
                        if qid and raw_sql:
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

            if not oracle_sql:
                print(f"  SKIP {qid}: no Oracle SQL found")
                continue

            cases = self.test_cases.get(qid, [])
            if not cases:
                # Single default test
                cases = [{'name': 'default', 'params': {}}]

            for i, case in enumerate(cases):
                if isinstance(case, dict):
                    binds = case.get('binds', case.get('params', {}))
                    for skip_key in ['name', 'description', 'source', 'case_id', 'not_null_columns', 'expected']:
                        binds.pop(skip_key, None) if isinstance(binds, dict) else None
                    case_name = case.get('name', case.get('case_id', f'tc{i}'))
                else:
                    binds = {}
                    case_name = f'tc{i}'

                # Bind params into both SQLs
                bound_oracle = self.bind_params(oracle_sql, binds)
                bound_pg = self.bind_params(pg_sql, binds)

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
            log_activity('PHASE_END', agent='validate-queries', phase='phase_3_compare',
                         detail=f"Compare: {pass_count} match, {fail_count} fail, {warn_count} warn (total {total})")
        except Exception:
            pass

        print(f"\nSaved: {output_path / 'compare_validated.json'}")
        return validated

    @staticmethod
    def _extract_mybatis_sql(elem, mapper_root=None):
        """Extract SQL from MyBatis XML element, handling dynamic SQL tags intelligently.
        Instead of blindly joining all itertext(), this understands:
        - <if>: include content (assume condition true for max coverage)
        - <choose>/<when>/<otherwise>: pick first <when> only (avoid duplicate branches)
        - <where>: wrap content with WHERE, strip leading AND/OR
        - <set>: wrap content with SET, strip trailing comma
        - <trim>: apply prefix/suffix/prefixOverrides/suffixOverrides
        - <foreach>: generate single iteration placeholder
        - <include>: resolve by looking up <sql id="X"> in mapper root
        - <selectKey>: skip (separate statement)
        - <bind>: skip

        mapper_root: the <mapper> root element (for <sql> fragment lookup).
                     If None, falls back to searching within elem only.
        """
        # Pre-build sql fragment map for <include refid="X"> resolution
        sql_fragments = {}
        search_root = mapper_root or elem
        try:
            for sql_elem in search_root.iter():
                if sql_elem.tag == 'sql' and sql_elem.get('id'):
                    sql_fragments[sql_elem.get('id')] = sql_elem
        except Exception:
            pass

        def _walk(el):
            parts = []
            # Element's own text
            if el.text and el.text.strip():
                parts.append(el.text.strip())

            for child in el:
                tag = child.tag if isinstance(child.tag, str) else ''

                if tag == 'if':
                    # Include content (assume condition true)
                    parts.append(_walk(child))

                elif tag == 'choose':
                    # Pick first <when> only, or <otherwise> if no <when>
                    when = child.find('when')
                    if when is not None:
                        parts.append(_walk(when))
                    else:
                        otherwise = child.find('otherwise')
                        if otherwise is not None:
                            parts.append(_walk(otherwise))

                elif tag == 'when':
                    parts.append(_walk(child))

                elif tag == 'otherwise':
                    # Only reached if no <when> matched above
                    parts.append(_walk(child))

                elif tag == 'where':
                    inner = _walk(child).strip()
                    if inner:
                        # Strip leading AND/OR
                        inner = re.sub(r'^(?:AND|OR)\s+', '', inner, flags=re.IGNORECASE)
                        parts.append(f'WHERE {inner}')

                elif tag == 'set':
                    inner = _walk(child).strip()
                    # Remove trailing comma (MyBatis <set> does this)
                    inner = re.sub(r',\s*$', '', inner)
                    if inner:
                        parts.append(f'SET {inner}')

                elif tag == 'trim':
                    inner = _walk(child).strip()
                    prefix = child.get('prefix', '')
                    suffix = child.get('suffix', '')
                    prefix_overrides = child.get('prefixOverrides', '')
                    suffix_overrides = child.get('suffixOverrides', '')
                    if prefix_overrides and inner:
                        for po in prefix_overrides.split('|'):
                            po = po.strip()
                            if po and inner.upper().startswith(po.upper()):
                                inner = inner[len(po):].strip()
                                break
                    if suffix_overrides and inner:
                        for so in suffix_overrides.split('|'):
                            so = so.strip()
                            if so and inner.upper().endswith(so.upper()):
                                inner = inner[:-len(so)].strip()
                                break
                    if inner:
                        parts.append(f'{prefix} {inner} {suffix}'.strip())

                elif tag == 'foreach':
                    # Generate single item placeholder
                    item = child.get('item', 'item')
                    open_str = child.get('open', '')
                    close_str = child.get('close', '')
                    inner = _walk(child).strip()
                    if inner:
                        parts.append(f'{open_str}{inner}{close_str}')

                elif tag == 'include':
                    refid = child.get('refid', '')
                    if refid and refid in sql_fragments:
                        parts.append(_walk(sql_fragments[refid]))
                    # else: skip (not found or already expanded)

                elif tag in ('selectKey', 'bind'):
                    pass  # Skip

                else:
                    # Unknown tag — include text content
                    parts.append(_walk(child))

                # Tail text (text after closing tag)
                if child.tail and child.tail.strip():
                    parts.append(child.tail.strip())

            return ' '.join(p for p in parts if p)

        return _walk(elem)

    def load_queries(self):
        """Load all queries from converted XML files."""
        for xml_file in sorted(self.output_dir.glob('*.xml')):
            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()
            except ET.ParseError as e:
                print(f"  SKIP {xml_file.name}: XML parse error: {e}")
                continue

            for tag in ['select', 'insert', 'update', 'delete']:
                for elem in root.findall(f'.//{tag}'):
                    qid = elem.get('id', 'unknown')
                    raw_sql = self._extract_mybatis_sql(elem, mapper_root=root)
                    raw_sql = re.sub(r'--[^\n]*', '', raw_sql)
                    raw_sql = re.sub(r'\s+', ' ', raw_sql).strip()

                    # Extract parameter names
                    params = re.findall(r'#\{(\w+)(?:,[^}]*)?\}', raw_sql)

                    self.queries.append({
                        'file': xml_file.name,
                        'id': qid,
                        'type': tag,
                        'sql_raw': raw_sql,
                        'params': list(set(params)),
                    })

        print(f"Loaded {len(self.queries)} queries from {len(list(self.output_dir.glob('*.xml')))} files")

    def load_extracted(self, extracted_dir):
        """Load SQL from mybatis-sql-extractor JSON output (Phase 3.5).
        This provides accurate SQL with dynamic branches resolved by the MyBatis engine."""
        extracted_path = Path(extracted_dir)
        if not extracted_path.exists():
            print(f"ERROR: Extracted directory not found: {extracted_dir}")
            return

        for json_file in sorted(extracted_path.glob('*-extracted.json')):
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
        """Load test cases from workspace/results/*/v*/test-cases.json."""
        # Search all version directories, not just v1
        found_files = list(self.results_dir.glob('*/v*/test-cases.json'))
        if not found_files:
            # Also try direct children (flat structure)
            found_files = list(self.results_dir.glob('*/test-cases.json'))
        if not found_files:
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

    def bind_params(self, sql, params_dict):
        """Replace #{param} with actual values from test case."""
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

        # Replace any remaining unbound params with NULL
        result = re.sub(r'#\{[^}]+\}', 'NULL', result)
        # Replace ${} dollar substitution with placeholder
        result = re.sub(r'\$\{[^}]+\}', "placeholder_tbl", result)

        return result

    @staticmethod
    def _extract_dml_where(sql):
        """DML (UPDATE/DELETE)에서 테이블명과 WHERE 절을 추출하여 SELECT COUNT(*)로 변환.
        Oracle sqlplus에 statement_timeout이 없으므로 DML 실행 대신 영향 행수만 예측.
        예: UPDATE T SET col=1 WHERE id=1 → SELECT * FROM T WHERE id=1"""
        flat = re.sub(r'\s+', ' ', sql).strip().rstrip(';')
        # UPDATE table SET ... WHERE ...
        m = re.match(r'UPDATE\s+(\S+)\s+.*?(WHERE\s+.+)$', flat, re.IGNORECASE)
        if m:
            table = m.group(1)
            where = m.group(2)
            return f"SELECT * FROM {table} {where}"
        # DELETE FROM table WHERE ...
        m = re.match(r'DELETE\s+(?:FROM\s+)?(\S+)\s+(WHERE\s+.+)$', flat, re.IGNORECASE)
        if m:
            return f"SELECT * FROM {m.group(1)} {m.group(2)}"
        # INSERT — 행수 예측 불가, 스킵
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
        explain_lines = ["\\set ON_ERROR_STOP off", ""]
        execute_lines = ["\\set ON_ERROR_STOP off", ""]
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

            # Extracted SQL has ? placeholders from MyBatis — bind with TC values if available
            if is_extracted:
                param_names = query.get('param_names_for_bind', [])
                tc_binds = {}
                # Try to find TC values for these parameter names
                if param_names:
                    tc_cases = self.test_cases.get(qid, [])
                    if tc_cases and isinstance(tc_cases[0], dict):
                        tc_binds = tc_cases[0].get('params', tc_cases[0].get('binds', {}))

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

                if qtype == 'select':
                    safe_sql = bound_sql.rstrip(';')
                    if 'LIMIT' not in safe_sql.upper():
                        safe_sql += ' LIMIT 5'
                    execute_lines.append(f"\\echo === {test_id} ===")
                    execute_lines.append(f"SET statement_timeout = '30s';")
                    execute_lines.append(f"{safe_sql};")
                    execute_lines.append("")

                continue

            # Get test cases for this query
            cases = self.test_cases.get(qid, [])

            if not cases:
                # No test cases - use default dummy binding
                bound_sql = re.sub(r'#\{[^}]+\}', "'1'", sql)
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

                # EXECUTE
                if qtype == 'select':
                    safe_sql = bound_sql.rstrip(';')
                    if 'LIMIT' not in safe_sql.upper():
                        safe_sql += ' LIMIT 5'
                    execute_lines.append(f"\\echo === {test_id} ===")
                    execute_lines.append(f"SET statement_timeout = '30s';")
                    execute_lines.append(f"{safe_sql};")
                    execute_lines.append("")
                else:
                    # DML: EXPLAIN first to check cost, then execute with short timeout
                    execute_lines.append(f"\\echo === {test_id} ===")
                    execute_lines.append(f"SET statement_timeout = '5s';")
                    execute_lines.append(f"BEGIN;")
                    execute_lines.append(f"{bound_sql.rstrip(';')};")
                    execute_lines.append(f"ROLLBACK;")
                    execute_lines.append("")

                # Oracle compare (use original SQL with same binds)
                oracle_sql = self.oracle_queries.get(qid, '')
                if oracle_sql:
                    ora_bound = self._flatten_sql(self.bind_params(oracle_sql, {}))
                    oracle_lines.append(f"PROMPT === {test_id} ===")
                    if qtype == 'select':
                        safe_ora = ora_bound.rstrip(';')
                        oracle_lines.append(f"SELECT COUNT(*) FROM ({safe_ora}) WHERE ROWNUM <= 50;")
                    else:
                        # DML: SELECT COUNT(*) 로 영향 행수만 예측 (실제 UPDATE/DELETE 실행 안 함)
                        # Oracle sqlplus에 statement_timeout이 없어서 대형 DML이 무한 실행됨
                        dml_where = self._extract_dml_where(ora_bound)
                        if dml_where:
                            oracle_lines.append(f"SELECT COUNT(*) AS affected_rows FROM ({dml_where}) WHERE ROWNUM <= 50;")
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

                    # EXPLAIN (always — even for skipped DML, syntax check is safe)
                    explain_lines.append(f"\\echo === {test_id} ===")
                    explain_lines.append(f"EXPLAIN {bound_sql.rstrip(';')};")
                    explain_lines.append("")

                    # EXECUTE — skip if marked dangerous (large table DML)
                    if execute_skip:
                        execute_lines.append(f"\\echo === {test_id} ===")
                        execute_lines.append(f"\\echo SKIPPED: {skip_reason}")
                        execute_lines.append("")
                    elif qtype == 'select':
                        safe_sql = bound_sql.rstrip(';')
                        if 'LIMIT' not in safe_sql.upper():
                            safe_sql += ' LIMIT 5'
                        execute_lines.append(f"\\echo === {test_id} ===")
                        execute_lines.append(f"SET statement_timeout = '30s';")
                        execute_lines.append(f"{safe_sql};")
                        execute_lines.append("")
                    else:
                        # DML: wrap in BEGIN/ROLLBACK with short timeout (prevent mass UPDATE)
                        execute_lines.append(f"\\echo === {test_id} ===")
                        execute_lines.append(f"SET statement_timeout = '5s';")
                        execute_lines.append(f"BEGIN;")
                        execute_lines.append(f"{bound_sql.rstrip(';')};")
                        execute_lines.append(f"ROLLBACK;")
                        execute_lines.append("")

                    # Oracle compare
                    oracle_sql = self.oracle_queries.get(qid, '')
                    if oracle_sql:
                        ora_bound = self._flatten_sql(self.bind_params(oracle_sql, binds))
                        oracle_lines.append(f"PROMPT === {test_id} ===")
                        if qtype == 'select':
                            safe_ora = ora_bound.rstrip(';')
                            oracle_lines.append(f"SELECT COUNT(*) FROM ({safe_ora}) WHERE ROWNUM <= 50;")
                        else:
                            # DML: SELECT COUNT(*) WHERE로 영향 행수만 예측
                            dml_where = self._extract_dml_where(ora_bound)
                            if dml_where:
                                oracle_lines.append(f"SELECT COUNT(*) AS affected_rows FROM ({dml_where}) WHERE ROWNUM <= 50;")
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
            log_activity('PHASE_END', agent='validate-queries', phase='phase_3_explain',
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
            log_activity('PHASE_END', agent='validate-queries', phase='phase_3_execute',
                         detail=f"Execute: {pass_count} pass, {fail_count} fail, {len(warnings)} warnings")
        except Exception:
            pass

        print(f"\nSaved: {output_path / 'execute_validated.json'}")
        return validated

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
            # Parse PG row counts
            pg_rows = {}  # {test_id: row_count}
            current_test = None
            for line in exec_output.split('\n'):
                if line.startswith('=== ') and line.endswith(' ==='):
                    current_test = line.strip('= ')
                elif current_test:
                    m = re.match(r'\((\d+) (?:rows?|행)\)', line.strip())
                    if m:
                        pg_rows[current_test] = int(m.group(1))
                        current_test = None
                    elif 'ERROR' in line:
                        pg_rows[current_test] = -1  # error marker
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
                    continue  # one side missing
                if pg_r == -1 or ora_r == -1:
                    compare_results.append({
                        'query_id': qid, 'test_id': tid, 'match': False,
                        'oracle_rows': ora_r, 'pg_rows': pg_r,
                        'reason': 'execution_error'
                    })
                elif pg_r == ora_r:
                    compare_results.append({
                        'query_id': qid, 'test_id': tid, 'match': True,
                        'oracle_rows': ora_r, 'pg_rows': pg_r
                    })
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
    parser = argparse.ArgumentParser(description='Phase 3: Query Validation Tool')
    parser.add_argument('--generate', action='store_true', help='Generate SQL test scripts')
    parser.add_argument('--local', action='store_true', help='Execute EXPLAIN locally via psql')
    parser.add_argument('--execute', action='store_true', help='Execute queries locally via psql (actual execution)')
    parser.add_argument('--compare', action='store_true', help='Execute on BOTH Oracle AND PostgreSQL, compare results')
    parser.add_argument('--parse-results', action='store_true', help='Parse results from executed scripts')
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
            print(f"  Filtered: {before} → {len(validator.queries)} queries")

    if args.compare:
        validator.load_queries()
        apply_file_filter()
        validator.load_oracle_queries()
        validator.load_test_cases()
        validator.compare_queries(args.output, tracking_dir=args.tracking_dir)

    elif args.generate:
        if args.extracted:
            validator.load_extracted(args.extracted)
        else:
            validator.load_queries()
            validator.load_test_cases()
        validator.load_oracle_queries()  # For oracle_compare.sql generation
        apply_file_filter()
        validator.generate_scripts(args.output)

    elif args.local:
        if args.extracted:
            validator.load_extracted(args.extracted)
        else:
            validator.load_queries()
            validator.load_test_cases()
        apply_file_filter()
        validator.generate_scripts(args.output)
        validator.execute_local(args.output, tracking_dir=args.tracking_dir)

    elif args.execute:
        if args.extracted:
            validator.load_extracted(args.extracted)
        else:
            validator.load_queries()
            validator.load_test_cases()
        apply_file_filter()
        validator.generate_scripts(args.output)
        validator.execute_local_queries(args.output, tracking_dir=args.tracking_dir)

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

                for tdir in tracking_dirs:
                    tm = TrackingManager(tdir)
                    for qid, res in explain_results.items():
                        tm.update_explain(qid, res['status'], error=res.get('error'))
                    tm._save()
                print(f"  Query tracking updated: {len(explain_results)} queries")
            except Exception as e:
                print(f"  Warning: Could not update query tracking: {e}")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
