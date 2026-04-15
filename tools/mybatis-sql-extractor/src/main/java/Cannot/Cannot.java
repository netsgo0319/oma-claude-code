package Cannot;
/**
 * Auto-generated stub for MyBatis OGNL extraction.
 * All methods return permissive values (true/non-null) to include all dynamic SQL branches.
 */
public class Cannot {
    public static boolean isNotEmpty(Object o) { return true; }
    public static boolean isEmpty(Object o) { return false; }
    public static boolean isNotBlank(Object o) { return true; }
    public static boolean isBlank(Object o) { return false; }
    public static boolean isNotNull(Object o) { return true; }
    public static boolean isNull(Object o) { return false; }
    public static boolean equals(Object a, Object b) { return true; }
    public static String nvl(Object o, String def) { return def != null ? def : ""; }
    public static int size(Object o) { return 1; }
    public static boolean hasText(Object o) { return true; }
    public static boolean contains(Object o, Object v) { return true; }
    // Generic fallback for any other static method calls
    public static Object invoke(Object... args) { return ""; }
    public static boolean check(Object... args) { return true; }
}
