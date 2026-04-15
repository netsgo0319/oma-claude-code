#!/usr/bin/env python3
"""
Pre-scan XML files for class references and generate Java stubs BEFORE extractor build.
Prevents MyBatis rendering failures from missing TypeHandler/OGNL/DTO classes.

Usage:
    python3 tools/pre-scan-stubs.py --input pipeline/shared/input \
        --stub-dir tools/mybatis-sql-extractor/src/main/java

Scans for:
  1. typeHandler="ClassName" in resultMap/parameter
  2. parameterType="com.pkg.ClassName" / resultType="..."
  3. @com.pkg.ClassName@method() in OGNL test= expressions
  4. type="com.pkg.TypeHandler" in typeHandler tags

Generates permissive stubs so MyBatis can evaluate all dynamic branches.
"""

import argparse
import os
import re
from pathlib import Path

# Classes that DON'T need stubs (Java/MyBatis built-in)
SKIP_PACKAGES = {
    'java.', 'javax.', 'org.apache.ibatis.', 'org.mybatis.',
    'int', 'long', 'string', 'map', 'hashmap', 'list', 'arraylist',
    'boolean', 'double', 'float', 'integer', 'object',
}

# Known MyBatis aliases (don't need stubs)
MYBATIS_ALIASES = {
    'string', 'int', 'integer', 'long', 'double', 'float', 'boolean',
    'map', 'hashmap', 'list', 'arraylist', 'date', 'object', 'byte',
    'short', 'char', 'character', '_int', '_long', '_double', '_float',
    '_boolean', '_byte', '_short',
}


def scan_xml_for_classes(xml_dir):
    """Scan all XML files for Java class references."""
    classes = set()
    xml_dir = Path(xml_dir)
    if not xml_dir.exists():
        return classes

    for xml_file in sorted(xml_dir.glob('**/*.xml')):
        try:
            content = xml_file.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        # 1) typeHandler="ClassName" or type="ClassName"
        for m in re.finditer(r'typeHandler\s*=\s*["\']([^"\']+)["\']', content):
            classes.add(m.group(1))

        # 2) parameterType / resultType / resultMap type
        for attr in ('parameterType', 'resultType', 'type'):
            for m in re.finditer(rf'{attr}\s*=\s*["\']([^"\']+)["\']', content):
                val = m.group(1)
                if '.' in val:  # only FQCNs
                    classes.add(val)

        # 3) OGNL @com.pkg.ClassName@method() in test= attributes
        for m in re.finditer(r'@([\w.]+)@\w+', content):
            classes.add(m.group(1))

        # 4) javaType="com.pkg.ClassName"
        for m in re.finditer(r'javaType\s*=\s*["\']([^"\']+)["\']', content):
            val = m.group(1)
            if '.' in val:
                classes.add(val)

    return classes


def filter_classes(classes, stub_dir):
    """Filter out classes that don't need stubs."""
    needed = set()
    for cls in classes:
        cls_lower = cls.lower()
        # Skip built-in types
        if cls_lower in MYBATIS_ALIASES:
            continue
        # Skip known packages
        if any(cls_lower.startswith(pkg) for pkg in SKIP_PACKAGES):
            continue
        # Skip if stub already exists
        java_path = Path(stub_dir) / (cls.replace('.', '/') + '.java')
        if java_path.exists():
            continue
        needed.add(cls)
    return needed


def is_typehandler(cls_name):
    """Heuristic: class name suggests TypeHandler."""
    lower = cls_name.lower()
    return 'typehandler' in lower or 'handler' in lower


