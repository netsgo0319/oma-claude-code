package org.springframework.util;

import java.util.Collection;
import java.util.Map;

/**
 * Stub for Spring CollectionUtils used in OGNL expressions.
 */
public class CollectionUtils {
    public static boolean isEmpty(Collection<?> c) { return c == null || c.isEmpty(); }
    public static boolean isEmpty(Map<?, ?> m) { return m == null || m.isEmpty(); }
}
