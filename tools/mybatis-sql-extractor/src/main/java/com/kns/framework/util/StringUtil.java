package com.kns.framework.util;

/**
 * Stub for MyBatis OGNL expressions referencing @com.kns.framework.util.StringUtil@
 * All methods return permissive values to include all dynamic SQL branches.
 */
public class StringUtil {
    public static boolean isNotEmpty(Object o) { return o != null && !o.toString().isEmpty(); }
    public static boolean isEmpty(Object o) { return o == null || o.toString().isEmpty(); }
    public static boolean isNotBlank(Object o) { return o != null && !o.toString().trim().isEmpty(); }
    public static boolean isBlank(Object o) { return o == null || o.toString().trim().isEmpty(); }
    public static boolean isNotNull(Object o) { return o != null; }
    public static boolean isNull(Object o) { return o == null; }
    public static boolean equals(Object a, Object b) { return a != null && a.equals(b); }
    public static String nvl(Object o, String def) { return o != null ? o.toString() : (def != null ? def : ""); }
    public static int length(Object o) { return o != null ? o.toString().length() : 0; }
}
