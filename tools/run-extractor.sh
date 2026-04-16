#!/usr/bin/env bash
# Phase 3.5: MyBatis SQL Extractor + Validation Pipeline
# 한 번의 명령으로 전체 Phase 3.5를 실행한다.
#
# Usage:
#   bash tools/run-extractor.sh                    # build + extract + generate validation
#   bash tools/run-extractor.sh --skip-build       # build 건너뛰기 (이미 빌드된 경우)
#   bash tools/run-extractor.sh --validate         # extract + EXPLAIN 검증
#   bash tools/run-extractor.sh --execute          # extract + 실제 쿼리 실행
#
# 필수: Java 11+, Gradle
# 선택: PG 환경변수 (--validate, --execute 시 필요)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
EXTRACTOR_DIR="$SCRIPT_DIR/mybatis-sql-extractor"
JAR_PATH="$EXTRACTOR_DIR/build/libs/mybatis-sql-extractor-1.0.0.jar"
# 심링크 해석 — Java Files.walk()가 심링크를 안 따라갈 수 있으므로 실제 경로 사용
_resolve() { [ -L "$1" ] && readlink -f "$1" || echo "$1"; }
INPUT_DIR="$(_resolve "$PROJECT_DIR/workspace/input")"
OUTPUT_DIR="$(_resolve "$PROJECT_DIR/workspace/output")"
EXTRACTED_DIR="$(_resolve "$PROJECT_DIR/workspace/results/_extracted")"
# Phase 3.5는 Phase 3과 다른 디렉토리에 출력해야 함 (덮어쓰기 방지)
VALIDATION_DIR="$PROJECT_DIR/workspace/results/_validation_phase35"

SKIP_BUILD=false
DO_VALIDATE=false
DO_EXECUTE=false

for arg in "$@"; do
    case $arg in
        --skip-build) SKIP_BUILD=true ;;
        --validate) DO_VALIDATE=true ;;
        --execute) DO_EXECUTE=true ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

echo "=== Phase 3.5: MyBatis SQL Extractor ==="
echo ""

# Step 1: Check Java
if ! command -v java &>/dev/null; then
    echo "WARNING: Java not found. Phase 3.5 skipped. Install Java 11+ for MyBatis engine validation."
    mkdir -p "$EXTRACTED_DIR"
    echo '{"skipped": true, "reason": "java_not_found"}' > "$EXTRACTED_DIR/.skipped"
    exit 0
fi
JAVA_VER=$(java -version 2>&1 | head -1)
echo "Java: $JAVA_VER"

# OGNL stub directory for auto-generated stubs (pre-scan + auto-retry 공용)
STUB_DIR="$EXTRACTOR_DIR/src/main/java"

# Step 1.5: Pre-scan XMLs → generate stubs BEFORE build
# Prevents ClassNotFoundException / OGNL errors at extraction time
if [ "$SKIP_BUILD" = false ] && command -v python3 &>/dev/null; then
    echo ""
    echo "--- Pre-scanning XMLs for missing class stubs ---"
    python3 "$SCRIPT_DIR/pre-scan-stubs.py" \
        --input "$INPUT_DIR" \
        --stub-dir "$STUB_DIR"
    # Also scan output dir (converted XMLs may reference different classes)
    if [ -d "$OUTPUT_DIR" ]; then
        python3 "$SCRIPT_DIR/pre-scan-stubs.py" \
            --input "$OUTPUT_DIR" \
            --stub-dir "$STUB_DIR"
    fi
fi

# Step 2: Build (unless --skip-build)
if [ "$SKIP_BUILD" = false ]; then
    echo ""
    echo "--- Building extractor ---"
    cd "$EXTRACTOR_DIR"
    if [ -f ./gradlew ]; then
        if ! ./gradlew build -q 2>&1; then
            echo "ERROR: Gradle build failed"
            cd "$PROJECT_DIR"
            exit 1
        fi
    elif command -v gradle &>/dev/null; then
        if ! gradle build -q 2>&1; then
            echo "ERROR: Gradle build failed"
            cd "$PROJECT_DIR"
            exit 1
        fi
    else
        echo "ERROR: Gradle not found and gradlew missing."
        echo "Fix: cd $EXTRACTOR_DIR && gradle wrapper --gradle-version 8.7"
        exit 1
    fi
    cd "$PROJECT_DIR"
    echo "Build: OK"
