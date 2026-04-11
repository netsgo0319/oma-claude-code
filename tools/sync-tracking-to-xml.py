#!/usr/bin/env python3
"""
Sync query-tracking.json pg_sql back to output XML files.
Fixes desync when tracking is updated but output XML isn't.

Usage:
    python3 tools/sync-tracking-to-xml.py
    python3 tools/sync-tracking-to-xml.py --dry-run
"""

import json
import glob
import re
import os
import sys
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Sync tracking pg_sql to output XML')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without writing')
    parser.add_argument('--results-dir', default='workspace/results', help='Results directory')
    parser.add_argument('--output-dir', default='workspace/output', help='Output XML directory')
    args = parser.parse_args()

    synced = 0
    skipped = 0

    for tracking_path in sorted(glob.glob(f'{args.results_dir}/*/v*/query-tracking.json')):
        try:
            with open(tracking_path, 'r', encoding='utf-8') as f:
                tracking = json.load(f)
        except Exception:
            continue

        fname = tracking.get('file', '')
        if not fname:
            continue

        output_path = os.path.join(args.output_dir, fname)
        if not os.path.exists(output_path):
            continue

        with open(output_path, 'r', encoding='utf-8') as f:
            xml_content = f.read()

        queries = tracking.get('queries', [])
        if isinstance(queries, dict):
            queries = list(queries.values())

        changed = False
        for q in queries:
            qid = q.get('query_id', '')
            pg_sql = q.get('pg_sql', '')
            if not qid or not pg_sql:
                continue

            # Find the query tag in XML
            tag_pattern = re.compile(
                r'(<(?:select|insert|update|delete)\s+[^>]*id\s*=\s*"' + re.escape(qid) + r'"[^>]*>)(.*?)(</(?:select|insert|update|delete)>)',
                re.DOTALL | re.IGNORECASE
            )
            m = tag_pattern.search(xml_content)
            if not m:
                continue

            old_body = m.group(2)

            # Check if Oracle patterns remain in XML but not in tracking pg_sql
            oracle_in_xml = bool(re.search(r'\bMERGE\s+INTO\b|\bCONNECT\s+BY\b|\(\+\)', old_body, re.IGNORECASE))
            oracle_in_tracking = bool(re.search(r'\bMERGE\s+INTO\b|\bCONNECT\s+BY\b|\(\+\)', pg_sql, re.IGNORECASE))

            if oracle_in_xml and not oracle_in_tracking:
                # XML has Oracle patterns but tracking doesn't → sync needed
                # Replace the SQL body (preserve dynamic SQL tags)
                # Simple: if no dynamic tags, replace entirely
                has_dynamic = bool(re.search(r'<(?:if|choose|when|otherwise|foreach|where|set|trim)\b', old_body))

                if not has_dynamic:
                    new_body = '\n' + pg_sql + '\n    '
                    xml_content = xml_content[:m.start(2)] + new_body + xml_content[m.end(2):]
                    changed = True
                    synced += 1
                    if args.dry_run:
                        print(f"  SYNC {fname}::{qid} (Oracle patterns in XML, clean in tracking)")
                else:
                    skipped += 1
                    if args.dry_run:
                        print(f"  SKIP {fname}::{qid} (has dynamic SQL tags — manual sync needed)")

        if changed and not args.dry_run:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)

    print(f"Synced: {synced}, Skipped (dynamic SQL): {skipped}")


if __name__ == '__main__':
    main()
