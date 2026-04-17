#!/usr/bin/env python3
"""
Oracle to PostgreSQL Mechanical Converter
Handles rule-based SQL conversions (L0~L2) in MyBatis/iBatis XML files.

Handles:
- CDATA blocks (converts inside them)
- Multi-line function calls (NVL(\n\t...\n) patterns)
- Nested function calls
- 40+ Oracle→PostgreSQL conversion rules
- ROWNUM 3-level pagination -> LIMIT/OFFSET auto-conversion
- FETCH FIRST N ROWS ONLY (12c+) -> LIMIT
- OFFSET N ROWS FETCH NEXT M ROWS ONLY -> LIMIT M OFFSET N
- ROWNUM = 1 -> LIMIT 1
- Residual Oracle pattern scanner with line numbers and context
- (+) outer join detection and reporting (not auto-converted)

Does NOT handle (left for LLM):
- CONNECT BY / START WITH (structural transformation)
- MERGE INTO (structural transformation)
- PIVOT / UNPIVOT
- PL/SQL procedure calls
- Complex analytical patterns (KEEP DENSE_RANK etc)
- (+) outer joins (structural FROM/WHERE restructuring)

Usage:
    python3 tools/oracle-to-pg-converter.py <input.xml> <output.xml> [--report report.json]
    python3 tools/oracle-to-pg-converter.py --dir workspace/input/ --outdir workspace/output/ [--report-dir workspace/results/]
    python3 tools/oracle-to-pg-converter.py input.xml output.xml --report report.json --update-progress workspace/progress.json
    python3 tools/oracle-to-pg-converter.py input.xml output.xml --report report.json --diff workspace/results/file/v1/conversion-diff.txt
"""

import re
import sys
import os
import json
import argparse
import difflib
from pathlib import Path
from copy import deepcopy
from datetime import datetime


