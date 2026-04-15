#!/usr/bin/env python3
"""
Step 2: Test Case Generator (sample-data-first)

TC value sources (priority order):
  0. Custom binds (workspace/input/custom-binds.json) — 고객 제공 [HIGHEST]
  1. Sample data (_samples/*.json) — real rows from Oracle tables  [PRIMARY]
  2. Java VO analysis (--java-src) — parse VO/DTO field names + types
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
    """sqlplus로 SQL 실행. oracledb가 있으면 그쪽을 직접 사용하는 게 낫지만,
    generate-test-cases의 딕셔너리 쿼리는 sqlplus 파이프라인 형태라 유지."""
    try:
        r = subprocess.run([_sqlplus(), '-S', _oracle_conn_str()],
                           input=sql, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        print(f"  WARNING: sqlplus error: {e}"); return ''

def _get_oracle_conn():
    """oracledb Python 패키지로 Oracle 접속. 없으면 None."""
    try:
        import oracledb
        dsn = f"{os.environ.get('ORACLE_HOST','')}:{os.environ.get('ORACLE_PORT','1521')}/{os.environ.get('ORACLE_SID','')}"
        return oracledb.connect(user=os.environ.get('ORACLE_USER',''),
                                password=os.environ.get('ORACLE_PASSWORD',''), dsn=dsn)
    except Exception:
        return None

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
    'boolean': True, 'Boolean': True, 'Date': '20260115', 'LocalDate': '20260115',
    'LocalDateTime': '20260115103000', 'Timestamp': '20260115103000',
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
    'sysdate': '20260115103000', 'surkey': 'SYSTEM', 'inserturkey': 'SYSTEM',
    'updateurkey': 'SYSTEM', 'delyn': 'N', 'useyn': 'Y',
    'owkey': 'DS', 'ctkey': 'HE', 'interfaceid': 'IF001', 'ifid': '1',
}

# Framework-injected pagination parameters — empty string at test time
_FRAMEWORK_PARAMS = {
    'gridpaging_rownumtype_top', 'gridpaging_rownumtype_bottom',
    'gridpaging_prefix', 'gridpaging_suffix',
    'gridpaging_rownum_top', 'gridpaging_rownum_bottom',
}

def infer_value(param, vo_fields=None, captures=None, col_stats=None, fk_values=None):
    pn, pu = param.lower(), param.upper()
    if pn in _FRAMEWORK_PARAMS: return ''
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

# ── Source 0: Custom binds (고객 제공) ────────────

def _clean_val(v):
    """값 정규화: None/NaN→'', [vals]→첫번째, 'quoted'→strip."""
    if v is None or (isinstance(v, float) and v != v):
        return ''
    if isinstance(v, list):
        return _clean_val(v[0]) if v else ''
    s = str(v)
    if s.startswith("'") and s.endswith("'") and len(s) > 1:
        s = s[1:-1]
    return s


def _stem(filename):
    """파일명 stem: prefix 제거 + .xml 제거. fuzzy 매칭용.
    daiso-xxx__ 프로젝트 prefix도 제거 (e.g. daiso-ams__foo → foo)."""
    name = Path(filename).stem if '.' in filename else filename
    name = re.sub(r'^[._]+tmp[_.]?', '', name, flags=re.I)
    # 프로젝트 prefix 제거: daiso-xxx__ 또는 daiso-xxx-sub__
    name = re.sub(r'^daiso-[\w-]+?__', '', name)
    return name


def load_custom_binds(input_dir, custom_file=None):
    """3가지 포맷의 바인드 데이터를 통합 로드.

    Returns: {key: [{param: value, ...}]}
    key = "filename.xml::queryId" (파일 스코프) 또는 "queryId" (bare, fallback)

    지원 포맷:
    a) 2레벨: {filename.xml: {queryId: {param: [vals]}}}
    b) 1레벨: {queryId: {param: "val"}}
    c) flat 리스트: [{source_file, sql_id, parameter_name, sample_value}]
    """
    custom = {}

    def _add(key, params_dict):
        cleaned = {k: _clean_val(v) for k, v in params_dict.items()}
        # 전부 빈값이면 스킵
        if any(v != '' for v in cleaned.values()):
            custom.setdefault(key, []).append(cleaned)

    # 1. custom-binds.json (format a + b)
    search_paths = [Path(input_dir) / 'custom-binds.json', Path(input_dir) / 'custom_binds.json']
    if custom_file:
        search_paths.insert(0, Path(custom_file))
    for p in search_paths:
        if not p.exists():
            continue
        try:
            raw = p.read_text(encoding='utf-8')
            raw = raw.replace(': NaN', ': ""').replace(':NaN', ':""')
            raw = raw.replace(': Infinity', ': 999999').replace(': -Infinity', ': -999999')
            data = json.loads(raw)
            if not isinstance(data, dict):
                continue

            for key, val in data.items():
                if not isinstance(val, dict):
                    if isinstance(val, list):
                        for c in val:
                            if isinstance(c, dict):
                                _add(key, c)
                    continue

                # val이 dict → 2레벨인지 1레벨인지 판별
                first_inner = next(iter(val.values()), None)
                if isinstance(first_inner, dict):
                    # Format a: 2레벨 {filename: {queryId: {param: [val]}}}
                    fname = key
                    for qid, params in val.items():
                        if isinstance(params, dict):
                            _add(f"{fname}::{qid}", params)
                elif isinstance(first_inner, list) and first_inner and isinstance(first_inner[0], dict):
                    # {filename: {queryId: [{params}]}}
                    fname = key
                    for qid, cases in val.items():
                        if isinstance(cases, list):
                            for c in cases:
                                if isinstance(c, dict):
                                    _add(f"{fname}::{qid}", c)
                else:
                    # Format b: 1레벨 {queryId: {param: "val"}}
                    _add(key, val)

            print(f"  Source-Custom: {len(custom)} keys from {p.name}")
        except Exception as e:
            print(f"  WARNING: {p.name} parse error: {e}")
        break

    # 2. bind-variable-samples/ (format c: flat 리스트)
    samples_dirs = [
        Path(input_dir) / 'daiso-bind-variable-samples',
        Path(input_dir) / 'bind-variable-samples',
        Path(input_dir).parent / 'daiso-bind-variable-samples',
    ]
    for sdir in samples_dirs:
        if not sdir.exists():
            continue
        loaded = 0
        grouped = {}  # (source_file, sql_id) → {param: value}
        for jf in sorted(sdir.glob('*.json')):
            try:
                with open(jf, encoding='utf-8') as _f:
                    rows = json.load(_f)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    sf = row.get('source_file', '')
                    sid = row.get('sql_id', '')
                    pname = row.get('parameter_name', '')
                    pval = row.get('sample_value')
                    if sf and sid and pname:
                        gkey = (sf, sid)
                        if gkey not in grouped:
                            grouped[gkey] = {}
                        cv = _clean_val(pval)
                        if cv:
                            grouped[gkey][pname] = cv
                        loaded += 1
            except Exception:
                continue
        for (sf, sid), params in grouped.items():
            if params:
                _add(f"{sf}::{sid}", params)
        if loaded:
            print(f"  Source-BindSamples: {loaded} rows, {len(grouped)} queries from {sdir.name}/")

    print(f"  Custom total: {len(custom)} keys ({sum(len(v) for v in custom.values())} TC sets)")
    return custom

def _tables(sql):
    skip = {'DUAL','SELECT','WHERE','SET','VALUES','AND','OR','NOT','NULL'}
    return [t.upper() for t in re.findall(r'\b(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)', sql, re.I) if t.upper() not in skip]

def _params(sql):
    return list(dict.fromkeys(re.findall(r'#\{(\w+)\}', sql)))

def _foreach_collections(q):
    """Extract <foreach collection="X"> names from parsed query branches."""
    collections = set()
    raw = q.get('sql_raw', '')
    for b in q.get('sql_branches', []):
        raw += ' ' + b.get('sql', '') + ' ' + b.get('condition', '')
    # XML attribute: collection="paramName"
    for m in re.findall(r'collection\s*=\s*["\'](\w+)["\']', raw):
        collections.add(m)
    # Also check raw XML text if available
    xml_text = q.get('xml_text', '')
    for m in re.findall(r'collection\s*=\s*["\'](\w+)["\']', xml_text):
        collections.add(m)
    return list(collections)

def build_query_tcs(qid, q, sample_data, vo_map, pt_map, captures, col_stats, fk_values, table_rows, custom_binds=None, filename=None):
    raw = q.get('sql_raw', '')
    for b in q.get('sql_branches', []): raw += ' ' + b.get('sql', '')
    params = _params(raw)
    # foreach collection 파라미터도 포함 (더미 리스트 필요)
    foreach_cols = _foreach_collections(q)
    if not params and not foreach_cols:
        # 파라미터 없는 쿼리도 빈 TC 생성 (EXPLAIN/Execute 검증용)
        return [{'name': 'no_params', 'params': {}, 'source': 'NO_PARAMS'}]
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

    # Priority 0: Custom binds (고객 제공 — 최우선)
    # 매칭 순서: 정확키 → stem 매칭 → bare qid (fallback)
    custom_cases = None
    if custom_binds:
        # 1) 정확: filename::qid
        custom_key = f"{filename}::{qid}" if filename else qid
        custom_cases = custom_binds.get(custom_key)
        # 2) stem 매칭: prefix/suffix 차이 무시
        if not custom_cases and filename:
            fn_stem = _stem(filename)
            for ck, cv in custom_binds.items():
                if '::' in ck:
                    ck_file, ck_qid = ck.split('::', 1)
                    if ck_qid == qid and _stem(ck_file) == fn_stem:
                        custom_cases = cv
                        break
        # 3) bare qid (파일 스코프 없는 1레벨 키)
        if not custom_cases:
            custom_cases = custom_binds.get(qid)
    if custom_cases:
        for i, cb in enumerate(custom_cases):
            binds = dict(cb) if isinstance(cb, dict) else {}
            # 고객이 안 준 나머지 파라미터는 추론으로 채움
            for p in params:
                if p not in binds:
                    binds[p] = infer_value(p, vo_fields, captures, col_stats, fk_values)
            # foreach collection에 더미 리스트 (고객이 안 줬으면)
            for fc in foreach_cols:
                if fc not in binds:
                    binds[fc] = ['1', '2']
            _add(f'custom_{i+1}', binds, 'CUSTOM')

    # Priority 1: Sample data TCs (sample_row_1, _2, _3)
    if sample_data:
        for idx in range(3):
            sb, matched = build_sample_tc(params, tables, sample_data, row_idx=idx)
            if not sb: break
            full = dict(sb)
            for p in params:
                if p not in full:
                    full[p] = infer_value(p, vo_fields, captures, col_stats, fk_values)
                elif full[p] is None:
                    # sample_value가 None → 추론값으로 대체 (null이면 MyBatis 렌더링 실패)
                    full[p] = infer_value(p, vo_fields, captures, col_stats, fk_values)
            if _dup(full): break
            _add(f'sample_row_{idx+1}', full, 'SAMPLE_DATA')

    # Priority 2: Default TC (inferred)
    default = {p: infer_value(p, vo_fields, captures, col_stats, fk_values) for p in params}
    # foreach collection에 더미 리스트 추가 (OGNL null.iterator() 방지)
    for fc in foreach_cols:
        if fc not in default:
            default[fc] = ['1', '2']
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
    ap = argparse.ArgumentParser(description='Step 2: TC Generator (sample-data-first)')
    ap.add_argument('--results-dir', default='workspace/results')
    ap.add_argument('--samples-dir', default=None, help='Sample data dir (default: <results>/_samples)')
    ap.add_argument('--output-dir', default=None, help='Output dir for per-file TCs and merged-tc.json (default: write alongside parsed.json + <results>/_test-cases/)')
    ap.add_argument('--custom-binds', default=None, help='Custom binds JSON path (default: workspace/input/custom-binds.json)')
    ap.add_argument('--java-src', default=None, help='Java source dir for VO parsing')
    ap.add_argument('--skip-oracle', action='store_true')
    ap.add_argument('--dml-row-limit', type=int, default=10000)
    args = ap.parse_args()

    global DML_ROW_LIMIT
    DML_ROW_LIMIT = args.dml_row_limit
    results_dir = Path(args.results_dir)
    samples_dir = args.samples_dir or str(results_dir / '_samples')
    output_dir = Path(args.output_dir) if args.output_dir else None
    print("=== Step 2: Test Case Generator ===\n")

    # Collect sources — custom-binds 경로 지원
    custom_binds_dir = args.custom_binds
    if custom_binds_dir and Path(custom_binds_dir).is_file():
        # 파일 직접 지정
        custom_binds = load_custom_binds(str(Path(custom_binds_dir).parent), Path(custom_binds_dir).name)
    elif custom_binds_dir and Path(custom_binds_dir).is_dir():
        custom_binds = load_custom_binds(custom_binds_dir)
    else:
        # 기본: workspace/input/ 또는 pipeline/shared/
        for cdir in ['workspace/input', 'pipeline/shared']:
            if Path(cdir).exists():
                custom_binds = load_custom_binds(cdir)
                if custom_binds:
                    break
        else:
            custom_binds = {}
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
        filename = parsed.get('source_file', parsed_path.parent.name)
        for q in parsed.get('queries', []):
            qid = q.get('query_id') or q.get('id', '')
            tcs = build_query_tcs(qid, q, sample_data, vo_map, pt_map,
                                  captures, col_stats, fk_values, table_rows, custom_binds, filename)
            if tcs:
                file_tc[qid] = tcs; total_cases += len(tcs)
                for c in tcs: source_counts[c['source']] = source_counts.get(c['source'], 0) + 1
        if file_tc:
            # output-dir 지정 시 per-file TC를 별도 디렉토리에 저장
            if output_dir:
                filename_base = parsed.get('source_file', parsed_path.parent.parent.name)
                out_tc_dir = output_dir / filename_base / 'v1'
                out_tc_dir.mkdir(parents=True, exist_ok=True)
                tc_out_path = out_tc_dir / 'test-cases.json'
            else:
                tc_out_path = parsed_path.parent / 'test-cases.json'
            tc_out_path.write_text(
                json.dumps(file_tc, indent=2, ensure_ascii=False), encoding='utf-8')
            total_files += 1

    # Merged TC for MyBatis extractor
    # null_test, empty_string TC는 제외 — MyBatis 동적 SQL이 불완전하게 렌더링됨
    # custom, sample_row, default, boundary, bind_capture, fk_sample만 포함
    _SKIP_TC_NAMES = {'null_test', 'empty_string'}
    merged_tc = {}
    for parsed_path in sorted(results_dir.glob('*/v1/parsed.json')):
        # output-dir 지정 시 per-file TC 경로도 확인
        tc_paths = [parsed_path.parent / 'test-cases.json']
        if output_dir:
            filename_base = parsed_path.parent.parent.name
            tc_paths.insert(0, output_dir / filename_base / 'v1' / 'test-cases.json')
        tc_path = None
        for tp in tc_paths:
            if tp.exists():
                tc_path = tp
                break
        if not tc_path: continue
        try: ftcs = json.loads(tc_path.read_text(encoding='utf-8'))
        except Exception: continue
        # filename_base 추출 (parsed_path 기준)
        filename_base = parsed_path.parent.parent.name
        if not filename_base.endswith('.xml'):
            filename_base = filename_base + '.xml'
        for qid, cases in ftcs.items():
            # 실값이 있는 TC만 (null_test/empty_string 제외)
            pl = [c['params'] for c in cases
                  if c.get('params') is not None and c.get('name', '') not in _SKIP_TC_NAMES
                  and not all(v is None for v in c['params'].values())]
            # 파라미터 없는 쿼리도 빈 TC 포함 (검증용)
            if not pl and any(c.get('source') == 'NO_PARAMS' for c in cases):
                pl = [{}]
            if pl:
                # 키: filename::qid (프로젝트 간 동명 쿼리 충돌 방지) + bare qid (fallback 호환)
                merged_tc[f"{filename_base}::{qid}"] = pl
                if qid not in merged_tc:  # bare qid는 첫 등장만 (충돌 방지)
                    merged_tc[qid] = pl

    # merged-tc.json 출력 위치: --output-dir 지정 시 output_dir/merged-tc.json, 아니면 기존 경로
    if output_dir:
        merged_path = output_dir / 'merged-tc.json'
    else:
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
        log_activity('STEP_END', agent='generate-test-cases', step='step_2',
                     detail=f"TC: {total_files} files, {total_cases} cases "
                            f"(sample:{source_counts.get('SAMPLE_DATA',0)}, "
                            f"capture:{source_counts.get('BIND_CAPTURE',0)}, "
                            f"fk:{source_counts.get('FK_SAMPLE',0)})")
    except Exception: pass

if __name__ == '__main__':
    main()
