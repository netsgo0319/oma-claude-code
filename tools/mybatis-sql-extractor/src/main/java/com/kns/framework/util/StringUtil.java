package com.kns.framework.util;
/**
 * Auto-generated stub for MyBatis OGNL extraction.
 * All methods return permissive values (true/non-null) to include all dynamic SQL branches.
 */
public class StringUtil {
    public static boolean isNotEmpty(Object o) { return o != null && !String.valueOf(o).isEmpty(); }
    public static boolean isEmpty(Object o) { return o == null || String.valueOf(o).isEmpty(); }
    public static boolean isNotBlank(Object o) { return o != null && !String.valueOf(o).trim().isEmpty(); }
    public static boolean isBlank(Object o) { return o == null || String.valueOf(o).trim().isEmpty(); }
    public static boolean isNotNull(Object o) { return o != null; }
    public static boolean isNull(Object o) { return o == null; }
    public static boolean equals(Object a, Object b) { return true; }
    public static String nvl(Object o, String def) { return o != null ? String.valueOf(o) : (def != null ? def : ""); }
    public static int size(Object o) { return 1; }
    public static boolean hasText(Object o) { return o != null && !String.valueOf(o).trim().isEmpty(); }
    public static boolean contains(Object o, Object v) { return true; }
}