def generate_stub(cls, stub_dir):
    """Generate a permissive Java stub class."""
    parts = cls.rsplit('.', 1)
    if len(parts) == 2:
        package, class_name = parts
    else:
        package, class_name = '', parts[0]

    pkg_dir = Path(stub_dir) / package.replace('.', '/')
    pkg_dir.mkdir(parents=True, exist_ok=True)
    java_file = pkg_dir / f'{class_name}.java'

    if java_file.exists():
        return False

    if is_typehandler(class_name):
        # TypeHandler stub — extends BaseTypeHandler<String>
        code = f"""package {package};

import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;
import java.sql.*;

/**
 * Auto-generated TypeHandler stub for MyBatis extraction.
 */
public class {class_name} extends BaseTypeHandler<String> {{
    @Override public void setNonNullParameter(PreparedStatement ps, int i, String p, JdbcType jt) throws SQLException {{ ps.setString(i, p); }}
    @Override public String getNullableResult(ResultSet rs, String col) throws SQLException {{ return rs.getString(col); }}
    @Override public String getNullableResult(ResultSet rs, int col) throws SQLException {{ return rs.getString(col); }}
    @Override public String getNullableResult(CallableStatement cs, int col) throws SQLException {{ return cs.getString(col); }}
}}
"""
    else:
        # Generic OGNL/DTO stub — permissive static methods
        code = f"""package {package};

/**
 * Auto-generated stub for MyBatis OGNL extraction.
 * All methods return permissive values to include all dynamic SQL branches.
 */
public class {class_name} {{
    // OGNL static method stubs
    public static boolean isNotEmpty(Object o) {{ return o != null && !String.valueOf(o).isEmpty(); }}
    public static boolean isEmpty(Object o) {{ return o == null || String.valueOf(o).isEmpty(); }}
    public static boolean isNotBlank(Object o) {{ return o != null && !String.valueOf(o).trim().isEmpty(); }}
    public static boolean isBlank(Object o) {{ return o == null || String.valueOf(o).trim().isEmpty(); }}
    public static boolean isNotNull(Object o) {{ return o != null; }}
    public static boolean isNull(Object o) {{ return o == null; }}
    public static boolean equals(Object a, Object b) {{ return true; }}
    public static String nvl(Object o, String def) {{ return o != null ? String.valueOf(o) : (def != null ? def : ""); }}
    public static int size(Object o) {{ return 1; }}
    public static boolean hasText(Object o) {{ return o != null && !String.valueOf(o).trim().isEmpty(); }}
    public static boolean contains(Object o, Object v) {{ return true; }}
    public static Object invoke(Object... args) {{ return ""; }}
    public static boolean check(Object... args) {{ return true; }}

    // DTO field stubs (getter/setter pattern)
    private String value;
    public String getValue() {{ return value; }}
    public void setValue(String v) {{ this.value = v; }}
    public String toString() {{ return value != null ? value : ""; }}
}}
"""

    if not package:
        # Root package — no package statement
        code = code.replace(f'package {package};\n\n', '')

    java_file.write_text(code, encoding='utf-8')
    return True


def main():
    ap = argparse.ArgumentParser(description='Pre-scan XMLs and generate Java stubs for MyBatis extractor')
    ap.add_argument('--input', required=True, help='XML input directory')
    ap.add_argument('--stub-dir', default='tools/mybatis-sql-extractor/src/main/java',
                    help='Java source directory for stubs')
    args = ap.parse_args()

    print("=== Pre-scan: generating stubs for MyBatis extractor ===")

    # Scan
    all_classes = scan_xml_for_classes(args.input)
    print(f"  Scanned: {len(all_classes)} class references found")

    # Filter
    needed = filter_classes(all_classes, args.stub_dir)
    if not needed:
        print("  All classes already have stubs or are built-in. No new stubs needed.")
        return

    print(f"  Need stubs: {len(needed)} classes")

    # Generate
    generated = 0
    for cls in sorted(needed):
        if generate_stub(cls, args.stub_dir):
            kind = 'TypeHandler' if is_typehandler(cls) else 'OGNL/DTO'
            print(f"    + {cls} ({kind})")
            generated += 1

    print(f"  Generated: {generated} new stubs")
    if generated:
        print("  → Extractor rebuild required")


if __name__ == '__main__':
    main()
