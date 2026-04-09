#!/usr/bin/env bash
# Phase 7: MyBatis SQL Extractor + Validation Pipeline
# 한 번의 명령으로 전체 Phase 7을 실행한다.
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
INPUT_DIR="$PROJECT_DIR/workspace/input"
OUTPUT_DIR="$PROJECT_DIR/workspace/output"
EXTRACTED_DIR="$PROJECT_DIR/workspace/results/_extracted"
VALIDATION_DIR="$PROJECT_DIR/workspace/results/_validation"

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

echo "=== Phase 7: MyBatis SQL Extractor ==="
echo ""

# Step 1: Check Java
if ! command -v java &>/dev/null; then
    echo "ERROR: Java not found. Install Java 11+ to use Phase 7."
    exit 1
fi
JAVA_VER=$(java -version 2>&1 | head -1)
echo "Java: $JAVA_VER"

# Step 2: Build (unless --skip-build)
if [ "$SKIP_BUILD" = false ]; then
    echo ""
    echo "--- Building extractor ---"
    cd "$EXTRACTOR_DIR"
    if command -v gradle &>/dev/null; then
        gradle build -q 2>&1
    elif [ -f ./gradlew ]; then
        ./gradlew build -q 2>&1
    else
        echo "ERROR: Gradle not found. Install Gradle or use ./gradlew"
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

# Step 4: Run extraction
echo ""
echo "--- Extracting SQL (individual file mode, auto DTO fallback) ---"
mkdir -p "$EXTRACTED_DIR"

java -jar "$JAR_PATH" --input "$INPUT_DIR" --output "$EXTRACTED_DIR"

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
echo "=== Phase 7 Complete ==="
echo "Extracted: $EXTRACTED_DIR/"

EXTRACTED_COUNT=$(ls "$EXTRACTED_DIR"/*-extracted.json 2>/dev/null | wc -l)
echo "Output files: $EXTRACTED_COUNT"

if [ -f "$VALIDATION_DIR/validated.json" ]; then
    echo "Validation: $VALIDATION_DIR/validated.json"
fi
if [ -f "$VALIDATION_DIR/execute_validated.json" ]; then
    echo "Execution: $VALIDATION_DIR/execute_validated.json"
fi