fi

if [ ! -f "$JAR_PATH" ]; then
    echo "ERROR: JAR not found at $JAR_PATH"
    echo "Run without --skip-build to build first."
    exit 1
fi

# Step 3: Check input files
XML_COUNT=$(ls "$INPUT_DIR"/*.xml 2>/dev/null | wc -l)
if [ "$XML_COUNT" -eq 0 ]; then
    echo "ERROR: No XML files in $INPUT_DIR"
    exit 1
fi
echo "XML files: $XML_COUNT"

# Step 4: Run extraction (with TC params if available)
MERGED_TC="$PROJECT_DIR/workspace/results/_test-cases/merged-tc.json"
PARAMS_OPT=""
if [ -f "$MERGED_TC" ]; then
    PARAMS_OPT="--params $MERGED_TC"
    echo "--- TC params found: $MERGED_TC ---"
fi

# OGNL stub directory — moved up, pre-scan-stubs.py도 참조
# STUB_DIR is defined earlier (before Step 1.5)
STUB_CP=""

# Function: run extractor with auto-stub retry for ClassNotFoundException
run_extractor_with_stubs() {
    local INPUT="$1"
    local OUTPUT="$2"
    local MAX_RETRY=5
    local RETRY=0
    local CP_OPT=""

    while [ $RETRY -lt $MAX_RETRY ]; do
        echo "  [Extraction attempt $((RETRY+1))/$MAX_RETRY]"
        EXTRACT_LOG=$(java ${CP_OPT:+"$CP_OPT"} -jar "$JAR_PATH" --input "$INPUT" --output "$OUTPUT" ${PARAMS_OPT:+"$PARAMS_OPT"} 2>&1)
        echo "$EXTRACT_LOG" | tail -5

        # Check for ClassNotFoundException / OGNL errors in output
        # Pattern 1: java.lang.ClassNotFoundException: com.pkg.ClassName
        MISSING_CLASSES=$(echo "$EXTRACT_LOG" | grep -oP 'ClassNotFoundException:\s*\K[\w.]+' | sort -u)
        # Pattern 2: OGNL @com.pkg.ClassName@method — class not on classpath
        OGNL_MISSING=$(echo "$EXTRACT_LOG" | grep -oP '@([\w.]+)@\w+' | sed 's/@//g;s/@.*$//' | sort -u)
        if [ -n "$OGNL_MISSING" ]; then
            MISSING_CLASSES="$MISSING_CLASSES $OGNL_MISSING"
        fi
        # Pattern 3: extracted JSON error messages
        if [ -z "$MISSING_CLASSES" ]; then
            MISSING_CLASSES=$(grep -roh '"error".*ClassNotFoundException[^"]*' "$OUTPUT"/*.json 2>/dev/null | grep -oP '[\w.]+(?=\s)' | sort -u)
        fi
        if [ -z "$MISSING_CLASSES" ]; then
            MISSING_CLASSES=$(grep -roh '@[\w.]*@' "$OUTPUT"/*.json 2>/dev/null | tr -d '@' | sort -u)
        fi
        # Deduplicate and filter out known packages
        MISSING_CLASSES=$(echo "$MISSING_CLASSES" | tr ' ' '\n' | grep '\.' | grep -v '^java\.' | grep -v '^org\.apache\.' | sort -u | tr '\n' ' ')

        if [ -z "$MISSING_CLASSES" ]; then
            echo "  Extraction complete (no missing classes)"
            break
        fi

        echo "  Missing classes found: $MISSING_CLASSES"
        echo "  Auto-generating stubs..."

        for CLASS in $MISSING_CLASSES; do
            # Split into package and class name
            PKG=$(echo "$CLASS" | rev | cut -d. -f2- | rev)
            CLS=$(echo "$CLASS" | rev | cut -d. -f1 | rev)
            PKG_DIR="$STUB_DIR/$(echo "$PKG" | tr '.' '/')"
            STUB_FILE="$PKG_DIR/$CLS.java"

            if [ -f "$STUB_FILE" ]; then
                echo "    Stub already exists: $CLASS"
                continue
            fi

            mkdir -p "$PKG_DIR"
            echo "    Generating stub: $CLASS"
            cat > "$STUB_FILE" << JAVAEOF
package $PKG;
/**
 * Auto-generated stub for MyBatis OGNL extraction.
 * All methods return permissive values (true/non-null) to include all dynamic SQL branches.
 */
public class $CLS {
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
JAVAEOF
        done

        # Rebuild extractor with stubs on classpath
        echo "  Rebuilding extractor with stubs..."
        cd "$EXTRACTOR_DIR"
        if [ -f ./gradlew ]; then
            ./gradlew build -q 2>&1
        elif command -v gradle &>/dev/null; then
            gradle build -q 2>&1
        fi
        cd "$PROJECT_DIR"

        RETRY=$((RETRY + 1))
    done

    if [ $RETRY -eq $MAX_RETRY ]; then
        echo "  WARNING: Max retries reached. Some OGNL classes still missing."
    fi
}

echo ""
echo "--- Extracting Oracle SQL (input XML, with TC params) ---"
mkdir -p "$EXTRACTED_DIR"

run_extractor_with_stubs "$INPUT_DIR" "$EXTRACTED_DIR"

# Step 4b: Extract PG SQL variants from converted output XML
PG_EXTRACTED_DIR="$PROJECT_DIR/workspace/results/_extracted_pg"
echo ""
echo "--- Extracting PG SQL variants (output XML, with TC params) ---"
mkdir -p "$PG_EXTRACTED_DIR"

run_extractor_with_stubs "$OUTPUT_DIR" "$PG_EXTRACTED_DIR"

PG_EXTRACTED_COUNT=$(ls "$PG_EXTRACTED_DIR"/*-extracted.json 2>/dev/null | wc -l)
echo "PG output files: $PG_EXTRACTED_COUNT"

# Step 5: Validate with converted output (if exists)
if [ "$DO_VALIDATE" = true ]; then
    echo ""
    echo "--- Running EXPLAIN validation ---"

    # Use extracted SQL for validation
    python3 "$SCRIPT_DIR/validate-queries.py" \
        --local \
        --extracted "$EXTRACTED_DIR" \
        --xml-dir "$OUTPUT_DIR" \
        --output "$VALIDATION_DIR"
fi

if [ "$DO_EXECUTE" = true ]; then
    echo ""
    echo "--- Running query execution validation ---"

    python3 "$SCRIPT_DIR/validate-queries.py" \
        --execute \
        --extracted "$EXTRACTED_DIR" \
        --xml-dir "$OUTPUT_DIR" \
        --output "$VALIDATION_DIR"
fi

# Step 6: Summary
echo ""
echo "=== Phase 3.5 Complete ==="
echo "Extracted (Oracle): $EXTRACTED_DIR/"
echo "Extracted (PG):     $PG_EXTRACTED_DIR/"

EXTRACTED_COUNT=$(ls "$EXTRACTED_DIR"/*-extracted.json 2>/dev/null | wc -l)
PG_EXTRACTED_COUNT=$(ls "$PG_EXTRACTED_DIR"/*-extracted.json 2>/dev/null | wc -l)
echo "Oracle input files: $EXTRACTED_COUNT"
echo "PG output files:    $PG_EXTRACTED_COUNT"

if [ -f "$VALIDATION_DIR/validated.json" ]; then
    echo "Validation: $VALIDATION_DIR/validated.json"
fi
if [ -f "$VALIDATION_DIR/execute_validated.json" ]; then
    echo "Execution: $VALIDATION_DIR/execute_validated.json"
fi
