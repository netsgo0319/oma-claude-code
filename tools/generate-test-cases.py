#!/usr/bin/env python3
"""
Phase 2.5: Test Case Generator (sample-data-first)

TC value sources (priority order):
  1. Java VO analysis (--java-src) — parse VO/DTO field names + types
  2. Sample data (_samples/*.json) — real rows from Oracle tables  [PRIMARY]
  3. V$SQL_BIND_CAPTURE — captured bind values from production
  4. ALL_TAB_COL_STATISTICS — MIN/MAX boundary values
  5. ALL_CONSTRAINTS (FK) — sampled values from referenced tables
  6. Name/type inference — fallback

Core principle: No static XML tag manipulation. All SQL comes from MyBatis engine.

Output:
    workspace/results/{file}/v1/test-cases.json (per-file)
    workspace/results/_test-cases/merged-tc.json (for MyBatis extractor)
"""
import json, re, os, sys, subprocess, argparse
from pathlib import Path

# ── Oracle helpers ──────────────────────────────

def _oracle_conn_str():
    u, p, h = (os.environ.get(k, '') for k in ('ORACLE_USER', 'ORACLE_PASSWORD', 'ORACLE_HOST'))
    port, sid = os.environ.get('ORACLE_PORT', '1521'), os.environ.get('ORACLE_SID', '')
    if os.environ.get('ORACLE_CONN_TYPE') == 'sid':
        return f"{u}/{p}@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={h})(PORT={port}))(CONNECT_DATA=(SID={sid})))"
    return f"{u}/{p}@{h}:{port}/{sid}"

def _sqlplus():
    for p in ['/opt/oracle/instantclient_23_3/sqlplus', '/usr/bin/sqlplus']:
        if os.path.exists(p): return p
    return 'sqlplus'

