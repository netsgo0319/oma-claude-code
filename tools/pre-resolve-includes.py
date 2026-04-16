#!/usr/bin/env python3
"""
Pre-resolve <include refid> across XML files BEFORE MyBatis extractor.
Cross-file include를 텍스트 인라인으로 치환하여 extractor가 완전한 SQL을 렌더링하도록.

Usage:
    python3 tools/pre-resolve-includes.py --input pipeline/shared/input \
        --output pipeline/shared/input-resolved

동작:
  1) 모든 XML에서 <sql id="X"> 수집 → global fragment map
  2) 각 XML에서 <include refid="X"/> → fragment 내용으로 치환
  3) MyBatis 3 property 치환 지원: <include refid="X"><property name="p" value="v"/></include>
  4) 치환된 XML을 output 디렉토리에 저장 (원본 유지)
"""

import argparse
import os
import re
from pathlib import Path
from collections import defaultdict


def collect_sql_fragments(xml_dir):
    """모든 XML에서 <sql id="X">...</sql> 수집.
    Returns: {refid: sql_body_text, ...}
    네임스페이스 포함 키도 등록 (namespace.refid)."""
    fragments = {}
    xml_dir = Path(xml_dir)

    for xml_file in sorted(xml_dir.glob('**/*.xml')):
        try:
            content = xml_file.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        # namespace 추출
        ns_match = re.search(r'<mapper\s+namespace\s*=\s*["\']([^"\']+)["\']', content)
        namespace = ns_match.group(1) if ns_match else ''

        # <sql id="X">...</sql> 추출
        for m in re.finditer(
            r'<sql\s+id\s*=\s*["\']([^"\']+)["\']\s*>(.*?)</sql>',
            content, re.DOTALL
        ):
            frag_id = m.group(1)
            frag_body = m.group(2).strip()

            # bare id로 등록
            if frag_id not in fragments:
                fragments[frag_id] = frag_body

            # namespace.id로도 등록 (namespace 참조 지원)
            if namespace:
                full_id = f"{namespace}.{frag_id}"
                fragments[full_id] = frag_body

    return fragments


def resolve_includes(content, fragments, max_depth=5):
    """<include refid="X"/> → fragment 내용으로 치환.
    Property 치환도 처리: <include refid="X"><property name="p" value="v"/></include>
    재귀적 resolve (fragment 안에 include가 또 있을 수 있음)."""

    for depth in range(max_depth):
        # Pattern 1: <include refid="X"/> (self-closing, no properties)
        def replace_simple(m):
            refid = m.group(1)
            bare = refid.split('.')[-1] if '.' in refid else refid
            body = fragments.get(refid) or fragments.get(bare, '')
            return body

        new_content = re.sub(
            r'<include\s+refid\s*=\s*["\']([^"\']+)["\']\s*/>',
            replace_simple, content
        )

        # Pattern 2: <include refid="X"><property name="p" value="v"/>...</include>
        def replace_with_props(m):
            refid = m.group(1)
            props_block = m.group(2)
            bare = refid.split('.')[-1] if '.' in refid else refid
            body = fragments.get(refid) or fragments.get(bare, '')

            # Extract properties
            props = {}
            for pm in re.finditer(
                r'<property\s+name\s*=\s*["\']([^"\']+)["\']\s+value\s*=\s*["\']([^"\']*)["\']',
                props_block
            ):
                props[pm.group(1)] = pm.group(2)

            # Apply property substitution: ${propName} → value
            for pname, pval in props.items():
                body = body.replace(f'${{{pname}}}', pval)

            return body

        new_content = re.sub(
            r'<include\s+refid\s*=\s*["\']([^"\']+)["\']\s*>(.*?)</include>',
            replace_with_props, new_content, flags=re.DOTALL
        )

        if new_content == content:
            break  # 더 이상 치환할 것 없음
        content = new_content

    return content


def main():
    ap = argparse.ArgumentParser(description='Pre-resolve <include refid> across XML files')
    ap.add_argument('--input', required=True, help='Input XML directory')
    ap.add_argument('--output', default=None,
                    help='Output directory (default: in-place modification)')
    ap.add_argument('--dry-run', action='store_true', help='Show changes without writing')
    args = ap.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output) if args.output else None

    print("=== Pre-resolve includes ===")

    # 1) Collect all <sql id> fragments
    fragments = collect_sql_fragments(input_dir)
    print(f"  Collected {len(fragments)} SQL fragments from {input_dir}")

    if not fragments:
        print("  No <sql> fragments found — nothing to resolve")
        return

    # 2) Resolve includes in each XML
    resolved_count = 0
    total_replacements = 0

    for xml_file in sorted(input_dir.glob('**/*.xml')):
        try:
            content = xml_file.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        # include가 없으면 스킵
        if '<include refid' not in content:
            if output_dir:
                out_path = output_dir / xml_file.relative_to(input_dir)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content, encoding='utf-8')
            continue

        resolved = resolve_includes(content, fragments)

        if resolved != content:
            # 치환 건수 카운트
            orig_includes = len(re.findall(r'<include\s+refid', content))
            remaining_includes = len(re.findall(r'<include\s+refid', resolved))
            replacements = orig_includes - remaining_includes
            total_replacements += replacements
            resolved_count += 1

            if args.dry_run:
                print(f"  {xml_file.name}: {replacements} includes resolved ({remaining_includes} remaining)")
            else:
                if output_dir:
                    out_path = output_dir / xml_file.relative_to(input_dir)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(resolved, encoding='utf-8')
                else:
                    # in-place
                    xml_file.write_text(resolved, encoding='utf-8')

    mode = "(dry-run)" if args.dry_run else ("→ " + str(output_dir) if output_dir else "(in-place)")
    print(f"  Resolved: {total_replacements} includes in {resolved_count} files {mode}")


if __name__ == '__main__':
    main()
