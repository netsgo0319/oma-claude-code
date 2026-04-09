#!/usr/bin/env python3
"""
MyBatis/iBatis XML Splitter
대형 XML 파일을 쿼리 단위로 분할하여 LLM 컨텍스트 한계를 우회한다.

Usage:
    python3 tools/xml-splitter.py <input.xml> <output_dir>
"""

import xml.etree.ElementTree as ET
import json
import sys
import os
from pathlib import Path

# MyBatis 3.x query tags
MYBATIS3_QUERY_TAGS = {'select', 'insert', 'update', 'delete', 'sql'}
MYBATIS3_MAPPING_TAGS = {'resultMap', 'parameterMap', 'cache', 'cache-ref'}

# iBatis 2.x query tags
IBATIS2_QUERY_TAGS = {'select', 'insert', 'update', 'delete', 'sql', 'statement', 'procedure'}
IBATIS2_MAPPING_TAGS = {'resultMap', 'parameterMap', 'cacheModel', 'typeAlias'}


def detect_framework(root):
    """Detect MyBatis 3.x vs iBatis 2.x"""
    if root.tag == 'mapper':
        return 'mybatis3'
    elif root.tag == 'sqlMap':
        return 'ibatis2'
    else:
        return 'unknown'


def get_element_xml(element, root_attribs=None):
    """Convert element back to XML string"""
    # We need to preserve the original XML as closely as possible
    # Using ElementTree's tostring
    xml_str = ET.tostring(element, encoding='unicode', xml_declaration=False)
    return xml_str


def split_xml(input_path, output_dir):
    """Split a MyBatis/iBatis XML file into individual query chunks"""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Count lines
    with open(input_path, 'r', encoding='utf-8') as f:
        total_lines = sum(1 for _ in f)

    # Parse XML
    tree = ET.parse(input_path)
    root = tree.getroot()

    framework = detect_framework(root)
    namespace = root.get('namespace', '')

    if framework == 'mybatis3':
        query_tags = MYBATIS3_QUERY_TAGS
        mapping_tags = MYBATIS3_MAPPING_TAGS
    elif framework == 'ibatis2':
        query_tags = IBATIS2_QUERY_TAGS
        mapping_tags = IBATIS2_MAPPING_TAGS
    else:
        print(f"Warning: Unknown root tag '{root.tag}', trying MyBatis 3.x tags")
        query_tags = MYBATIS3_QUERY_TAGS
        mapping_tags = MYBATIS3_MAPPING_TAGS

    chunks = []

    for element in root:
        tag = element.tag
        elem_id = element.get('id', element.get('alias', f'unnamed_{len(chunks)}'))

        if tag in query_tags:
            chunk_type = tag
        elif tag in mapping_tags:
            chunk_type = tag.lower()
        else:
            continue  # Skip unknown tags

        # Generate filename
        safe_id = elem_id.replace('/', '_').replace('\\', '_').replace(' ', '_')
        filename = f"{safe_id}.{chunk_type}.xml"
        filepath = output_dir / filename

        # Write chunk
        xml_content = get_element_xml(element)

        # Wrap in root element to make it valid XML
        wrapper_tag = 'mapper' if framework == 'mybatis3' else 'sqlMap'
        wrapped = f'<?xml version="1.0" encoding="UTF-8"?>\n<{wrapper_tag} namespace="{namespace}">\n{xml_content}\n</{wrapper_tag}>\n'

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(wrapped)

        # Count lines in chunk
        chunk_lines = wrapped.count('\n') + 1

        chunks.append({
            "id": elem_id,
            "type": chunk_type,
            "file": filename,
            "lines": chunk_lines
        })

    # Write metadata
    metadata = {
        "source_file": input_path.name,
        "source_size_lines": total_lines,
        "framework": framework,
        "namespace": namespace,
        "total_chunks": len(chunks),
        "chunks": chunks
    }

    metadata_path = output_dir / "_metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"Split complete: {input_path.name}")
    print(f"  Framework: {framework}")
    print(f"  Namespace: {namespace}")
    print(f"  Source lines: {total_lines}")
    print(f"  Chunks: {len(chunks)}")
    print(f"  Output: {output_dir}")

    return metadata


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 xml-splitter.py <input.xml> <output_dir>")
        sys.exit(1)

    split_xml(sys.argv[1], sys.argv[2])
