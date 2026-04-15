package com.oma.extractor;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.mapping.*;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.apache.ibatis.datasource.pooled.PooledDataSource;
import org.apache.ibatis.type.TypeAliasRegistry;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.regex.*;
import java.util.stream.Collectors;

/**
 * MyBatis XML 매퍼 파일에서 실제 SQL을 추출하는 유틸리티.
 * SqlSessionFactory + BoundSql API를 사용하여 동적 SQL을 정확하게 평가한다.
 *
 * 각 XML 파일을 독립된 Configuration으로 처리하여 namespace 충돌을 방지한다.
 * parameterType에 지정된 DTO 클래스가 classpath에 없으면 자동으로 HashMap으로 대체한다.
 *
 * Usage:
 *   java -jar mybatis-sql-extractor.jar [options]
 *   --input <dir>         XML 매퍼 파일 디렉토리 (필수)
 *   --output <dir>        JSON 출력 디렉토리 (필수)
 *   --config <file>       mybatis-config.xml 경로 (선택, 없으면 기본 설정 사용)
 *   --params <file>       테스트 파라미터 JSON 파일 (선택, test-cases.json 형식)
 */
public class SqlExtractor {

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create();

    // Regex to find parameterType/resultType attributes with fully-qualified class names
    private static final Pattern PARAM_TYPE_PATTERN = Pattern.compile(
        "(parameterType|parameterClass|resultType|resultClass)\\s*=\\s*\"([^\"]+)\"");

    public static void main(String[] args) throws Exception {
        Map<String, String> options = parseArgs(args);

        String inputDir = options.get("input");
        String outputDir = options.get("output");
        String configPath = options.getOrDefault("config", null);
        String paramsPath = options.getOrDefault("params", null);

        if (inputDir == null || outputDir == null) {
            System.err.println("Usage: java -jar mybatis-sql-extractor.jar --input <dir> --output <dir> [--config <file>] [--params <file>]");
            System.exit(1);
        }

        Files.createDirectories(Paths.get(outputDir));

        // Find all XML mapper files
        List<Path> xmlFiles = Files.walk(Paths.get(inputDir))
                .filter(p -> p.toString().endsWith(".xml"))
                .collect(Collectors.toList());

        System.out.println("Found " + xmlFiles.size() + " XML files in " + inputDir);

        // Load test parameters if provided
        Map<String, List<Map<String, Object>>> testParams = null;
        if (paramsPath != null) {
            testParams = loadTestParams(paramsPath);
        }

        // Summary stats
        int successCount = 0;
        int errorCount = 0;
        int totalQueries = 0;
        int totalVariants = 0;
        List<String> dtoReplacements = new ArrayList<>();

        // Process each XML file with its own Configuration to avoid StrictMap collision
        for (Path xmlFile : xmlFiles) {
            try {
                // Pre-process: replace unknown DTO classes with HashMap
                Path processedFile = preprocessDtoTypes(xmlFile, dtoReplacements);

                // Fresh Configuration per file to avoid namespace collision
                Configuration configuration = createConfiguration(configPath);

                Map<String, Object> result = processMapperFile(configuration, processedFile, testParams);

                // Restore original source_file name
                result.put("source_file", xmlFile.getFileName().toString());
                if (!dtoReplacements.isEmpty()) {
                    result.put("dto_replacements", new ArrayList<>(dtoReplacements));
                }

                // Count stats
                List<?> queries = (List<?>) result.get("queries");
                if (queries != null) {
                    totalQueries += queries.size();
                    for (Object q : queries) {
                        if (q instanceof Map) {
                            List<?> variants = (List<?>) ((Map<?, ?>) q).get("sql_variants");
                            if (variants != null) totalVariants += variants.size();
                        }
                    }
                }

                // Write output JSON
                String outputFileName = xmlFile.getFileName().toString().replace(".xml", "-extracted.json");
                Path outputPath = Paths.get(outputDir, outputFileName);
                Files.writeString(outputPath, GSON.toJson(result));

                System.out.println("  OK: " + xmlFile.getFileName());
                successCount++;

                // Clean up temp file
                if (!processedFile.equals(xmlFile)) {
                    Files.deleteIfExists(processedFile);
                }
                dtoReplacements.clear();

            } catch (Exception e) {
                System.err.println("  FAIL: " + xmlFile.getFileName() + " - " + e.getMessage());
                errorCount++;

                // Write error result
                Map<String, Object> errorResult = new LinkedHashMap<>();
                errorResult.put("source_file", xmlFile.getFileName().toString());
                errorResult.put("error", e.getMessage());
                errorResult.put("stack_trace", getStackTrace(e));

                String outputFileName = xmlFile.getFileName().toString().replace(".xml", "-extracted.json");
                Path outputPath = Paths.get(outputDir, outputFileName);
                Files.writeString(outputPath, GSON.toJson(errorResult));
            }
        }

        // Print summary
        System.out.println("\n=== Extraction Summary ===");
        System.out.println("Files: " + successCount + " OK, " + errorCount + " FAIL (total " + xmlFiles.size() + ")");
        System.out.println("Queries: " + totalQueries + ", Variants: " + totalVariants);
    }

