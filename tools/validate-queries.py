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

    # Use extracted SQL from mybatis-sql-extractor (Phase 7)
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
    def __init__(self, output_dir='workspace/output', results_dir='workspace/results'):
        self.output_dir = Path(output_dir)
        self.results_dir = Path(results_dir)
        self.queries = []
        self.test_cases = {}

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
                    # Get all text content
                    parts = []
                    for text in elem.itertext():
                        parts.append(text.strip())
                    raw_sql = ' '.join(parts)
                    # Remove SQL comments (-- ...) that may contain non-ASCII chars
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
        """Load SQL from mybatis-sql-extractor JSON output (Phase 7).
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

                for q in queries_data:
                    qid = q.get('query_id', 'unknown')
                    qtype = q.get('type', 'select')

                    # Collect unique SQL variants
                    seen_sql = set()
                    variants = q.get('sql_variants', [])
                    for variant in variants:
                        sql = variant.get('sql', '')
                        if not sql or 'error' in variant:
                            continue
                        if sql in seen_sql:
                            continue
                        seen_sql.add(sql)

                        variant_name = variant.get('params', 'default')
                        self.queries.append({
                            'file': source_file,
                            'id': qid,
                            'type': qtype,
                            'sql_raw': sql,
                            'params': [],  # Already bound by MyBatis engine
                            'variant': variant_name,
                            'from_extracted': True,
                        })

            except (json.JSONDecodeError, Exception) as e:
                print(f"  WARN: Error loading {json_file}: {e}")

        print(f"Loaded {len(self.queries)} unique SQL variants from extracted JSON")

    def load_test_cases(self):
        """Load test cases from workspace/results/*/v1/test-cases.json."""
        for tc_file in self.results_dir.glob('*/v1/test-cases.json'):
            try:
                with open(tc_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Handle different structures
                if isinstance(data, dict):
                    cases = data.get('query_test_cases', data.get('test_cases', []))
                    if isinstance(cases, dict):
                        # {query_id: [{...}]}
                        for qid, tcs in cases.items():
                            if isinstance(tcs, list):
                                self.test_cases[qid] = tcs
                            elif isinstance(tcs, dict) and 'test_cases' in tcs:
                                self.test_cases[qid] = tcs['test_cases']
                    elif isinstance(cases, list):
                        for tc in cases:
                            qid = tc.get('query_id', '')
                            tcs = tc.get('test_cases', [tc])
                            self.test_cases[qid] = tcs
                elif isinstance(data, list):
                    for tc in data:
                        qid = tc.get('query_id', '')
                        self.test_cases[qid] = tc.get('test_cases', [tc])

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
            elif isinstance(value, (int, float)):
                replacement = str(value)
            elif isinstance(value, str):
                replacement = f"'{value}'"
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
        result = re.sub(r'\$\{[^}]+\}', "'placeholder'", result)

        return result

    def generate_scripts(self, output_dir):
        """Generate SQL test scripts for remote execution."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        all_tests = []
        explain_lines = ["\\set ON_ERROR_STOP off", ""]
        execute_lines = ["\\set ON_ERROR_STOP off", ""]

        for query in self.queries:
            qid = query['id']
            fname = query['file'].replace('.xml', '')
            sql = query['sql_raw']
            qtype = query['type']
            is_extracted = query.get('from_extracted', False)
            variant_name = query.get('variant', '')

            # Extracted SQL already has ? placeholders from MyBatis — replace with dummy values
            if is_extracted:
                bound_sql = sql.replace('?', "'1'")
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
                bound_sql = re.sub(r'\$\{[^}]+\}', "'placeholder'", bound_sql)

                test_id = f"{fname}.{qid}.default"
                all_tests.append({
                    'test_id': test_id,
                    'file': query['file'],
                    'query_id': qid,
                    'type': qtype,
                    'case': 'default',
                    'bound_sql': bound_sql,
                })

                # EXPLAIN
                explain_lines.append(f"\\echo === {test_id} ===")
                explain_lines.append(f"EXPLAIN {bound_sql.rstrip(';')};")
                explain_lines.append("")

                # EXECUTE (SELECT only, with LIMIT for safety)
                if qtype == 'select':
                    safe_sql = bound_sql.rstrip(';')
                    if 'LIMIT' not in safe_sql.upper():
                        safe_sql += ' LIMIT 5'
                    execute_lines.append(f"\\echo === {test_id} ===")
                    execute_lines.append(f"SET statement_timeout = '30s';")
                    execute_lines.append(f"{safe_sql};")
                    execute_lines.append("")

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
                    })

                    # EXPLAIN
                    explain_lines.append(f"\\echo === {test_id} ===")
                    explain_lines.append(f"EXPLAIN {bound_sql.rstrip(';')};")
                    explain_lines.append("")

                    # EXECUTE (SELECT only)
                    if qtype == 'select':
                        safe_sql = bound_sql.rstrip(';')
                        if 'LIMIT' not in safe_sql.upper():
                            safe_sql += ' LIMIT 5'
                        execute_lines.append(f"\\echo === {test_id} ===")
                        execute_lines.append(f"SET statement_timeout = '30s';")
                        execute_lines.append(f"{safe_sql};")
                        execute_lines.append("")

        # Write scripts
        with open(output_path / 'explain_test.sql', 'w', encoding='utf-8') as f:
            f.write('\n'.join(explain_lines))

        with open(output_path / 'execute_test.sql', 'w', encoding='utf-8') as f:
            f.write('\n'.join(execute_lines))

        # Write test manifest
        with open(output_path / 'test_manifest.json', 'w', encoding='utf-8') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'total_tests': len(all_tests),
                'tests': all_tests,
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
        print(f"  {output_path / 'test_manifest.json'}")
        print(f"  {total_batches} SSM batches in {batch_dir}/")

        return all_tests

    def execute_local(self, output_dir):
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

        return validated

    def execute_local_queries(self, output_dir):
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
                row_match = re.match(r'\((\d+) rows?\)', line.strip())
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
                elif current_test and re.match(r'\((\d+) rows?\)', line):
                    m = re.match(r'\((\d+) rows?\)', line)
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

        if warnings:
            print(f"\nResult Integrity Guard: {len(warnings)} warnings")
            for w in warnings[:10]:
                print(f"  [{w['severity'].upper()}] {w['code']}: {w['query_id']} - {w['message']}")

        # Write validated.json
        validated = {
            'timestamp': datetime.now().isoformat(),
            'total': pass_count + fail_count,
            'pass': pass_count,
            'fail': fail_count,
            'pass_rate': f"{pass_count/(pass_count+fail_count)*100:.1f}%" if (pass_count+fail_count) > 0 else "N/A",
            'failure_categories': {k: len(v) for k, v in categories.items()},
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
    parser.add_argument('--parse-results', action='store_true', help='Parse results from executed scripts')
    parser.add_argument('--output', default='workspace/results/_validation', help='Output directory')
    parser.add_argument('--xml-dir', default='workspace/output', help='Converted XML directory')
    parser.add_argument('--results-dir', default='workspace/results', help='Results directory')
    parser.add_argument('--extracted', default=None, help='Extracted SQL dir from mybatis-sql-extractor (Phase 7)')

    args = parser.parse_args()

    validator = QueryValidator(args.xml_dir, args.results_dir)

    if args.generate:
        if args.extracted:
            validator.load_extracted(args.extracted)
        else:
            validator.load_queries()
            validator.load_test_cases()
        validator.generate_scripts(args.output)

    elif args.local:
        if args.extracted:
            validator.load_extracted(args.extracted)
        else:
            validator.load_queries()
            validator.load_test_cases()
        validator.generate_scripts(args.output)
        validator.execute_local(args.output)

    elif args.execute:
        if args.extracted:
            validator.load_extracted(args.extracted)
        else:
            validator.load_queries()
            validator.load_test_cases()
        validator.generate_scripts(args.output)
        validator.execute_local_queries(args.output)

    elif args.parse_results:
        validator.parse_results(args.output)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