def _run_sql(sql, timeout=120):
    try:
        r = subprocess.run([_sqlplus(), '-S', _oracle_conn_str()],
                           input=sql, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        print(f"  WARNING: sqlplus error: {e}"); return ''

def _ora_ok():
    import shutil
    return bool(os.environ.get('ORACLE_USER') and os.environ.get('ORACLE_HOST') and shutil.which('sqlplus'))

def _schema():
    return os.environ.get('ORACLE_SCHEMA', os.environ.get('ORACLE_USER', '')).upper()

_SQL_HDR = "SET PAGESIZE 0 FEEDBACK OFF LINESIZE 1000 TRIMSPOOL ON\n"

# ── Source 1: Java VO analysis ──────────────────

_JAVA_FIELD_RE = re.compile(r'private\s+(\w+(?:<.*?>)?)\s+(\w+)\s*;')
JAVA_TYPE_DEFAULTS = {
    'String': 'TEST', 'int': 1, 'Integer': 1, 'long': 1, 'Long': 1,
    'double': 1.0, 'Double': 1.0, 'float': 1.0, 'Float': 1.0, 'BigDecimal': 1,
    'boolean': True, 'Boolean': True, 'Date': '2026-01-15', 'LocalDate': '2026-01-15',
    'LocalDateTime': '2026-01-15 10:30:00', 'Timestamp': '2026-01-15 10:30:00',
}

def parse_java_vo(java_src_dir):
    """Returns {fqcn: {field: java_type}}."""
    vo_map = {}
    src = Path(java_src_dir)
    if not src.is_dir(): return vo_map
    for jf in src.rglob('*.java'):
        txt = jf.read_text(encoding='utf-8', errors='ignore')
        pkg = re.search(r'package\s+([\w.]+)\s*;', txt)
        cls = re.search(r'class\s+(\w+)', txt)
        if not pkg or not cls: continue
        fields = {m.group(2): m.group(1) for m in _JAVA_FIELD_RE.finditer(txt)}
        if fields: vo_map[f"{pkg.group(1)}.{cls.group(1)}"] = fields
    if vo_map:
        print(f"  Source-VO: {len(vo_map)} classes, {sum(len(f) for f in vo_map.values())} fields")
    return vo_map

# ── Source 2: Sample data ───────────────────────

def load_sample_data(samples_dir):
    """Load _samples/<TABLE>.json. Returns {TABLE: [row_dict, ...]}."""
    samples, sdir = {}, Path(samples_dir)
    if not sdir.is_dir(): return samples
    for fp in sorted(sdir.glob('*.json')):
        try: data = json.loads(fp.read_text(encoding='utf-8'))
        except Exception: continue
        if isinstance(data, dict):
            tname, rows = data.get('table', fp.stem).upper(), data.get('rows', [])
        elif isinstance(data, list):
            tname, rows = fp.stem.upper(), data
        else: continue
        if rows: samples[tname] = rows[:20]
    if samples:
        print(f"  Source-Sample: {len(samples)} tables, {sum(len(r) for r in samples.values())} rows")
    return samples

def _match_col(param, row):
    """Fuzzy-match #{param} → column in sample row."""
    col_map = {k.upper(): k for k in row}
    pu = param.upper()
    if pu in col_map: return col_map[pu]
    snake = re.sub(r'([a-z])([A-Z])', r'\1_\2', param).upper()
    if snake in col_map: return col_map[snake]
    flat = pu.replace('_', '')
    for cu, co in col_map.items():
        if cu.replace('_', '') == flat: return co
    return None

def build_sample_tc(params, tables, sample_data, row_idx=0):
    """Returns (binds_dict, matched_count) or (None, 0)."""
    binds, matched = {}, 0
    for tbl in tables:
        rows = sample_data.get(tbl, [])
        if not rows: continue
        row = rows[row_idx % len(rows)]
        for p in params:
            if p in binds: continue
            col = _match_col(p, row)
            if col is not None:
                binds[p] = row[col]; matched += 1
    return (binds, matched) if matched > 0 else (None, 0)

# ── Source 3: parameterType from parsed.json ────

def parse_parameter_types(results_dir):
    pt_map = {}
    for pf in sorted(Path(results_dir).glob('*/v1/parsed.json')):
        try: parsed = json.loads(pf.read_text(encoding='utf-8'))
        except Exception: continue
        for q in parsed.get('queries', []):
            qid = q.get('id') or q.get('query_id', '')
            pt = q.get('parameterType') or q.get('parameter_type')
            if qid and pt: pt_map[qid] = pt
    return pt_map

# ── Oracle dictionary sources (3-5) ────────────

def _parse_pipe(output, min_cols=2):
    for line in output.split('\n'):
        parts = [p.strip() for p in line.strip().split('|')]
        if len(parts) >= min_cols and parts[0]: yield parts

def get_bind_captures():
    if not _ora_ok(): return {}
    sql = _SQL_HDR + ("SELECT DISTINCT NAME||'|'||NVL(TO_CHAR(VALUE_STRING),'NULL')"
        " FROM V$SQL_BIND_CAPTURE WHERE VALUE_STRING IS NOT NULL AND ROWNUM<=5000 ORDER BY 1;\nEXIT;\n")
    caps = {}
    for parts in _parse_pipe(_run_sql(sql, 30)):
        name, val = parts[0].lstrip(':').lower(), parts[1]
        if name and val != 'NULL': caps.setdefault(name, []).append(val)
    for k in caps: caps[k] = list(dict.fromkeys(caps[k]))[:5]
    print(f"  Source-BindCapture: {len(caps)} params, {sum(len(v) for v in caps.values())} values")
    return caps

def get_column_stats():
    if not _ora_ok(): return {}
    s = _schema()
    sql = _SQL_HDR + (f"SELECT TABLE_NAME||'|'||COLUMN_NAME||'|'||NVL(TO_CHAR(LOW_VALUE),'NULL')"
        f"||'|'||NVL(TO_CHAR(HIGH_VALUE),'NULL')||'|'||NVL(NUM_DISTINCT,0)"
        f" FROM ALL_TAB_COL_STATISTICS WHERE OWNER='{s}' AND LOW_VALUE IS NOT NULL"
        f" AND ROWNUM<=10000 ORDER BY 1,2;\nEXIT;\n")
    stats = {}
    for parts in _parse_pipe(_run_sql(sql, 60), 4):
        tbl, col, low, high = parts[0], parts[1], parts[2], parts[3]
        dist = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        if low != 'NULL':
            info = {'low': low, 'high': high, 'distinct': dist}
            stats[f"{tbl}.{col}"] = info; stats[col] = info
    print(f"  Source-ColStats: {len(stats)} columns"); return stats

def get_fk_samples():
    if not _ora_ok(): return {}
    s = _schema()
    sql = _SQL_HDR + (f"SELECT CC.TABLE_NAME||'|'||CC.COLUMN_NAME||'|'||RC.TABLE_NAME||'|'||RC.COLUMN_NAME"
        f" FROM ALL_CONS_COLUMNS CC"
        f" JOIN ALL_CONSTRAINTS C ON CC.CONSTRAINT_NAME=C.CONSTRAINT_NAME AND CC.OWNER=C.OWNER"
        f" JOIN ALL_CONS_COLUMNS RC ON C.R_CONSTRAINT_NAME=RC.CONSTRAINT_NAME AND C.R_OWNER=RC.OWNER"
        f" WHERE C.CONSTRAINT_TYPE='R' AND C.OWNER='{s}' AND ROWNUM<=3000 ORDER BY 1,2;\nEXIT;\n")
    fk_map = {}
    for parts in _parse_pipe(_run_sql(sql, 60), 4):
        fk_map[f"{parts[0]}.{parts[1]}"] = (parts[2], parts[3])
        fk_map[parts[1]] = (parts[2], parts[3])
    fk_vals, done = {}, {}
    for key, (rt, rc) in fk_map.items():
        sk = f"{rt}.{rc}"
        if sk in done: fk_vals[key] = done[sk]; continue
        out = _run_sql(_SQL_HDR + f"SELECT DISTINCT {rc} FROM {s}.{rt} WHERE {rc} IS NOT NULL AND ROWNUM<=3;\nEXIT;\n", 10)
        vals = [l.strip() for l in out.split('\n') if l.strip() and 'ERROR' not in l and 'ORA-' not in l][:3]
        if vals: done[sk] = vals; fk_vals[key] = vals
    print(f"  Source-FK: {len(fk_vals)} columns, {sum(len(v) for v in fk_vals.values())} values")
    return fk_vals

def get_table_row_counts():
    if not _ora_ok(): return {}
    s = _schema()
    sql = _SQL_HDR + f"SELECT TABLE_NAME||'|'||NVL(NUM_ROWS,0) FROM ALL_TABLES WHERE OWNER='{s}' ORDER BY 2 DESC;\nEXIT;\n"
    counts = {}
    for parts in _parse_pipe(_run_sql(sql, 30)):
        if parts[1].isdigit(): counts[parts[0]] = int(parts[1])
    print(f"  Source-RowCounts: {len(counts)} tables"); return counts

# ── Name/type inference (fallback) ──────────────

_SPECIAL = {
    'sysdate': '2026-01-15 10:30:00', 'surkey': 'SYSTEM', 'inserturkey': 'SYSTEM',
    'updateurkey': 'SYSTEM', 'delyn': 'N', 'useyn': 'Y',
    'owkey': 'DS', 'ctkey': 'HE', 'interfaceid': 'IF001', 'ifid': '1',
}

def infer_value(param, vo_fields=None, captures=None, col_stats=None, fk_values=None):
    pn, pu = param.lower(), param.upper()
    if pn in _SPECIAL: return _SPECIAL[pn]
    if vo_fields and param in vo_fields:
        base = re.sub(r'<.*?>', '', vo_fields[param])
        if base in JAVA_TYPE_DEFAULTS: return JAVA_TYPE_DEFAULTS[base]
    if captures:
        for k in [pn, pu, param]:
            if k in captures and captures[k]: return captures[k][0]
    if fk_values:
        for k in [pu, pn, param]:
            if k in fk_values and fk_values[k]: return fk_values[k][0]
    if col_stats:
        for k in [pu, pn]:
            if k in col_stats:
                try: return int(float(col_stats[k].get('low', '')))
                except (ValueError, TypeError): pass
    if any(k in pn for k in ('qty','cnt','amt','price','prc','rate','seq','no','num',
                              'idx','id','size','len','weight','page','limit','offset')): return 1
    if any(k in pn for k in ('date','day','dt','time','tm')): return '20260115'
    if pn.endswith('yn') or pn == 'yn': return 'Y'
    if any(k in pn for k in ('key','cd','code','type','div','gb','flag','stat')): return 'A1'
    if any(k in pn for k in ('nm','name','desc','msg','text','remark','note')): return 'TEST'
    return 'T'

# ── TC assembly per query ───────────────────────

DML_ROW_LIMIT = 10000
DML_TIMEOUT = 5

def _tables(sql):
    skip = {'DUAL','SELECT','WHERE','SET','VALUES','AND','OR','NOT','NULL'}
    return [t.upper() for t in re.findall(r'\b(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)', sql, re.I) if t.upper() not in skip]

def _params(sql):
    return list(dict.fromkeys(re.findall(r'#\{(\w+)\}', sql)))

def build_query_tcs(qid, q, sample_data, vo_map, pt_map, captures, col_stats, fk_values, table_rows):
    raw = q.get('sql_raw', '')
    for b in q.get('sql_branches', []): raw += ' ' + b.get('sql', '')
    params = _params(raw)
    if not params: return []
    tables = _tables(raw)
    qtype = q.get('type', 'select').lower()
    is_dml = qtype in ('insert', 'update', 'delete')
    dml_large = is_dml and table_rows and any(table_rows.get(t, 0) >= DML_ROW_LIMIT for t in tables)
    vo_fields = vo_map.get(pt_map.get(qid, '')) if vo_map else None
    cases = []

    def _add(name, binds, source):
        tc = {'name': name, 'params': binds, 'source': source}
        if dml_large:
            tc['execute_skip'] = True
            tc['skip_reason'] = f'DML on large table ({max(table_rows.get(t,0) for t in tables):,} rows)'
        if is_dml: tc['timeout'] = DML_TIMEOUT
        cases.append(tc)

    def _dup(binds): return any(c['params'] == binds for c in cases)

    # Priority 1: Sample data TCs (sample_row_1, _2, _3)
    if sample_data:
        for idx in range(3):
            sb, matched = build_sample_tc(params, tables, sample_data, row_idx=idx)
            if not sb: break
            full = dict(sb)
            for p in params:
                if p not in full: full[p] = infer_value(p, vo_fields, captures, col_stats, fk_values)
            if _dup(full): break
            _add(f'sample_row_{idx+1}', full, 'SAMPLE_DATA')

    # Priority 2: Default TC (inferred)
    default = {p: infer_value(p, vo_fields, captures, col_stats, fk_values) for p in params}
    if not _dup(default): _add('default', default, 'INFERRED')

    # DML safety: no null_test / empty_string / boundary
    if not is_dml:
        null_b = dict(default)
        for p in params[:3]: null_b[p] = None
        if null_b != default: _add('null_test', null_b, 'NULL_SEMANTICS')

        empty_b = dict(default)
        for p in params[:3]:
            if isinstance(default.get(p), str): empty_b[p] = ''
        if empty_b != default: _add('empty_string', empty_b, 'EMPTY_STRING')

        if col_stats:
            bnd = dict(default); changed = False
            for p in params:
                pu = p.upper()
                if pu in col_stats and col_stats[pu].get('high'):
                    try: bnd[p] = int(float(col_stats[pu]['high']))
                    except (ValueError, TypeError): bnd[p] = str(col_stats[pu]['high'])[:50]
                    changed = True
            if changed and bnd != default: _add('boundary', bnd, 'BOUNDARY')

    # Bind capture TC (second captured value)
    if captures:
        cap = dict(default); changed = False
        for p in params:
            for k in [p.lower(), p.upper(), p]:
                if k in captures and len(captures[k]) > 1:
                    cap[p] = captures[k][1]; changed = True; break
        if changed and not _dup(cap): _add('bind_capture', cap, 'BIND_CAPTURE')

    # FK sample TC
    if fk_values:
        fk = dict(default); changed = False
        for p in params:
            for k in [p.upper(), p.lower(), p]:
                if k in fk_values and fk_values[k]:
                    for v in fk_values[k]:
                        if v != str(default.get(p, '')): fk[p] = v; changed = True; break
                    break
        if changed and not _dup(fk): _add('fk_sample', fk, 'FK_SAMPLE')

    return cases

# ── Main ────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Phase 2.5: TC Generator (sample-data-first)')
    ap.add_argument('--results-dir', default='workspace/results')
    ap.add_argument('--samples-dir', default=None, help='Sample data dir (default: <results>/_samples)')
    ap.add_argument('--java-src', default=None, help='Java source dir for VO parsing')
    ap.add_argument('--skip-oracle', action='store_true')
    ap.add_argument('--dml-row-limit', type=int, default=10000)
    args = ap.parse_args()

    global DML_ROW_LIMIT
    DML_ROW_LIMIT = args.dml_row_limit
    results_dir = Path(args.results_dir)
    samples_dir = args.samples_dir or str(results_dir / '_samples')
    print("=== Phase 2.5: Test Case Generator (sample-data-first) ===\n")

    # Collect sources
    java_src = args.java_src or os.environ.get('JAVA_SRC_DIR', '')
    vo_map = parse_java_vo(java_src) if java_src else {}
    sample_data = load_sample_data(samples_dir)
    pt_map = parse_parameter_types(results_dir)

    if args.skip_oracle or not _ora_ok():
        captures, col_stats, fk_values, table_rows = {}, {}, {}, {}
        print("  Oracle not connected — using samples + inference only\n")
    else:
        print("  Collecting Oracle metadata...")
        captures = get_bind_captures()
        col_stats = get_column_stats()
        fk_values = get_fk_samples()
        table_rows = get_table_row_counts()
        print()

    # Generate TCs per file
    total_files, total_cases, source_counts = 0, 0, {}
    for parsed_path in sorted(results_dir.glob('*/v1/parsed.json')):
        try: parsed = json.loads(parsed_path.read_text(encoding='utf-8'))
        except Exception: continue
        file_tc = {}
        for q in parsed.get('queries', []):
            qid = q.get('query_id') or q.get('id', '')
            tcs = build_query_tcs(qid, q, sample_data, vo_map, pt_map,
                                  captures, col_stats, fk_values, table_rows)
            if tcs:
                file_tc[qid] = tcs; total_cases += len(tcs)
                for c in tcs: source_counts[c['source']] = source_counts.get(c['source'], 0) + 1
        if file_tc:
            (parsed_path.parent / 'test-cases.json').write_text(
                json.dumps(file_tc, indent=2, ensure_ascii=False), encoding='utf-8')
            total_files += 1

    # Merged TC for MyBatis extractor
    merged_tc = {}
    for parsed_path in sorted(results_dir.glob('*/v1/parsed.json')):
        tc_path = parsed_path.parent / 'test-cases.json'
        if not tc_path.exists(): continue
        try: ftcs = json.loads(tc_path.read_text(encoding='utf-8'))
        except Exception: continue
        for qid, cases in ftcs.items():
            pl = [c['params'] for c in cases if c.get('params')]
            if pl: merged_tc[qid] = pl
    merged_path = results_dir / '_test-cases' / 'merged-tc.json'
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    merged_path.write_text(json.dumps(merged_tc, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"  Merged TC: {merged_path} ({len(merged_tc)} queries)")

    # Summary
    print(f"\n=== Done ===\n  Files: {total_files}\n  Test cases: {total_cases}\n  Sources:")
    for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
        if cnt: print(f"    {src}: {cnt}")

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tracking_utils import log_activity
        log_activity('PHASE_END', agent='generate-test-cases', phase='phase_2.5',
                     detail=f"TC: {total_files} files, {total_cases} cases "
                            f"(sample:{source_counts.get('SAMPLE_DATA',0)}, "
                            f"capture:{source_counts.get('BIND_CAPTURE',0)}, "
                            f"fk:{source_counts.get('FK_SAMPLE',0)})")
    except Exception: pass

if __name__ == '__main__':
    main()