    /**
     * Pre-process XML to replace unknown DTO class names with java.util.HashMap.
     * This handles the common case where parameterType/resultType references project-specific
     * DTO classes that aren't on the extractor's classpath.
     */
    private static Path preprocessDtoTypes(Path xmlFile, List<String> replacements) throws IOException {
        String content = Files.readString(xmlFile, StandardCharsets.UTF_8);
        String original = content;

        // Known MyBatis built-in type aliases (don't replace these)
        Set<String> builtinTypes = new HashSet<>(Arrays.asList(
            "string", "int", "integer", "long", "short", "byte", "float", "double",
            "boolean", "date", "object", "map", "hashmap", "list", "arraylist",
            "collection", "iterator", "ResultSet",
            "java.lang.String", "java.lang.Integer", "java.lang.Long",
            "java.lang.Short", "java.lang.Byte", "java.lang.Float",
            "java.lang.Double", "java.lang.Boolean", "java.lang.Object",
            "java.util.Map", "java.util.HashMap", "java.util.LinkedHashMap",
            "java.util.List", "java.util.ArrayList", "java.util.Collection",
            "java.util.Date", "java.sql.Date", "java.sql.Timestamp",
            "java.math.BigDecimal", "java.math.BigInteger"
        ));

        Matcher matcher = PARAM_TYPE_PATTERN.matcher(content);
        StringBuffer sb = new StringBuffer();
        while (matcher.find()) {
            String attr = matcher.group(1);
            String typeName = matcher.group(2);

            // Skip built-in types
            if (builtinTypes.contains(typeName) || builtinTypes.contains(typeName.toLowerCase())) {
                continue;
            }

            // Try to load the class - if it fails, replace with HashMap
            try {
                Class.forName(typeName);
            } catch (ClassNotFoundException e) {
                String replacement = attr + "=\"java.util.HashMap\"";
                matcher.appendReplacement(sb, Matcher.quoteReplacement(replacement));
                replacements.add(typeName + " -> java.util.HashMap");
            }
        }
        matcher.appendTail(sb);
        content = sb.toString();

        if (!content.equals(original)) {
            System.out.println("  DTO replacements in " + xmlFile.getFileName() + ": " + replacements.size());
            for (String r : replacements) {
                System.out.println("    " + r);
            }
            // Write to temp file
            Path tempFile = xmlFile.getParent().resolve("._tmp_" + xmlFile.getFileName());
            Files.writeString(tempFile, content, StandardCharsets.UTF_8);
            return tempFile;
        }

        return xmlFile;
    }

