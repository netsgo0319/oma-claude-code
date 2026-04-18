#!/usr/bin/env python3
"""
S3 Upload — Phase 2 결과물을 프로젝트 S3 경로에 업로드.

Usage:
    python3 tools/upload-to-s3.py
    python3 tools/upload-to-s3.py --config ../migration-config.json --phase phase2-app
"""

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description='Upload migration results to S3')
    ap.add_argument('--config', default=None, help='migration-config.json 경로')
    ap.add_argument('--phase', default='phase2-app', help='Phase 이름 (phase1-schema 또는 phase2-app)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    # Config 로드
    config_path = args.config or 'migration-config.json'
    if not Path(config_path).exists():
        config_path = '../migration-config.json'
    if not Path(config_path).exists():
        print("⚠️ migration-config.json 없음 — /init-project 먼저 실행")
        return

    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    project = config['project']['name']
    bucket = config['project'].get('s3_bucket', '')
    if not bucket:
        print("⚠️ S3 버킷 미설정")
        return

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    s3_prefix = f"s3://{bucket}/{project}/{args.phase}/{timestamp}"

    print(f"=== S3 Upload: {s3_prefix} ===")

    # Phase 2 결과물
    files_to_upload = []

    if args.phase == 'phase2-app':
        candidates = [
            ('pipeline/step-4-report/output/migration-report.html', 'migration-report.html'),
            ('pipeline/step-4-report/output/query-matrix.json', 'query-matrix.json'),
            ('pipeline/step-4-report/output/query-matrix.csv', 'query-matrix.csv'),
        ]
        # 변환된 XML
        xml_dir = Path('pipeline/step-1-convert/output/xml')
        if xml_dir.exists():
            for xf in sorted(xml_dir.glob('*.xml')):
                candidates.append((str(xf), f'converted-xml/{xf.name}'))

        # 학습 결과
        learning_dir = Path('pipeline/learning')
        if learning_dir.exists():
            for lf in sorted(learning_dir.glob('*')):
                if lf.is_file():
                    candidates.append((str(lf), f'learning/{lf.name}'))

        # migration-config
        candidates.append((config_path, 'migration-config.json'))

    elif args.phase == 'phase1-schema':
        candidates = [
            ('schema-migration/migration_result.json', 'migration_result.json'),
            (config_path, 'migration-config.json'),
        ]
        # Phase 1 보고서
        report_dir = Path('schema-migration/workspace/reports')
        if report_dir.exists():
            for rf in sorted(report_dir.glob('*.html')):
                candidates.append((str(rf), rf.name))

    # 업로드
    uploaded = 0
    for local, remote in candidates:
        if Path(local).exists():
            s3_path = f"{s3_prefix}/{remote}"
            if args.dry_run:
                print(f"  (dry) {local} → {s3_path}")
            else:
                try:
                    subprocess.run(['aws', 's3', 'cp', local, s3_path],
                                  capture_output=True, text=True, timeout=60)
                    uploaded += 1
                    print(f"  ↑ {remote}")
                except Exception as e:
                    print(f"  ✗ {remote}: {e}")

    mode = "(dry-run)" if args.dry_run else ""
    print(f"\n{uploaded} files uploaded {mode}")
    print(f"S3: {s3_prefix}/")

    # config에 S3 경로 기록
    if not args.dry_run and args.phase == 'phase2-app':
        config.setdefault('phase2', {})['s3_path'] = s3_prefix
        config['phase2']['uploaded_at'] = datetime.now().isoformat()
        Path(config_path).write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