class OracleToPgConverter:
    """Rule-based Oracle to PostgreSQL SQL converter."""

    def __init__(self):
        self.stats = {
            'total_replacements': 0,
            'rules_applied': {},
            'unconverted': [],
            'cdata_conversions': 0,
            'residual_oracle_patterns': [],
        }

    def convert_file(self, input_path, output_path, report_path=None,
                     progress_path=None, diff_path=None, tracking_dir=None):
        """Convert a single XML file."""
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()

        converted, report = self.convert_xml_content(content, os.path.basename(input_path))

        # Write output
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(converted)

        # Update query-level tracking
        if tracking_dir:
            try:
                import time
                from tracking_utils import TrackingManager
                tm = TrackingManager(tracking_dir)
                before_queries = self._extract_queries_from_xml(content)
                after_queries = self._extract_queries_from_xml(converted)
                tracked = 0
                for qid in before_queries:
                    pg_sql = after_queries.get(qid, before_queries[qid])
                    rules = list(self.stats.get('rules_applied', {}).keys())
                    # 공백 정규화 후 비교 (줄바꿈/탭 차이 무시)
                    before_norm = re.sub(r'\s+', ' ', before_queries[qid]).strip()
                    after_norm = re.sub(r'\s+', ' ', pg_sql).strip()
                    changed = before_norm != after_norm
                    tm.update_conversion(
                        qid, pg_sql,
                        'rule' if changed else 'no_change',
                        rules if changed else []
                    )
                    tracked += 1
                if tracked:
                    print(f"  Query tracking updated: {tracked} queries")
            except Exception as e:
                print(f"  Warning: Could not update query tracking: {e}")

        # Auto-update progress.json
        try:
            from tracking_utils import TrackingManager
            # Derive progress.json path from output_path
            progress_path = str(Path(output_path).parent.parent / 'progress.json')
            if not Path(progress_path).exists():
                progress_path = 'workspace/progress.json'
            fname = os.path.basename(input_path)
            unconverted_count = report.get('unconverted_count', len(report.get('unconverted', [])))
            TrackingManager.update_progress(
                progress_path, fname,
                status='converted',
                phase=2,
                queries_total=report.get('total_queries', 0),
            )
        except Exception:
            pass

        # Activity log
        try:
            from tracking_utils import log_activity
            log_activity('STEP_END', agent='oracle-to-pg-converter', step='step_1',
                         file=os.path.basename(input_path),
                         detail=f"Converted: {report.get('total_replacements',0)} replacements, "
                                f"{len(report.get('unconverted',[]))} unconverted, "
                                f"{len(report.get('residual_oracle_patterns',[]))} residual")
        except Exception:
            pass

        # Write report
        if report_path:
            os.makedirs(os.path.dirname(report_path) if os.path.dirname(report_path) else '.', exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

        # Generate diff
        if diff_path:
            self._generate_diff(content, converted, input_path, output_path, diff_path)

        # Update progress
        if progress_path:
            self._update_progress(progress_path, input_path, report)

        return report

    def convert_sql(self, sql):
        """단일 SQL 변환. /convert-query 스킬용.
        Returns: (converted_sql, report_dict)"""
        self.stats = {
            'total_replacements': 0,
            'rules_applied': {},
            'unconverted': [],
        }
        converted = self._apply_all_rules(sql)
        residual = self._scan_residual_patterns(converted)
        report = {
            'rules_applied': dict(self.stats.get('rules_applied', {})),
            'residual_oracle_patterns': residual,
            'changed': sql.strip() != converted.strip(),
        }
        return converted, report

    def convert_xml_content(self, content, filename=""):
        """Convert XML content, handling CDATA blocks and regular text."""
        self.stats = {
            'total_replacements': 0,
            'rules_applied': {},
            'unconverted': [],
            'cdata_conversions': 0,
            'residual_oracle_patterns': [],
            'filename': filename,
        }

        # Process CDATA blocks separately
        # Pattern: <![CDATA[...]]>
        def convert_cdata(match):
            cdata_content = match.group(1)
            converted = self._apply_all_rules(cdata_content)
            if converted != cdata_content:
                self.stats['cdata_conversions'] += 1
            return f'<![CDATA[{converted}]]>'

        # First, convert inside CDATA blocks
        content = re.sub(
            r'<!\[CDATA\[(.*?)\]\]>',
            convert_cdata,
            content,
            flags=re.DOTALL
        )

        # Then convert SQL in text nodes (between XML tags, not inside tag attributes)
        # CRITICAL: Use greedy matching to capture ENTIRE text nodes including multi-line
        # function calls like NVL(\n\tSUM(...),\n\t0\n). Non-greedy (+?) would split
        # these across multiple matches, causing partial conversion bugs.
        def convert_text_node(match):
            prefix = match.group(1)  # >
            text = match.group(2)    # text content (greedy — captures full multi-line text)
            suffix = match.group(3)  # <
            converted = self._apply_all_rules(text)
            # If conversion introduced bare < or <= that wasn't in original,
            # wrap in CDATA to prevent XML parse errors
            if converted != text and '<' in converted and '<' not in text:
                converted = f'<![CDATA[{converted}]]>'
            return f'{prefix}{converted}{suffix}'

        # Match text between XML tags — greedy [^<]+ to capture full text nodes
        # This ensures multi-line NVL(SUM(...),0) is captured as ONE text node
        content = re.sub(
            r'(>)([^<]+)(<)',
            convert_text_node,
            content,
            flags=re.DOTALL
        )

        # Detect unconverted Oracle patterns
        self._detect_unconverted(content)

        # Scan for residual Oracle patterns with line numbers and context
        self._scan_residual_patterns(content)

        report = {
            'filename': filename,
            'total_replacements': self.stats['total_replacements'],
            'rules_applied': self.stats['rules_applied'],
            'cdata_conversions': self.stats['cdata_conversions'],
            'unconverted_count': len(self.stats['unconverted']),
            'unconverted': self.stats['unconverted'],
            'residual_oracle_patterns': self.stats['residual_oracle_patterns'],
        }

        return content, report

    def _apply_all_rules(self, sql):
        """Apply all conversion rules to a SQL string."""
        original = sql

        # Order matters: apply more specific rules first

        # 1. FROM DUAL removal (before function conversions)
        sql = self._convert_from_dual(sql)

        # 2. Sequence conversion (before function conversions)
        sql = self._convert_sequences(sql)

        # 3. Package-qualified functions first (before generic function names)
        #    DBMS_LOB.INSTR must be converted before INSTR, etc.
        sql = self._convert_dbms_lob_substr(sql)
        sql = self._convert_dbms_lob_getlength(sql)
        sql = self._convert_dbms_lob_instr(sql)
        sql = self._convert_dbms_random(sql)

        # 4. Function conversions (multi-line aware)
        # NVL2 before NVL (more specific first)
        sql = self._convert_nvl2(sql)
        # NVL/DECODE: 반복 적용하여 중첩 패턴 처리 (NVL(a, NVL(b, c)) 등)
        for _ in range(5):  # 최대 5단계 중첩까지
            prev = sql
            sql = self._convert_nvl(sql)
            sql = self._convert_decode(sql)
            if sql == prev:
                break  # 더 이상 변환할 게 없으면 중단
        sql = self._convert_sysdate(sql)
        sql = self._convert_systimestamp(sql)
        sql = self._convert_timestamp_arithmetic(sql)
        sql = self._convert_listagg(sql)
        sql = self._convert_wm_concat(sql)
        sql = self._convert_to_number(sql)
        sql = self._convert_trunc_date(sql)
        sql = self._convert_add_months(sql)
        sql = self._convert_months_between(sql)
        sql = self._convert_last_day(sql)
        sql = self._convert_instr(sql)
        sql = self._convert_length(sql)  # LENGTH is compatible but document it

        # 5. REGEXP functions
        sql = self._convert_regexp_like(sql)
        sql = self._convert_regexp_replace(sql)
        sql = self._convert_regexp_substr(sql)

        # 6. Outer join (+) syntax
        sql = self._convert_outer_join_plus(sql)

        # 7. MINUS -> EXCEPT
        sql = self._convert_minus(sql)

        # 8a. ROWNUM 3-level pagination pattern (must run before simple ROWNUM)
        sql = self._convert_rownum_pagination(sql)

        # 8b. ROWNUM = 1 -> LIMIT 1
        sql = self._convert_rownum_equals_one(sql)

        # 8c. ROWNUM simple cases
        sql = self._convert_rownum_simple(sql)

        # 8d. Oracle 12c+ FETCH FIRST / OFFSET-FETCH
        sql = self._convert_offset_fetch(sql)
        sql = self._convert_fetch_first(sql)

        # 9. Date format strings in TO_DATE/TO_CHAR
        sql = self._convert_date_formats(sql)

        # 10. Oracle hints (comment or remove)
        sql = self._convert_hints(sql)

        # 11. Empty string = NULL semantics warning (add comment)
        # (don't auto-convert, just detect)

        # 12. GREATEST/LEAST NULL handling (auto COALESCE wrap)
        sql = self._convert_greatest_least(sql)

        # 13. BITAND
        sql = self._convert_bitand(sql)

        # 14. DELETE without FROM (Oracle allows, PG requires FROM)
        sql = self._convert_delete_from(sql)

        # 14b. UPDATE SET alias.col -> SET col (PG doesn't allow alias in SET)
        sql = self._convert_update_set_alias(sql)

        # 15. CONNECT BY LEVEL <= N -> generate_series(1, N)
        sql = self._convert_connect_by_level(sql)

        # 16. PKG_CRYPTO.DECRYPT/ENCRYPT -> TODO tagging
        sql = self._convert_pkg_crypto(sql)

        # 17. LPAD(numeric) -> LPAD(expr::TEXT)
        sql = self._convert_lpad_numeric(sql)

        # 18. TO_CLOB(expr) -> expr::TEXT
        sql = self._convert_to_clob(sql)

        # 19. TO_DATE single arg -> TO_DATE(expr, 'YYYYMMDD')
        sql = self._convert_to_date_single(sql)

        # 20. date_column - numeric -> date_column - numeric::INTEGER
        sql = self._convert_date_column_arithmetic(sql)

        # 21. Subquery alias: FROM (subquery) → FROM (subquery) AS sub_N
        # Oracle allows subqueries without alias, PG requires it
        sql = self._convert_subquery_alias(sql)

        # 22. TO_CHAR single arg: TO_CHAR(expr) → (expr)::TEXT
        # PG TO_CHAR requires format arg; single-arg = cast to text
        sql = self._convert_to_char_single(sql)

        # 22b. REPLACE(str, old) 2인자 → REPLACE(str, old, '') 3인자
        sql = self._convert_replace_two_arg(sql)

        # 23. REGEXP_INSTR(col, pattern) > 0 → col ~ pattern
        sql = self._convert_regexp_instr(sql)

        # 24. SUBSTRB(expr, start, len) → SUBSTRING(expr FROM start FOR len)
        sql = self._convert_substrb(sql)

        # 25. COUNT 쿼리 ORDER BY 제거 (무의미, PG 에러 가능)
        sql = self._convert_count_order_by(sql)

        if sql != original:
            self.stats['total_replacements'] += 1

        return sql

    def _count_rule(self, rule_name):
        """Track rule application count."""
        self.stats['rules_applied'][rule_name] = self.stats['rules_applied'].get(rule_name, 0) + 1

    # ========== Function Converters (multi-line aware) ==========

    def _find_matching_paren(self, text, start):
        """Find the matching closing parenthesis, handling nesting and multi-line."""
        depth = 0
        i = start
        while i < len(text):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
                if depth == 0:
                    return i
            elif text[i] == "'":
                # Skip string literals
                i += 1
                while i < len(text) and text[i] != "'":
                    if text[i] == "'" and i + 1 < len(text) and text[i+1] == "'":
                        i += 2  # escaped quote
                        continue
                    i += 1
            i += 1
        return -1  # unmatched

    def _split_args(self, args_str):
        """Split function arguments respecting nesting and strings."""
        args = []
        depth = 0
        current = []
        in_string = False

        for char in args_str:
            if char == "'" and not in_string:
                in_string = True
                current.append(char)
            elif char == "'" and in_string:
                in_string = False
                current.append(char)
            elif in_string:
                current.append(char)
            elif char == '(':
                depth += 1
                current.append(char)
            elif char == ')':
                depth -= 1
                current.append(char)
            elif char == ',' and depth == 0:
                args.append(''.join(current).strip())
                current = []
            else:
                current.append(char)

        if current:
            args.append(''.join(current).strip())

        return args

    def _convert_nvl(self, sql):
        """NVL(a, b) -> COALESCE(a, b) -- multi-line aware.
        Handles nested NVL by skipping matches inside already-converted regions."""
        pattern = re.compile(r'\bNVL\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches that fall inside an already-converted region
            if start < last_end:
                continue
            paren_start = match.end() - 1  # position of (
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 2:
                result.append(sql[last_end:start])
                result.append(f'COALESCE({args[0]}, {args[1]})')
                last_end = paren_end + 1
                self._count_rule('NVL->COALESCE')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_nvl2(self, sql):
        """NVL2(a, b, c) -> CASE WHEN a IS NOT NULL THEN b ELSE c END."""
        pattern = re.compile(r'\bNVL2\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 3:
                result.append(sql[last_end:start])
                result.append(f'CASE WHEN {args[0]} IS NOT NULL THEN {args[1]} ELSE {args[2]} END')
                last_end = paren_end + 1
                self._count_rule('NVL2->CASE')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_decode(self, sql):
        """DECODE(expr, val1, result1, val2, result2, ..., default) -> CASE."""
        pattern = re.compile(r'\bDECODE\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) >= 3:
                expr = args[0]
                pairs = args[1:]
                case_parts = [f'CASE {expr}']

                i = 0
                while i < len(pairs) - 1:
                    val = pairs[i]
                    res = pairs[i + 1]
                    if val.strip().upper() == 'NULL':
                        # DECODE treats NULL comparison specially
                        case_parts.append(f' WHEN {expr} IS NULL THEN {res}')
                    else:
                        case_parts.append(f' WHEN {val} THEN {res}')
                    i += 2

                # Odd number of remaining args = default
                if len(pairs) % 2 == 1:
                    case_parts.append(f' ELSE {pairs[-1]}')

                case_parts.append(' END')
                result.append(sql[last_end:start])
                result.append(''.join(case_parts))
                last_end = paren_end + 1
                self._count_rule('DECODE->CASE')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_sysdate(self, sql):
        """SYSDATE -> CURRENT_TIMESTAMP. Excludes #{sysdate} MyBatis parameters."""
        new_sql = re.sub(r'(?<!#\{)\bSYSDATE\b(?!\})', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
        if new_sql != sql:
            self._count_rule('SYSDATE->CURRENT_TIMESTAMP')
        return new_sql

    def _convert_systimestamp(self, sql):
        """SYSTIMESTAMP -> CURRENT_TIMESTAMP."""
        new_sql = re.sub(r'\bSYSTIMESTAMP\b', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
        if new_sql != sql:
            self._count_rule('SYSTIMESTAMP->CURRENT_TIMESTAMP')
        return new_sql

    def _convert_timestamp_arithmetic(self, sql):
        """CURRENT_TIMESTAMP - 30 -> CURRENT_TIMESTAMP - INTERVAL '30 days'.
        Oracle allows date - number (days), PostgreSQL requires INTERVAL.
        Also handles SYSDATE - 30 remnants and DATE + numeric."""
        # Pattern: timestamp/date expression - bare integer (not already INTERVAL)
        # Match: CURRENT_TIMESTAMP - 30, CURRENT_DATE - 7, etc.
        def replace_minus(match):
            expr = match.group(1)
            num = match.group(2)
            self._count_rule('TIMESTAMP-N->INTERVAL')
            return f"{expr} - INTERVAL '{num} days'"

        def replace_plus(match):
            expr = match.group(1)
            num = match.group(2)
            self._count_rule('TIMESTAMP+N->INTERVAL')
            return f"{expr} + INTERVAL '{num} days'"

        # CURRENT_TIMESTAMP - <number> or CURRENT_DATE - <number>
        new_sql = re.sub(
            r'\b(CURRENT_TIMESTAMP|CURRENT_DATE|NOW\(\))\s*-\s*(\d+)\b(?!\s*(?:days|hours|minutes|seconds|months|years))',
            replace_minus, sql, flags=re.IGNORECASE)
        new_sql = re.sub(
            r'\b(CURRENT_TIMESTAMP|CURRENT_DATE|NOW\(\))\s*\+\s*(\d+)\b(?!\s*(?:days|hours|minutes|seconds|months|years))',
            replace_plus, new_sql, flags=re.IGNORECASE)

        return new_sql

    def _convert_from_dual(self, sql):
        """FROM DUAL -> remove. Handles whitespace variants (tabs, newlines) and subqueries."""
        # Match FROM DUAL with any whitespace (including newlines, tabs)
        new_sql = re.sub(r'\s+FROM\s+DUAL\b', '', sql, flags=re.IGNORECASE | re.DOTALL)
        if new_sql != sql:
            self._count_rule('FROM_DUAL->removed')
        return new_sql

    def _convert_sequences(self, sql):
        """sequence.NEXTVAL -> nextval('sequence'), sequence.CURRVAL -> currval('sequence').
        Handles schema-qualified: SCHEMA.SEQ.NEXTVAL -> nextval('schema.seq')."""
        def replace_seq(match):
            full = match.group(0)
            # Check for schema.seq.NEXTVAL (3-part)
            m3 = re.match(r'(\w+)\.(\w+)\.(NEXTVAL|CURRVAL)', full, re.IGNORECASE)
            if m3:
                schema, seq_name, func = m3.group(1), m3.group(2), m3.group(3).lower()
                pg_func = 'nextval' if 'next' in func else 'currval'
                self._count_rule(f'sequence.{func}->{pg_func}()')
                return f"{pg_func}('{schema.lower()}.{seq_name.lower()}')"
            # 2-part: SEQ.NEXTVAL
            seq_name = match.group(1)
            func = match.group(2).lower()
            pg_func = 'nextval' if 'next' in func else 'currval'
            self._count_rule(f'sequence.{func}->{pg_func}()')
            return f"{pg_func}('{seq_name.lower()}')"

        # 3-part first (schema.seq.NEXTVAL)
        new_sql = re.sub(
            r'(\w+)\.(\w+)\.(NEXTVAL|CURRVAL)',
            replace_seq,
            sql, flags=re.IGNORECASE
        )
        # 2-part fallback (seq.NEXTVAL)
        new_sql = re.sub(
            r'(\w+)\.(NEXTVAL|CURRVAL)',
            replace_seq,
            sql,
            flags=re.IGNORECASE
        )
        return new_sql

    def _convert_listagg(self, sql):
        """LISTAGG(col, sep) WITHIN GROUP (ORDER BY ...) -> STRING_AGG(col, sep ORDER BY ...)."""
        pattern = re.compile(
            r'\bLISTAGG\s*\((.*?)\)\s*WITHIN\s+GROUP\s*\(\s*ORDER\s+BY\s+(.*?)\)',
            re.IGNORECASE | re.DOTALL
        )

        def replace_listagg(match):
            args = match.group(1).strip()
            order_by = match.group(2).strip()
            self._count_rule('LISTAGG->STRING_AGG')
            return f'STRING_AGG({args} ORDER BY {order_by})'

        return pattern.sub(replace_listagg, sql)

    def _convert_wm_concat(self, sql):
        """WM_CONCAT(col) -> STRING_AGG(col::text, ',')."""
        pattern = re.compile(r'\bWM_CONCAT\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            arg = sql[paren_start + 1:paren_end].strip()
            result.append(sql[last_end:start])
            result.append(f"STRING_AGG({arg}::text, ',')")
            last_end = paren_end + 1
            self._count_rule('WM_CONCAT->STRING_AGG')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_to_number(self, sql):
        """TO_NUMBER(s) -> CAST(s AS NUMERIC)."""
        pattern = re.compile(r'\bTO_NUMBER\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            arg = sql[paren_start + 1:paren_end].strip()
            # Simple TO_NUMBER with one arg
            if ',' not in arg or arg.count(',') == 0:
                result.append(sql[last_end:start])
                result.append(f'CAST({arg} AS NUMERIC)')
                last_end = paren_end + 1
                self._count_rule('TO_NUMBER->CAST')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_trunc_date(self, sql):
        """TRUNC(expr) -> DATE_TRUNC('day', expr)::DATE for date context.
        Handles complex expressions like TRUNC(o.ORDERED_AT), TRUNC(MAX(o.DATE))."""
        pattern = re.compile(r'\bTRUNC\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            # Skip if preceded by DATE_ (already DATE_TRUNC)
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            if start >= 5 and sql[start-5:start].upper() == 'DATE_':
                continue

            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)
            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 1:
                # TRUNC(date_expr) -> DATE_TRUNC('day', date_expr)::DATE
                date_expr = args[0].strip()
                result.append(sql[last_end:start])
                result.append(f"DATE_TRUNC('day', {date_expr})::DATE")
                last_end = paren_end + 1
                self._count_rule('TRUNC->DATE_TRUNC')
            elif len(args) == 2:
                # TRUNC(number, precision) -> TRUNC(number, precision) — numeric TRUNC, keep as-is
                # PostgreSQL has TRUNC(numeric, int) natively
                pass

        result.append(sql[last_end:])
        return ''.join(result) if result else sql

    def _convert_add_months(self, sql):
        """ADD_MONTHS(d, n) -> d + INTERVAL 'n months'."""
        pattern = re.compile(r'\bADD_MONTHS\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 2:
                date_expr = args[0].strip()
                months = args[1].strip()
                result.append(sql[last_end:start])
                result.append(f"({date_expr} + ({months}) * INTERVAL '1 month')")
                last_end = paren_end + 1
                self._count_rule('ADD_MONTHS->INTERVAL')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_months_between(self, sql):
        """MONTHS_BETWEEN(d1, d2) -> EXTRACT(...)."""
        pattern = re.compile(r'\bMONTHS_BETWEEN\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 2:
                d1 = args[0].strip()
                d2 = args[1].strip()
                result.append(sql[last_end:start])
                result.append(f"(EXTRACT(YEAR FROM AGE({d1}, {d2})) * 12 + EXTRACT(MONTH FROM AGE({d1}, {d2})))")
                last_end = paren_end + 1
                self._count_rule('MONTHS_BETWEEN->EXTRACT')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_last_day(self, sql):
        """LAST_DAY(d) -> (DATE_TRUNC('month', d) + INTERVAL '1 month - 1 day')::DATE."""
        pattern = re.compile(r'\bLAST_DAY\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            arg = sql[paren_start + 1:paren_end].strip()
            result.append(sql[last_end:start])
            result.append(f"(DATE_TRUNC('month', {arg}) + INTERVAL '1 month - 1 day')::DATE")
            last_end = paren_end + 1
            self._count_rule('LAST_DAY->DATE_TRUNC')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_instr(self, sql):
        """INSTR(s, sub) -> POSITION(sub IN s). Only 2-arg version."""
        pattern = re.compile(r'\bINSTR\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 2:  # Only handle simple 2-arg case
                result.append(sql[last_end:start])
                result.append(f'POSITION({args[1]} IN {args[0]})')
                last_end = paren_end + 1
                self._count_rule('INSTR->POSITION')
            # 3+ arg INSTR left for LLM

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_length(self, sql):
        """LENGTH is compatible but track it."""
        # LENGTH is the same in both, no conversion needed
        return sql

    # ========== DBMS_LOB ==========

    def _convert_dbms_lob_substr(self, sql):
        """DBMS_LOB.SUBSTR(clob, len, pos) -> SUBSTRING(text FROM pos FOR len)."""
        pattern = re.compile(r'\bDBMS_LOB\s*\.\s*SUBSTR\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 3:
                clob = args[0].strip()
                length = args[1].strip()
                pos = args[2].strip()
                result.append(sql[last_end:start])
                result.append(f'SUBSTRING({clob} FROM {pos} FOR {length})')
                last_end = paren_end + 1
                self._count_rule('DBMS_LOB.SUBSTR->SUBSTRING')
            elif len(args) == 2:
                clob = args[0].strip()
                length = args[1].strip()
                result.append(sql[last_end:start])
                result.append(f'SUBSTRING({clob} FROM 1 FOR {length})')
                last_end = paren_end + 1
                self._count_rule('DBMS_LOB.SUBSTR->SUBSTRING')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_dbms_lob_getlength(self, sql):
        """DBMS_LOB.GETLENGTH(clob) -> LENGTH(text)."""
        pattern = re.compile(r'\bDBMS_LOB\s*\.\s*GETLENGTH\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            arg = sql[paren_start + 1:paren_end].strip()
            result.append(sql[last_end:start])
            result.append(f'LENGTH({arg})')
            last_end = paren_end + 1
            self._count_rule('DBMS_LOB.GETLENGTH->LENGTH')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_dbms_lob_instr(self, sql):
        """DBMS_LOB.INSTR(clob, pattern) -> POSITION(pattern IN text)."""
        pattern_re = re.compile(r'\bDBMS_LOB\s*\.\s*INSTR\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern_re.finditer(sql):
            start = match.start()
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) >= 2:
                clob = args[0].strip()
                search = args[1].strip()
                result.append(sql[last_end:start])
                result.append(f'POSITION({search} IN {clob})')
                last_end = paren_end + 1
                self._count_rule('DBMS_LOB.INSTR->POSITION')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_dbms_random(self, sql):
        """DBMS_RANDOM.VALUE -> random(), DBMS_RANDOM.VALUE(lo,hi) -> floor(random()*(hi-lo+1)+lo)."""
        # Simple: DBMS_RANDOM.VALUE without args
        new_sql = re.sub(
            r'\bDBMS_RANDOM\s*\.\s*VALUE\b(?!\s*\()',
            'random()',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('DBMS_RANDOM.VALUE->random()')
            sql = new_sql

        # With args: DBMS_RANDOM.VALUE(lo, hi)
        pattern = re.compile(r'\bDBMS_RANDOM\s*\.\s*VALUE\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 2:
                lo = args[0].strip()
                hi = args[1].strip()
                result.append(sql[last_end:start])
                result.append(f'floor(random() * ({hi} - {lo} + 1) + {lo})')
                last_end = paren_end + 1
                self._count_rule('DBMS_RANDOM.VALUE(lo,hi)->floor(random()...)')

        result.append(sql[last_end:])
        return ''.join(result)

    # ========== REGEXP ==========

    def _convert_regexp_like(self, sql):
        """REGEXP_LIKE(str, pattern) -> str ~ pattern."""
        pattern = re.compile(r'\bREGEXP_LIKE\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) >= 2:
                col = args[0].strip()
                pat = args[1].strip()
                # Check for case-insensitive flag
                if len(args) >= 3 and "'i'" in args[2].lower():
                    operator = '~*'
                else:
                    operator = '~'
                result.append(sql[last_end:start])
                result.append(f'{col} {operator} {pat}')
                last_end = paren_end + 1
                self._count_rule('REGEXP_LIKE->~')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_regexp_replace(self, sql):
        """REGEXP_REPLACE(str, pattern, repl) -> regexp_replace(str, pattern, repl)."""
        new_sql = re.sub(
            r'\bREGEXP_REPLACE\s*\(',
            'regexp_replace(',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('REGEXP_REPLACE->regexp_replace')
        return new_sql

    def _convert_regexp_substr(self, sql):
        """REGEXP_SUBSTR(str, pattern) -> substring(str from pattern)."""
        pattern = re.compile(r'\bREGEXP_SUBSTR\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 2:  # Simple 2-arg case
                col = args[0].strip()
                pat = args[1].strip()
                result.append(sql[last_end:start])
                result.append(f'substring({col} from {pat})')
                last_end = paren_end + 1
                self._count_rule('REGEXP_SUBSTR->substring')
            # 3+ args (position, occurrence) left for LLM

        result.append(sql[last_end:])
        return ''.join(result)

    # ========== Syntax conversions ==========

    def _convert_outer_join_plus(self, sql):
        """Simple (+) detection -- flag for LLM, don't auto-convert (structural change needed)."""
        if re.search(r'\(\+\)', sql):
            # Don't auto-convert -- this requires FROM/WHERE restructuring
            # Just flag it as unconverted
            if '(+) outer join' not in [u.get('pattern') for u in self.stats['unconverted']]:
                self.stats['unconverted'].append({
                    'pattern': '(+) outer join',
                    'reason': 'Requires structural FROM/WHERE clause restructuring to ANSI JOIN',
                    'severity': 'needs_llm'
                })
        return sql

    def _convert_minus(self, sql):
        """MINUS -> EXCEPT."""
        new_sql = re.sub(r'\bMINUS\b', 'EXCEPT', sql, flags=re.IGNORECASE)
        if new_sql != sql:
            self._count_rule('MINUS->EXCEPT')
        return new_sql

    def _convert_rownum_simple(self, sql):
        """Simple ROWNUM <= N -> LIMIT N (only standalone WHERE ROWNUM)."""
        # Only handle: WHERE ROWNUM <= N or AND ROWNUM <= N
        # Don't touch pagination patterns (3-level nesting)
        new_sql = re.sub(
            r'\bAND\s+ROWNUM\s*<=\s*(\S+)',
            r'LIMIT \1',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('ROWNUM->LIMIT')
            return new_sql

        new_sql = re.sub(
            r'\bWHERE\s+ROWNUM\s*<=\s*(\S+)',
            r'LIMIT \1',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('ROWNUM->LIMIT')
        return new_sql

    def _convert_date_formats(self, sql):
        """Convert Oracle date format strings in TO_DATE/TO_CHAR."""
        # RR -> YY
        sql = re.sub(r"'([^']*)\bRR\b([^']*)'", lambda m: f"'{m.group(1)}YY{m.group(2)}'", sql)
        # SSSSS -> SSSS (seconds since midnight)
        sql = re.sub(r"'([^']*)\bSSSSS\b([^']*)'", lambda m: f"'{m.group(1)}SSSS{m.group(2)}'", sql)
        return sql

    def _convert_hints(self, sql):
        """Oracle hints /*+ ... */ -> comment preservation."""
        def replace_hint(match):
            hint = match.group(1)
            self._count_rule('hint->comment')
            return f'/* hint: {hint} */'

        return re.sub(r'/\*\+\s*(.*?)\s*\*/', replace_hint, sql, flags=re.DOTALL)

    def _convert_greatest_least(self, sql):
        """GREATEST/LEAST: wrap arguments with COALESCE for NULL safety.
        Oracle ignores NULL in GREATEST/LEAST, PostgreSQL propagates NULL."""
        def wrap_args(match):
            func = match.group(1)  # GREATEST or LEAST
            args_str = match.group(2)
            args = [a.strip() for a in args_str.split(',')]
            wrapped = []
            for arg in args:
                if arg.upper().startswith('COALESCE(') or arg.lstrip('-').isdigit():
                    wrapped.append(arg)
                else:
                    wrapped.append(f'COALESCE({arg}, 0)')
            self._count_rule(f'{func.upper()}->COALESCE_wrap')
            return f'{func}({", ".join(wrapped)})'

        new_sql = re.sub(
            r'\b(GREATEST|LEAST)\s*\(\s*([^()]+)\)',
            wrap_args, sql, flags=re.IGNORECASE
        )
        return new_sql

    def _convert_replace_two_arg(self, sql):
        """Oracle REPLACE(str, old) (2 args, removes old) -> PG REPLACE(str, old, '').
        Oracle은 2인자 허용 (old 문자열 제거), PG는 3인자 필수."""
        pattern = re.compile(r'\bREPLACE\s*\(', re.IGNORECASE)
        result = []
        last_end = 0
        for match in pattern.finditer(sql):
            start = match.start()
            paren_start = match.end() - 1
            end = self._find_matching_paren(sql, paren_start)
            if end == -1:
                continue
            inner = sql[paren_start + 1:end]
            args = self._split_args(inner)
            if len(args) == 2:
                result.append(sql[last_end:paren_start + 1])
                result.append(f"{args[0]}, {args[1]}, ''")
                result.append(')')
                last_end = end + 1
                self._count_rule('REPLACE_2arg->3arg')
        if result:
            result.append(sql[last_end:])
            return ''.join(result)
        return sql

    def _convert_bitand(self, sql):
        """BITAND(a, b) -> (a & b)."""
        pattern = re.compile(r'\bBITAND\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)

            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)

            if len(args) == 2:
                result.append(sql[last_end:start])
                result.append(f'({args[0]} & {args[1]})')
                last_end = paren_end + 1
                self._count_rule('BITAND->&')

        result.append(sql[last_end:])
        return ''.join(result)

    def _convert_delete_from(self, sql):
        """DELETE table WHERE ... -> DELETE FROM table WHERE ...
        Oracle allows DELETE without FROM, PostgreSQL requires it."""
        new_sql = re.sub(
            r'\bDELETE\s+(?!FROM\b)(\w+)',
            r'DELETE FROM \1',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('DELETE->DELETE_FROM')
        return new_sql

    def _convert_update_set_alias(self, sql):
        """UPDATE TABLE A SET A.COL = ... -> UPDATE TABLE A SET COL = ...
        PG에서 SET 절에 테이블 alias 사용 불가."""
        if not re.search(r'\bUPDATE\b', sql, re.IGNORECASE):
            return sql
        m = re.search(r'\bUPDATE\s+\w+\s+(\w)\s+SET\b', sql, re.IGNORECASE)
        if not m:
            return sql
        alias = m.group(1)
        new_sql = re.sub(
            r'\bSET\b(.*?)(?=\bWHERE\b|\bFROM\b|$)',
            lambda match: match.group(0).replace(f'{alias}.', ''),
            sql, count=1, flags=re.IGNORECASE | re.DOTALL
        )
        if new_sql != sql:
            self._count_rule('UPDATE_SET_alias->no_alias')
        return new_sql

    def _convert_connect_by_level(self, sql):
        """CONNECT BY LEVEL <= N -> generate_series(1, N).
        Only handles simple CONNECT BY LEVEL (no PRIOR, no START WITH)."""
        new_sql = re.sub(
            r'\bCONNECT\s+BY\s+LEVEL\s*<=\s*(\S+)',
            r'FROM generate_series(1, \1) AS lvl(LEVEL)',
            sql, flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('CONNECT_BY_LEVEL->generate_series')
            return new_sql

        new_sql = re.sub(
            r'\bCONNECT\s+BY\s+LEVEL\s*<\s*(\S+)',
            r'FROM generate_series(1, \1 - 1) AS lvl(LEVEL)',
            sql, flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('CONNECT_BY_LEVEL->generate_series')
        return new_sql

    # PKG_CRYPTO function name mapping (Oracle package → PG standalone function)
    _PKG_CRYPTO_MAP = {
        'decrypt': 'pkg_crypto$decrypt',
        'encrypt': 'pkg_crypto$encrypt',
        'decrypt_session_key': 'pkg_crypto$decrypt_session_key',
        'encrypt_session_key': 'pkg_crypto$encrypt_session_key',
        # master_key: PG에 없음 — 변환 시 WARNING
    }

    def _convert_pkg_crypto(self, sql):
        """PKG_CRYPTO.FUNC(args) -> PG function call.
        Handles: DECRYPT, ENCRYPT, DECRYPT_SESSION_KEY, ENCRYPT_SESSION_KEY, MASTER_KEY.
        Also handles schema-qualified: WMSON.PKG_CRYPTO.FUNC(args)."""
        func_names = '|'.join(self._PKG_CRYPTO_MAP.keys())
        pattern = re.compile(
            rf'\b(?:\w+\.)?PKG_CRYPTO\s*\.\s*({func_names})\s*\(',
            re.IGNORECASE
        )
        result = []
        last_end = 0
        for match in pattern.finditer(sql):
            start = match.start()
            if start < last_end:
                continue
            ora_func = match.group(1).lower()
            pg_func = self._PKG_CRYPTO_MAP.get(ora_func, f'pkg_crypto_{ora_func}')
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)
            if paren_end == -1:
                continue
            args = sql[paren_start + 1:paren_end]
            result.append(sql[last_end:start])
            result.append(f'{pg_func}({args})')
            last_end = paren_end + 1
            self._count_rule('PKG_CRYPTO->pgcrypto_func')
        result.append(sql[last_end:])
        return ''.join(result) if last_end > 0 else sql

    def _convert_lpad_numeric(self, sql):
        """LPAD(numeric_expr, N, '0') -> LPAD(expr::TEXT, N, '0').
        Oracle auto-casts number to string, PG requires explicit ::TEXT."""
        pattern = re.compile(r'\bLPAD\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)
            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)
            if len(args) >= 2:
                first_arg = args[0].strip()
                # Only cast if not already ::TEXT and not a string literal
                if '::TEXT' not in first_arg.upper() and not first_arg.startswith("'"):
                    args[0] = f'{first_arg}::TEXT'
                    result.append(sql[last_end:start])
                    result.append(f'LPAD({", ".join(args)})')
                    last_end = paren_end + 1
                    self._count_rule('LPAD->LPAD_TEXT_CAST')

        result.append(sql[last_end:])
        return ''.join(result) if len(result) > 1 else sql

    def _convert_to_clob(self, sql):
        """TO_CLOB(expr) -> expr::TEXT. PG has no TO_CLOB function."""
        pattern = re.compile(r'\bTO_CLOB\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)
            if paren_end == -1:
                continue

            arg = sql[paren_start + 1:paren_end].strip()
            result.append(sql[last_end:start])
            result.append(f'{arg}::TEXT')
            last_end = paren_end + 1
            self._count_rule('TO_CLOB->TEXT_CAST')

        result.append(sql[last_end:])
        return ''.join(result) if len(result) > 1 else sql

    def _convert_to_date_single(self, sql):
        """TO_DATE(expr) single arg -> TO_DATE(expr, 'YYYYMMDD').
        Oracle allows TO_DATE without format (uses NLS_DATE_FORMAT), PG requires format."""
        pattern = re.compile(r'\bTO_DATE\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            # Skip matches inside already-converted regions
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)
            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end]
            args = self._split_args(args_str)
            if len(args) == 1:
                # Single arg TO_DATE — add default format
                arg = args[0].strip()
                result.append(sql[last_end:start])
                result.append(f"TO_DATE({arg}, 'YYYYMMDD')")
                last_end = paren_end + 1
                self._count_rule('TO_DATE_SINGLE->TO_DATE_FMT')
            # 2+ args: already has format, leave as-is

        result.append(sql[last_end:])
        return ''.join(result) if len(result) > 1 else sql

    def _convert_date_column_arithmetic(self, sql):
        """date_column - 30 -> date_column - 30::INTEGER.
        Extends timestamp_arithmetic for non-CURRENT_TIMESTAMP date columns.
        Only targets: column_name - bare_integer (not already INTERVAL or ::INTEGER)."""
        # Pattern: column_or_table.column - bare_integer
        # Exclude CURRENT_TIMESTAMP (already handled by _convert_timestamp_arithmetic)
        def replace_date_arith(match):
            expr = match.group(1)
            num = match.group(2)
            suffix = match.group(3)
            if 'CURRENT_TIMESTAMP' in expr.upper() or 'CURRENT_DATE' in expr.upper():
                return match.group(0)  # Already handled
            if '::' in match.group(0) or 'INTERVAL' in match.group(0):
                return match.group(0)
            self._count_rule('DATE_COL-N->INTEGER_CAST')
            return f"{expr}- {num}::INTEGER{suffix}"

        new_sql = re.sub(
            r'(\b\w+(?:\.\w+)?\s*)-\s*(\d+)(\s*(?:AND|OR|THEN|ELSE|END|,|\)|$))',
            replace_date_arith, sql, flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('DATE_COL-N->INTEGER_CAST')
        return new_sql

    # ========== Subquery alias & TO_CHAR single arg ==========

    _subquery_alias_counter = 0

    def _convert_subquery_alias(self, sql):
        """Add alias to subqueries in FROM clause that lack one.
        Oracle: FROM (SELECT ...) WHERE ...
        PG:     FROM (SELECT ...) AS sub_1 WHERE ...
        PG requires subqueries in FROM to have an alias."""
        # Match FROM ( ... ) followed by non-alias token (WHERE, JOIN, ,, ), etc.)
        def _add_alias(m):
            prefix = m.group(1)   # FROM or JOIN + whitespace
            subq = m.group(2)     # (...) the subquery including parens
            after = m.group(3)    # first token after closing paren
            # Check if already has alias (AS keyword or bare identifier)
            stripped = after.strip()
            if stripped.upper().startswith('AS ') or (stripped and stripped[0].isalpha() and stripped.split()[0].upper() not in
                ('WHERE', 'ON', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'CROSS', 'FULL', 'JOIN', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT', 'FETCH')):
                return m.group(0)  # already has alias
            OracleToPgConverter._subquery_alias_counter += 1
            alias = f"sub_{OracleToPgConverter._subquery_alias_counter}"
            self._count_rule('SUBQUERY_ALIAS_ADDED')
            return f"{prefix}{subq} {alias}{after}"

        # Simplified: find FROM/JOIN followed by opening paren, match to closing paren
        pattern = re.compile(
            r'(\b(?:FROM|JOIN)\s+)(\([^()]*(?:\([^()]*(?:\([^()]*\)[^()]*)*\)[^()]*)*\))(\s+\S)',
            re.IGNORECASE | re.DOTALL
        )
        return pattern.sub(_add_alias, sql)

    def _convert_to_char_single(self, sql):
        """TO_CHAR(expr) single arg → (expr)::TEXT.
        Oracle TO_CHAR works without format, PG requires it.
        Only converts single-arg calls (no comma in args)."""
        pattern = re.compile(r'\bTO_CHAR\s*\(', re.IGNORECASE | re.DOTALL)
        result = []
        last_end = 0

        for match in pattern.finditer(sql):
            start = match.start()
            if start < last_end:
                continue
            paren_start = match.end() - 1
            paren_end = self._find_matching_paren(sql, paren_start)
            if paren_end == -1:
                continue

            args_str = sql[paren_start + 1:paren_end].strip()
            # Only convert if single argument (no comma at top level)
            args = self._split_args(args_str)
            if len(args) == 1:
                expr = args[0].strip()
                result.append(sql[last_end:start])
                result.append(f'({expr})::TEXT')
                last_end = paren_end + 1
                self._count_rule('TO_CHAR_SINGLE->TEXT_CAST')

        result.append(sql[last_end:])
        return ''.join(result) if len(result) > 1 else sql

    # ========== ROWNUM Pagination & FETCH FIRST ==========

    def _convert_rownum_pagination(self, sql):
        """
        Convert 3-level ROWNUM pagination pattern to LIMIT/OFFSET.

        Oracle pattern:
            SELECT * FROM (
              SELECT a.*, ROWNUM rn FROM (
                {inner_query}
                ORDER BY {order}
              ) a WHERE ROWNUM <= #{pageEnd}
            ) WHERE rn > #{pageStart}

        PostgreSQL:
            {inner_query}
            ORDER BY {order}
            LIMIT (#{pageEnd} - #{pageStart}) OFFSET #{pageStart}
        """
        # Pattern: 3-level nested ROWNUM pagination
        # We use a flexible regex that allows for whitespace/newlines and optional aliases
        pattern = re.compile(
            r'SELECT\s+\*\s+FROM\s*\(\s*'              # outer: SELECT * FROM (
            r'SELECT\s+(\w+)\s*\.\s*\*\s*,\s*'         # middle: SELECT a.*,
            r'ROWNUM\s+(\w+)\s+'                        # ROWNUM rn
            r'FROM\s*\(\s*'                             # FROM (
            r'(.*?)'                                    # inner_query (captured)
            r'\)\s*(\w+)\s+'                            # ) a
            r'WHERE\s+ROWNUM\s*<=\s*'                   # WHERE ROWNUM <=
            r'(\S+?)\s*'                                # pageEnd param
            r'\)\s*'                                    # )
            r'WHERE\s+\2\s*>\s*'                        # WHERE rn >
            r'(\S+)',                                   # pageStart param
            re.IGNORECASE | re.DOTALL
        )

        def replace_pagination(match):
            inner_query = match.group(3).strip()
            page_end = match.group(5).strip()
            page_start = match.group(6).strip()
            self._count_rule('ROWNUM_pagination->LIMIT_OFFSET')
            return f'{inner_query}\nLIMIT ({page_end} - {page_start}) OFFSET {page_start}'

        new_sql = pattern.sub(replace_pagination, sql)
        if new_sql != sql:
            return new_sql

        # Also handle variation with >= instead of > and different ROWNUM position
        # SELECT * FROM (
        #   SELECT ROWNUM rn, a.* FROM (
        #     {inner_query}
        #   ) a WHERE ROWNUM <= #{pageEnd}
        # ) WHERE rn >= #{pageStart}
        pattern2 = re.compile(
            r'SELECT\s+\*\s+FROM\s*\(\s*'              # outer: SELECT * FROM (
            r'SELECT\s+ROWNUM\s+(\w+)\s*,\s*'          # middle: SELECT ROWNUM rn,
            r'(\w+)\s*\.\s*\*\s+'                       # a.*
            r'FROM\s*\(\s*'                             # FROM (
            r'(.*?)'                                    # inner_query (captured)
            r'\)\s*\2\s+'                               # ) a (backreference to alias)
            r'WHERE\s+ROWNUM\s*<=\s*'                   # WHERE ROWNUM <=
            r'(\S+?)\s*'                                # pageEnd param
            r'\)\s*'                                    # )
            r'WHERE\s+\1\s*>=\s*'                       # WHERE rn >=
            r'(\S+)',                                   # pageStart param
            re.IGNORECASE | re.DOTALL
        )

        def replace_pagination2(match):
            inner_query = match.group(3).strip()
            page_end = match.group(4).strip()
            page_start = match.group(5).strip()
            self._count_rule('ROWNUM_pagination->LIMIT_OFFSET')
            # For >= variant: LIMIT (pageEnd - pageStart + 1) OFFSET (pageStart - 1)
            return f'{inner_query}\nLIMIT ({page_end} - {page_start} + 1) OFFSET ({page_start} - 1)'

        new_sql = pattern2.sub(replace_pagination2, sql)
        if new_sql != sql:
            return new_sql

        # Simpler 2-level pattern:
        # SELECT * FROM (
        #   {inner_query}
        # ) WHERE ROWNUM <= N
        pattern3 = re.compile(
            r'SELECT\s+\*\s+FROM\s*\(\s*'
            r'(.*?)'
            r'\)\s*(?:\w+\s+)?'
            r'WHERE\s+ROWNUM\s*<=\s*'
            r'(\S+)',
            re.IGNORECASE | re.DOTALL
        )

        def replace_simple_wrapper(match):
            inner_query = match.group(1).strip()
            limit_val = match.group(2).strip()
            self._count_rule('ROWNUM_wrapper->LIMIT')
            return f'{inner_query}\nLIMIT {limit_val}'

        new_sql = pattern3.sub(replace_simple_wrapper, sql)
        return new_sql

    def _convert_rownum_equals_one(self, sql):
        """ROWNUM = 1 -> LIMIT 1."""
        # WHERE ROWNUM = 1
        new_sql = re.sub(
            r'\bWHERE\s+ROWNUM\s*=\s*1\b',
            'LIMIT 1',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('ROWNUM=1->LIMIT_1')
            return new_sql

        # AND ROWNUM = 1
        new_sql = re.sub(
            r'\bAND\s+ROWNUM\s*=\s*1\b',
            '\nLIMIT 1',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('ROWNUM=1->LIMIT_1')
        return new_sql

    def _convert_fetch_first(self, sql):
        """FETCH FIRST N ROWS ONLY -> LIMIT N (Oracle 12c+)."""
        new_sql = re.sub(
            r'\bFETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY\b',
            r'LIMIT \1',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('FETCH_FIRST->LIMIT')
        return new_sql

    def _convert_offset_fetch(self, sql):
        """OFFSET N ROWS FETCH NEXT M ROWS ONLY -> LIMIT M OFFSET N (Oracle 12c+)."""
        new_sql = re.sub(
            r'\bOFFSET\s+(\S+)\s+ROWS?\s+FETCH\s+(?:NEXT|FIRST)\s+(\S+)\s+ROWS?\s+ONLY\b',
            r'LIMIT \2 OFFSET \1',
            sql,
            flags=re.IGNORECASE
        )
        if new_sql != sql:
            self._count_rule('OFFSET_FETCH->LIMIT_OFFSET')
        return new_sql

    def _convert_regexp_instr(self, sql):
        """REGEXP_INSTR(col, pattern) > 0 → col ~ pattern.
        REGEXP_INSTR(col, pattern) = 0 → col !~ pattern.
        20+ 건 반복 수동 수정됨 → 룰 승격."""
        # REGEXP_INSTR(expr, 'pattern') > 0 → expr ~ 'pattern'
        new_sql = re.sub(
            r'\bREGEXP_INSTR\s*\(\s*([^,]+?)\s*,\s*(\x27[^\x27]+\x27)\s*\)\s*>\s*0',
            r'\1 ~ \2', sql, flags=re.IGNORECASE)
        # REGEXP_INSTR(expr, 'pattern') = 0 → expr !~ 'pattern'
        new_sql = re.sub(
            r'\bREGEXP_INSTR\s*\(\s*([^,]+?)\s*,\s*(\x27[^\x27]+\x27)\s*\)\s*=\s*0',
            r'\1 !~ \2', new_sql, flags=re.IGNORECASE)
        if new_sql != sql:
            self._count_rule('REGEXP_INSTR->~')
        return new_sql

    def _convert_substrb(self, sql):
        """SUBSTRB(expr, start, len) → SUBSTRING(expr FROM start FOR len).
        SUBSTRB는 byte 단위지만 PG UTF-8에서는 SUBSTRING으로 충분."""
        new_sql = re.sub(
            r'\bSUBSTRB\s*\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)',
            r'SUBSTRING(\1 FROM \2 FOR \3)', sql, flags=re.IGNORECASE)
        # 2인자 SUBSTRB(expr, start)
        new_sql = re.sub(
            r'\bSUBSTRB\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)',
            r'SUBSTRING(\1 FROM \2)', new_sql, flags=re.IGNORECASE)
        if new_sql != sql:
            self._count_rule('SUBSTRB->SUBSTRING')
        return new_sql

    def _convert_count_order_by(self, sql):
        """SELECT COUNT(*) ... ORDER BY → ORDER BY 제거.
        COUNT 쿼리에 ORDER BY는 무의미하며 일부 PG 버전에서 에러."""
        # SELECT COUNT로 시작하고 ORDER BY로 끝나는 패턴
        if re.search(r'\bSELECT\s+COUNT\s*\(', sql, re.IGNORECASE):
            new_sql = re.sub(
                r'\s+ORDER\s+BY\s+[^)]+$', '', sql, flags=re.IGNORECASE)
            if new_sql != sql:
                self._count_rule('COUNT_ORDER_BY->removed')
                return new_sql
        return sql

    # ========== Residual Pattern Scanner ==========

    def _scan_residual_patterns(self, content):
        """
        Scan the output content for any remaining Oracle-specific patterns.
        Reports each occurrence with line number, context, and suggestion.
        """
        lines = content.split('\n')

        # Define residual patterns to scan for
        residual_patterns = [
            {
                'regex': r'\(\+\)',
                'name': '(+)',
                'suggestion': 'Convert to LEFT JOIN or RIGHT JOIN (ANSI syntax)',
            },
            {
                'regex': r'\bROWNUM\b',
                'name': 'ROWNUM',
                'suggestion': 'Convert to LIMIT/OFFSET or window function ROW_NUMBER()',
            },
            {
                'regex': r'\bROWID\b',
                'name': 'ROWID',
                'suggestion': 'Use ctid (PostgreSQL system column) or add a surrogate key',
            },
            {
                'regex': r'\bCONNECT\s+BY\b',
                'name': 'CONNECT BY',
                'suggestion': 'Convert to recursive CTE (WITH RECURSIVE)',
            },
            {
                'regex': r'\bSTART\s+WITH\b',
                'name': 'START WITH',
                'suggestion': 'Convert to recursive CTE (WITH RECURSIVE)',
            },
            {
                'regex': r'\bMERGE\s+INTO\b',
                'name': 'MERGE INTO',
                'suggestion': 'Convert to INSERT ... ON CONFLICT (upsert)',
            },
            {
                'regex': r'\bPIVOT\s*\(',
                'name': 'PIVOT',
                'suggestion': 'Convert to crosstab() or conditional aggregation',
            },
            {
                'regex': r'\bUNPIVOT\s*\(',
                'name': 'UNPIVOT',
                'suggestion': 'Convert to LATERAL + VALUES or UNION ALL',
            },
            {
                'regex': r'\bDBMS_(?!LOB|RANDOM)\w+\.\w+',
                'name': 'DBMS_* package call',
                'suggestion': 'Replace with PostgreSQL equivalent function or extension',
            },
            {
                'regex': r'\bUTL_\w+\.\w+',
                'name': 'UTL_* package call',
                'suggestion': 'Replace with PostgreSQL equivalent function or extension',
            },
            {
                'regex': r'\bKEEP\s*\(\s*DENSE_RANK',
                'name': 'KEEP DENSE_RANK',
                'suggestion': 'Convert to window function with DISTINCT ON or subquery',
            },
            {
                'regex': r'\bTABLE\s*\(\s*\w+',
                'name': 'TABLE() collection',
                'suggestion': 'Convert to unnest() or LATERAL join',
            },
            {
                'regex': r'\bMODEL\b\s+',
                'name': 'MODEL clause',
                'suggestion': 'Rewrite using window functions or procedural logic',
            },
            {
                'regex': r'\bFROM\s+DUAL\b',
                'name': 'FROM DUAL (residual)',
                'suggestion': 'Remove FROM DUAL — PostgreSQL does not need it',
            },
            {
                'regex': r'\bFETCH\s+FIRST\b',
                'name': 'FETCH FIRST (residual)',
                'suggestion': 'Convert to LIMIT',
            },
            {
                'regex': r'\bSYS_GUID\s*\(\s*\)',
                'name': 'SYS_GUID()',
                'suggestion': 'Convert to gen_random_uuid() (PostgreSQL 13+) or uuid_generate_v4()',
            },
            {
                'regex': r'\bSYS_CONTEXT\s*\(',
                'name': 'SYS_CONTEXT()',
                'suggestion': 'Convert to current_setting() or session variables',
            },
            {
                'regex': r'\b(?!DBMS_|UTL_|SYS_|pkg_crypto_)[A-Za-z][A-Za-z0-9_]+\s*\.\s*[A-Za-z]\w*\s*\(',
                'name': 'Custom Oracle package call',
                'suggestion': 'Requires manual migration: create equivalent PG function or convert PL/SQL to PL/pgSQL',
            },
        ]

        # Track current query_id from XML context
        current_query_id = None

        for line_num, line in enumerate(lines, 1):
            # Try to extract query ID from XML tags
            id_match = re.search(r'<(?:select|insert|update|delete|sql)\s[^>]*id\s*=\s*["\']([^"\']+)["\']', line, re.IGNORECASE)
            if id_match:
                current_query_id = id_match.group(1)

            # Skip MyBatis parameter bindings — #{param} is NOT an Oracle pattern
            # Also skip XML tags, comments, CDATA markers
            stripped = re.sub(r'#\{[^}]+\}', '', line)  # Remove #{...} before scanning
            stripped = re.sub(r'<[^>]+>', '', stripped)    # Remove XML tags
            stripped = re.sub(r'/\*.*?\*/', '', stripped)  # Remove comments

            for pat_info in residual_patterns:
                if re.search(pat_info['regex'], stripped, re.IGNORECASE):
                    self.stats['residual_oracle_patterns'].append({
                        'line': line_num,
                        'pattern': pat_info['name'],
                        'context': line.strip(),
                        'query_id': current_query_id,
                        'suggestion': pat_info['suggestion'],
                    })

    def _scan_outer_join_details(self, content):
        """
        Scan for (+) outer join patterns and return detailed information
        for each occurrence including the tables involved and join condition.
        """
        lines = content.split('\n')
        outer_join_details = []
        current_query_id = None

        for line_num, line in enumerate(lines, 1):
            id_match = re.search(r'<(?:select|insert|update|delete|sql)\s[^>]*id\s*=\s*["\']([^"\']+)["\']', line, re.IGNORECASE)
            if id_match:
                current_query_id = id_match.group(1)

            # Find (+) patterns and extract surrounding join condition
            plus_matches = list(re.finditer(r'(\w+\.\w+)\s*=\s*(\w+\.\w+)\s*\(\+\)', line))
            for m in plus_matches:
                left_col = m.group(1)
                right_col = m.group(2)
                # (+) is on the right side, meaning LEFT JOIN
                outer_join_details.append({
                    'line': line_num,
                    'join_type': 'LEFT JOIN',
                    'condition': m.group(0),
                    'left_column': left_col,
                    'right_column': right_col,
                    'context': line.strip(),
                    'query_id': current_query_id,
                })

            # Reverse pattern: col(+) = col
            plus_matches2 = list(re.finditer(r'(\w+\.\w+)\s*\(\+\)\s*=\s*(\w+\.\w+)', line))
            for m in plus_matches2:
                left_col = m.group(1)
                right_col = m.group(2)
                # (+) is on the left side, meaning RIGHT JOIN
                outer_join_details.append({
                    'line': line_num,
                    'join_type': 'RIGHT JOIN',
                    'condition': m.group(0),
                    'left_column': left_col,
                    'right_column': right_col,
                    'context': line.strip(),
                    'query_id': current_query_id,
                })

        return outer_join_details

    # ========== Query Extraction for Tracking ==========

    def _extract_queries_from_xml(self, content):
        """Extract query_id -> sql_text mapping from XML content."""
        import xml.etree.ElementTree as ET
        queries = {}
        try:
            # DOCTYPE/DTD 제거 (ET가 외부 DTD를 resolve 못 해서 ParseError)
            cleaned = re.sub(r'<!DOCTYPE[^>]*>', '', content)
            # 네임스페이스 제거 (mybatis-3-mapper.dtd 등)
            cleaned = re.sub(r'\sxmlns="[^"]*"', '', cleaned)
            root = ET.fromstring(cleaned)
            for tag in ['select', 'insert', 'update', 'delete']:
                for elem in root.iter(tag):
                    qid = elem.get('id', '')
                    if qid:
                        text_parts = []
                        for t in elem.itertext():
                            text_parts.append(t.strip())
                        queries[qid] = ' '.join(text_parts)
        except (ET.ParseError, ValueError):
            # Fallback: regex로 추출 (XML 파싱 불가 시)
            for m in re.finditer(
                r'<(select|insert|update|delete)\s+[^>]*id\s*=\s*"([^"]+)"[^>]*>(.*?)</\1>',
                content, re.DOTALL | re.IGNORECASE
            ):
                qid = m.group(2)
                # 태그 제거 후 텍스트만
                sql_text = re.sub(r'<[^>]+>', ' ', m.group(3))
                sql_text = re.sub(r'\s+', ' ', sql_text).strip()
                queries[qid] = sql_text
        return queries

    # ========== Diff Generation ==========

    def _generate_diff(self, original_content, converted_content, input_path, output_path, diff_path):
        """Generate a unified diff showing all changes made during conversion."""
        original_lines = original_content.splitlines(keepends=True)
        converted_lines = converted_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            converted_lines,
            fromfile=f'a/{os.path.basename(input_path)} (Oracle)',
            tofile=f'b/{os.path.basename(output_path)} (PostgreSQL)',
            lineterm=''
        )

        diff_text = '\n'.join(diff)

        if not diff_text.strip():
            diff_text = '# No differences found - file was already compatible.\n'

        os.makedirs(os.path.dirname(diff_path) if os.path.dirname(diff_path) else '.', exist_ok=True)
        with open(diff_path, 'w', encoding='utf-8') as f:
            f.write(f'# Oracle to PostgreSQL Conversion Diff\n')
            f.write(f'# Generated: {datetime.now().isoformat()}\n')
            f.write(f'# Input:  {input_path}\n')
            f.write(f'# Output: {output_path}\n')
            f.write(f'#\n\n')
            f.write(diff_text)

    # ========== Progress JSON Helper ==========

    def _update_progress(self, progress_path, input_path, report):
        """Update workspace/progress.json with conversion results."""
        progress = {}
        if os.path.exists(progress_path):
            try:
                with open(progress_path, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
            except (json.JSONDecodeError, IOError):
                progress = {}

        # Ensure structure
        if 'files' not in progress:
            progress['files'] = {}
        if 'summary' not in progress:
            progress['summary'] = {}

        filename = os.path.basename(input_path)

        # Update file entry
        progress['files'][filename] = {
            'status': 'converted',
            'total_replacements': report.get('total_replacements', 0),
            'rules_applied': report.get('rules_applied', {}),
            'cdata_conversions': report.get('cdata_conversions', 0),
            'unconverted_count': report.get('unconverted_count', 0),
            'residual_count': len(report.get('residual_oracle_patterns', [])),
            'needs_llm': any(
                u.get('severity') == 'needs_llm'
                for u in report.get('unconverted', [])
            ),
            'timestamp': datetime.now().isoformat(),
        }

        # Update summary
        all_files = progress['files']
        progress['summary'] = {
            'total_files': len(all_files),
            'converted_files': sum(1 for f in all_files.values() if f.get('status') == 'converted'),
            'files_needing_llm': sum(1 for f in all_files.values() if f.get('needs_llm')),
            'total_replacements': sum(f.get('total_replacements', 0) for f in all_files.values()),
            'total_unconverted': sum(f.get('unconverted_count', 0) for f in all_files.values()),
            'total_residual': sum(f.get('residual_count', 0) for f in all_files.values()),
            'last_updated': datetime.now().isoformat(),
        }

        os.makedirs(os.path.dirname(progress_path) if os.path.dirname(progress_path) else '.', exist_ok=True)
        with open(progress_path, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)

    # ========== Unconverted detection ==========

    def _detect_unconverted(self, content):
        """Detect Oracle patterns that weren't converted (for LLM to handle)."""
        oracle_patterns = [
            (r'\bCONNECT\s+BY\b', 'CONNECT BY (hierarchical query)', 'needs_llm'),
            (r'\bSTART\s+WITH\b', 'START WITH (hierarchical query)', 'needs_llm'),
            (r'\bMERGE\s+INTO\b', 'MERGE INTO (upsert)', 'needs_llm'),
            (r'\bPIVOT\s*\(', 'PIVOT', 'needs_llm'),
            (r'\bUNPIVOT\s*\(', 'UNPIVOT', 'needs_llm'),
            (r'\bMODEL\b', 'MODEL clause', 'needs_llm'),
            (r'\(\+\)', '(+) outer join', 'needs_llm'),
            (r'\bDBMS_(?!LOB|RANDOM)\w+', 'DBMS_* package (unconverted)', 'needs_llm'),
            (r'\bUTL_\w+', 'UTL_* package', 'needs_llm'),
            (r'\bKEEP\s*\(\s*DENSE_RANK', 'KEEP DENSE_RANK', 'needs_llm'),
            (r'\bTABLE\s*\(\s*\w+', 'TABLE() function', 'needs_llm'),
            (r'\bROWNUM\b', 'ROWNUM (may need structural change)', 'warning'),
            (r'\bROWID\b', 'ROWID reference', 'warning'),
        ]

        for pattern, name, severity in oracle_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                existing = [u.get('pattern') for u in self.stats['unconverted']]
                if name not in existing:
                    self.stats['unconverted'].append({
                        'pattern': name,
                        'severity': severity,
                    })


def main():
    parser = argparse.ArgumentParser(description='Oracle to PostgreSQL XML converter')
    parser.add_argument('input', nargs='?', help='Input XML file')
    parser.add_argument('output', nargs='?', help='Output XML file')
    parser.add_argument('--report', help='Report JSON file')
    parser.add_argument('--dir', help='Input directory (batch mode)')
    parser.add_argument('--outdir', help='Output directory (batch mode)')
    parser.add_argument('--report-dir', help='Report directory (batch mode)')
    parser.add_argument('--update-progress', help='Path to progress.json to update with conversion results')
    parser.add_argument('--diff', help='Path to write unified diff of changes')
    parser.add_argument('--tracking-dir', help='Path to results directory for query-level tracking (e.g. workspace/results/file/v1)')

    args = parser.parse_args()
    converter = OracleToPgConverter()

    if args.dir:
        # Batch mode
        input_dir = Path(args.dir)
        output_dir = Path(args.outdir or 'workspace/output')
        report_dir = Path(args.report_dir) if args.report_dir else None

        xml_files = list(input_dir.glob('**/*.xml'))
        print(f"Found {len(xml_files)} XML files in {input_dir}")

        all_reports = []
        for xml_file in sorted(xml_files):
            out_file = output_dir / xml_file.name
            rep_file = (report_dir / f"{xml_file.stem}-conversion-report.json") if report_dir else None
            diff_file = (report_dir / f"{xml_file.stem}-conversion-diff.txt") if report_dir and args.diff else None

            report = converter.convert_file(
                str(xml_file), str(out_file),
                report_path=str(rep_file) if rep_file else None,
                progress_path=args.update_progress,
                diff_path=str(diff_file) if diff_file else None,
                tracking_dir=args.tracking_dir,
            )
            all_reports.append(report)

            unconverted = report.get('unconverted_count', 0)
            replacements = report.get('total_replacements', 0)
            residual = len(report.get('residual_oracle_patterns', []))
            status = 'CLEAN' if unconverted == 0 else f'{unconverted} unconverted'
            print(f"  {xml_file.name}: {replacements} replacements, {status}, {residual} residual patterns")

        # Summary
        total_replacements = sum(r.get('total_replacements', 0) for r in all_reports)
        total_unconverted = sum(r.get('unconverted_count', 0) for r in all_reports)
        total_residual = sum(len(r.get('residual_oracle_patterns', [])) for r in all_reports)
        print(f"\nTotal: {total_replacements} replacements, {total_unconverted} unconverted patterns, {total_residual} residual patterns")

    elif args.input and args.output:
        # Single file mode
        report = converter.convert_file(
            args.input, args.output,
            report_path=args.report,
            progress_path=args.update_progress,
            diff_path=args.diff,
            tracking_dir=args.tracking_dir,
        )
        print(f"Converted: {args.input} -> {args.output}")
        print(f"  Replacements: {report['total_replacements']}")
        print(f"  Rules applied: {report['rules_applied']}")
        if report['unconverted']:
            print(f"  Unconverted ({report['unconverted_count']}):")
            for u in report['unconverted']:
                print(f"    - {u['pattern']} ({u.get('severity', 'unknown')})")
        if report.get('residual_oracle_patterns'):
            print(f"  Residual Oracle patterns ({len(report['residual_oracle_patterns'])}):")
            for r in report['residual_oracle_patterns']:
                print(f"    - Line {r['line']}: {r['pattern']} -> {r['suggestion']}")
                print(f"      Context: {r['context'][:80]}")
                if r.get('query_id'):
                    print(f"      Query ID: {r['query_id']}")
        if args.diff:
            print(f"  Diff written to: {args.diff}")
        if args.update_progress:
            print(f"  Progress updated: {args.update_progress}")

        # Update results/_index.json for dashboard
        if args.report:
            _update_results_index(args.report)
    else:
        parser.print_help()


def _update_results_index(report_path):
    """Update workspace/results/_index.json with known result directories."""
    import pathlib
    results_dir = pathlib.Path(report_path).parent.parent
    index_path = results_dir / '_index.json'
    dirs = []
    if results_dir.exists():
        for d in sorted(results_dir.iterdir()):
            if d.is_dir() and not d.name.startswith('_'):
                dirs.append(d.name)
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump({"directories": dirs}, f, ensure_ascii=False)


if __name__ == '__main__':
    main()