    private static Configuration createConfiguration(String configPath) throws Exception {
        if (configPath != null && Files.exists(Paths.get(configPath))) {
            try (InputStream is = Files.newInputStream(Paths.get(configPath))) {
                SqlSessionFactory factory = new SqlSessionFactoryBuilder().build(is);
                return factory.getConfiguration();
            }
        }

        // Default configuration with H2 dummy datasource
        Configuration config = new Configuration();

        // Use H2 in-memory database as dummy datasource
        // This allows MyBatis to initialize without a real Oracle/PostgreSQL connection
        PooledDataSource dataSource = new PooledDataSource(
            "org.h2.Driver",
            "jdbc:h2:mem:dummy;MODE=Oracle",
            "sa", ""
        );

        Environment env = new Environment("extraction",
            new org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory(),
            dataSource);
        config.setEnvironment(env);

        // Oracle-compatible settings
        config.setDatabaseId("oracle");
        config.setMapUnderscoreToCamelCase(false);
        config.setUseGeneratedKeys(false);

        // Register stub TypeHandlers for common custom type aliases
        try {
            org.apache.ibatis.type.TypeAliasRegistry typeAliasRegistry = config.getTypeAliasRegistry();
            typeAliasRegistry.registerAlias("WmsCodeDescTypeHandler", com.oma.typehandler.WmsCodeDescTypeHandler.class);
            typeAliasRegistry.registerAlias("CodeDescTypeHandler", com.oma.typehandler.WmsCodeDescTypeHandler.class);
            typeAliasRegistry.registerAlias("GmtDateTimeTypeHandler", com.oma.typehandler.GmtDateTimeTypeHandler.class);
            typeAliasRegistry.registerAlias("UrMstDescTypeHandler", com.oma.typehandler.UrMstDescTypeHandler.class);
            typeAliasRegistry.registerAlias("TmsCodeDescTypeHandler", com.oma.typehandler.TmsCodeDescTypeHandler.class);
            typeAliasRegistry.registerAlias("IcomCodeDescTypeHandler", com.oma.typehandler.IcomCodeDescTypeHandler.class);
            // Register type handlers by their short names for typeHandler="X" in resultMap
            config.getTypeHandlerRegistry().register(com.oma.typehandler.WmsCodeDescTypeHandler.class);
            config.getTypeHandlerRegistry().register(com.oma.typehandler.GmtDateTimeTypeHandler.class);
            config.getTypeHandlerRegistry().register(com.oma.typehandler.UrMstDescTypeHandler.class);
            config.getTypeHandlerRegistry().register(com.oma.typehandler.TmsCodeDescTypeHandler.class);
            config.getTypeHandlerRegistry().register(com.oma.typehandler.IcomCodeDescTypeHandler.class);
        } catch (Exception e) {
            // Ignore if stub classes don't exist
        }

        return config;
    }

    private static Map<String, Object> processMapperFile(
            Configuration configuration, Path xmlFile,
            Map<String, List<Map<String, Object>>> testParams) throws Exception {

        // Parse the mapper XML
        String resource = xmlFile.toString();
        try (InputStream is = Files.newInputStream(xmlFile)) {
            XMLMapperBuilder mapperBuilder = new XMLMapperBuilder(
                is, configuration, resource, configuration.getSqlFragments());
            mapperBuilder.parse();
        }

        // Extract namespace - collect all MappedStatements from this resource
        String namespace = null;
        List<MappedStatement> statements = new ArrayList<>();
        for (Object obj : configuration.getMappedStatements()) {
            if (obj instanceof MappedStatement) {
                MappedStatement ms = (MappedStatement) obj;
                if (ms.getResource() != null && ms.getResource().equals(resource)) {
                    statements.add(ms);
                }
            }
        }

        if (!statements.isEmpty()) {
            String id = statements.iterator().next().getId();
            int lastDot = id.lastIndexOf('.');
            namespace = lastDot > 0 ? id.substring(0, lastDot) : "";
        }

        // Build result
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("version", 1);
        result.put("source_file", xmlFile.getFileName().toString());
        result.put("framework", "mybatis3");
        result.put("namespace", namespace);
        result.put("extraction_method", "SqlSessionFactory_BoundSql");

        List<Map<String, Object>> queries = new ArrayList<>();

        for (MappedStatement ms : statements) {
            Map<String, Object> query = extractStatement(ms, testParams);
            queries.add(query);
        }

        result.put("queries", queries);

        // Count variants with multiple unique SQLs (true dynamic SQL branches)
        int multiVariantCount = 0;
        int totalVariantCount = 0;
        for (Map<String, Object> q : queries) {
            List<?> variants = (List<?>) q.get("sql_variants");
            if (variants != null) {
                totalVariantCount += variants.size();
                Set<String> uniqueSqls = new HashSet<>();
                for (Object v : variants) {
                    if (v instanceof Map) {
                        Object sql = ((Map<?, ?>) v).get("sql");
                        if (sql != null) uniqueSqls.add(sql.toString());
                    }
                }
                if (uniqueSqls.size() > 1) multiVariantCount++;
            }
        }

        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("total_queries", queries.size());
        metadata.put("total_variants", totalVariantCount);
        metadata.put("multi_branch_queries", multiVariantCount);
        metadata.put("extraction_method", "mybatis_boundsql_api");
        result.put("metadata", metadata);

        return result;
    }

    private static Map<String, Object> extractStatement(
            MappedStatement ms, Map<String, List<Map<String, Object>>> testParams) {

        Map<String, Object> query = new LinkedHashMap<>();

        String fullId = ms.getId();
        String queryId = fullId.contains(".") ? fullId.substring(fullId.lastIndexOf('.') + 1) : fullId;

        query.put("query_id", queryId);
        query.put("full_id", fullId);
        query.put("type", ms.getSqlCommandType().name().toLowerCase());
        query.put("statement_type", ms.getStatementType().name());

        if (ms.getResultMaps() != null && !ms.getResultMaps().isEmpty()) {
            ResultMap rm = ms.getResultMaps().get(0);
            if (rm.getType() != null) {
                query.put("result_type", rm.getType().getName());
            }
        }

        // Extract SQL with different parameter combinations
        List<Map<String, Object>> sqlVariants = new ArrayList<>();

        // Variant 1: null parameters (captures default branch)
        try {
            BoundSql boundSql = ms.getBoundSql(null);
            Map<String, Object> variant = new LinkedHashMap<>();
            variant.put("params", "null");
            variant.put("sql", boundSql.getSql().trim());
            variant.put("parameter_mappings", extractParameterMappings(boundSql));
            sqlVariants.add(variant);
        } catch (Exception e) {
            Map<String, Object> variant = new LinkedHashMap<>();
            variant.put("params", "null");
            variant.put("error", e.getMessage());
            sqlVariants.add(variant);
        }

        // Variant 2: empty map (different from null for <if test> evaluation)
        try {
            BoundSql boundSql = ms.getBoundSql(new HashMap<>());
            Map<String, Object> variant = new LinkedHashMap<>();
            variant.put("params", "empty_map");
            variant.put("sql", boundSql.getSql().trim());
            variant.put("parameter_mappings", extractParameterMappings(boundSql));
            sqlVariants.add(variant);
        } catch (Exception e) {
            // skip
        }

        // Variant 3: all-non-null params (to trigger all <if> branches)
        try {
            Map<String, Object> allParams = new HashMap<>();
            // Populate with dummy values to trigger dynamic SQL branches
            BoundSql probeSql = ms.getBoundSql(null);
            for (ParameterMapping pm : probeSql.getParameterMappings()) {
                String prop = pm.getProperty();
                if (pm.getJavaType() != null) {
                    allParams.put(prop, getDummyValue(pm.getJavaType()));
                } else {
                    allParams.put(prop, "test");
                }
            }
            // Common dynamic SQL test properties
            allParams.putIfAbsent("name", "test");
            allParams.putIfAbsent("status", "ACTIVE");
            allParams.putIfAbsent("id", 1);
            allParams.putIfAbsent("list", Arrays.asList(1, 2, 3));
            allParams.putIfAbsent("idList", Arrays.asList(1, 2, 3));
            // Common foreach collection names (MyBatis + iBatis)
            // 이름 추론이 불가하면 더미 리스트로 모두 커버
            // WMS/OMS/AMS 프로젝트에서 발견된 실제 컬렉션명 포함
            for (String collName : new String[]{
                "list", "idList", "ids", "items", "orders", "codes",
                "array", "collection", "paramList", "valueList",
                "seqList", "codeList", "dataList", "keyList",
                "deleteList", "insertList", "updateList",
                // 프로젝트 실제 사용 컬렉션명
                "icKeyList", "owKeyList", "ctKeyList", "stKeyList",
                "hdKeyList", "dtKeyList", "itemList", "locList",
                "obKeyList", "ibKeyList", "waveList", "batchList",
                "fileList", "excelList", "roleList", "menuList",
                "centerList", "ownerList", "storeList", "userList",
                "param", "params", "vo", "map", "dto"
            }) {
                allParams.putIfAbsent(collName, Arrays.asList("1", "2"));
            }

            BoundSql boundSql = ms.getBoundSql(allParams);
            Map<String, Object> variant = new LinkedHashMap<>();
            variant.put("params", "all_non_null");
            variant.put("sql", boundSql.getSql().trim());
            variant.put("parameter_mappings", extractParameterMappings(boundSql));
            variant.put("param_values", allParams);
            sqlVariants.add(variant);
        } catch (Exception e) {
            // skip
        }

        // Variant 4: use test-cases.json params if available
        if (testParams != null && testParams.containsKey(queryId)) {
            for (Map<String, Object> tc : testParams.get(queryId)) {
                try {
                    BoundSql boundSql = ms.getBoundSql(tc);
                    Map<String, Object> variant = new LinkedHashMap<>();
                    variant.put("params", "test_case");
                    variant.put("sql", boundSql.getSql().trim());
                    variant.put("parameter_mappings", extractParameterMappings(boundSql));
                    variant.put("param_values", tc);
                    sqlVariants.add(variant);
                } catch (Exception e) {
                    // skip
                }
            }
        }

        query.put("sql_variants", sqlVariants);

        // Primary SQL (from null params - the base query)
        if (!sqlVariants.isEmpty()) {
            Object firstSql = sqlVariants.get(0).get("sql");
            if (firstSql != null) {
                query.put("sql_raw", firstSql.toString());
            }
        }

        // Collect all unique parameter names across all variants into a top-level list.
        // This provides a quick summary of which named parameters map to the '?' placeholders.
        LinkedHashSet<String> paramNameSet = new LinkedHashSet<>();
        for (Map<String, Object> variant : sqlVariants) {
            @SuppressWarnings("unchecked")
            List<Map<String, String>> mappings =
                (List<Map<String, String>>) variant.get("parameter_mappings");
            if (mappings != null) {
                for (Map<String, String> m : mappings) {
                    String prop = m.get("property");
                    if (prop != null) {
                        paramNameSet.add(prop);
                    }
                }
            }
        }
        query.put("param_names", new ArrayList<>(paramNameSet));

        return query;
    }

    private static List<Map<String, String>> extractParameterMappings(BoundSql boundSql) {
        List<Map<String, String>> mappings = new ArrayList<>();
        for (ParameterMapping pm : boundSql.getParameterMappings()) {
            Map<String, String> m = new LinkedHashMap<>();
            m.put("property", pm.getProperty());
            m.put("java_type", pm.getJavaType() != null ? pm.getJavaType().getSimpleName() : null);
            m.put("jdbc_type", pm.getJdbcType() != null ? pm.getJdbcType().name() : null);
            m.put("mode", pm.getMode() != null ? pm.getMode().name() : null);
            mappings.add(m);
        }
        return mappings;
    }

    private static Object getDummyValue(Class<?> type) {
        if (type == String.class) return "test";
        if (type == Integer.class || type == int.class) return 1;
        if (type == Long.class || type == long.class) return 1L;
        if (type == Double.class || type == double.class) return 1.0;
        if (type == Float.class || type == float.class) return 1.0f;
        if (type == Boolean.class || type == boolean.class) return true;
        if (type == java.util.Date.class) return new java.util.Date();
        if (type == java.sql.Date.class) return new java.sql.Date(System.currentTimeMillis());
        if (type == java.sql.Timestamp.class) return new java.sql.Timestamp(System.currentTimeMillis());
        if (List.class.isAssignableFrom(type)) return Arrays.asList(1, 2, 3);
        return "test";
    }

    /**
     * Extract <foreach collection="X"> attribute values from XML source for a given statement.
     */
    private static List<String> extractForeachCollections(String statementId, String xmlSource) {
        List<String> collections = new ArrayList<>();
        if (xmlSource == null) return collections;
        // Simple regex: find collection="..." within the statement's XML block
        java.util.regex.Matcher m = java.util.regex.Pattern
            .compile("collection\\s*=\\s*[\"']([\\w.]+)[\"']")
            .matcher(xmlSource);
        while (m.find()) {
            String col = m.group(1);
            if (!col.isEmpty()) collections.add(col);
        }
        return collections;
    }

    /**
     * Extract <iterate property="X"> attribute values (iBatis compatibility).
     */
    private static List<String> extractIterateProperties(String statementId, String xmlSource) {
        List<String> properties = new ArrayList<>();
        if (xmlSource == null) return properties;
        java.util.regex.Matcher m = java.util.regex.Pattern
            .compile("<iterate[^>]+property\\s*=\\s*[\"']([\\w.]+)[\"']")
            .matcher(xmlSource);
        while (m.find()) {
            String prop = m.group(1);
            if (!prop.isEmpty()) properties.add(prop);
        }
        return properties;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, List<Map<String, Object>>> loadTestParams(String path) throws Exception {
        String json = Files.readString(Paths.get(path));
        Map<String, Object> data = GSON.fromJson(json, Map.class);
        Map<String, List<Map<String, Object>>> result = new HashMap<>();

        // Format 1: nested {query_test_cases: [{query_id, test_cases: [{binds}]}]}
        List<Map<String, Object>> testCases = (List<Map<String, Object>>) data.get("query_test_cases");
        if (testCases != null) {
            for (Map<String, Object> tc : testCases) {
                String queryId = (String) tc.get("query_id");
                List<Map<String, Object>> cases = (List<Map<String, Object>>) tc.get("test_cases");
                if (cases != null) {
                    List<Map<String, Object>> bindsList = new ArrayList<>();
                    for (Map<String, Object> c : cases) {
                        Map<String, Object> binds = (Map<String, Object>) c.get("binds");
                        if (binds != null) bindsList.add(binds);
                    }
                    result.put(queryId, bindsList);
                }
            }
        }

        // Format 2: flat {queryId: [{param1: val1, ...}, ...]} (from generate-test-cases.py)
        if (result.isEmpty()) {
            for (Map.Entry<String, Object> entry : data.entrySet()) {
                String key = entry.getKey();
                if (key.equals("query_test_cases")) continue;
                Object val = entry.getValue();
                if (val instanceof List) {
                    List<?> items = (List<?>) val;
                    List<Map<String, Object>> bindsList = new ArrayList<>();
                    for (Object item : items) {
                        if (item instanceof Map) {
                            bindsList.add((Map<String, Object>) item);
                        }
                    }
                    if (!bindsList.isEmpty()) {
                        result.put(key, bindsList);
                    }
                }
            }
            if (!result.isEmpty()) {
                System.out.println("  Loaded " + result.size() + " queries from flat TC format");
            }
        }

        return result;
    }

    private static Map<String, String> parseArgs(String[] args) {
        Map<String, String> options = new HashMap<>();
        for (int i = 0; i < args.length - 1; i += 2) {
            String key = args[i].replace("--", "");
            options.put(key, args[i + 1]);
        }
        return options;
    }

    private static String getStackTrace(Exception e) {
        StringWriter sw = new StringWriter();
        e.printStackTrace(new PrintWriter(sw));
        return sw.toString();
    }
}
