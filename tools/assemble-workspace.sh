#!/bin/bash
# tools/assemble-workspace.sh
# Step 4 실행 전에 pipeline/ → workspace/ 심링크 조립.
# generate-query-matrix.py와 generate-report.py가 기존 workspace/ 경로로 작동하도록 한다.
#
# Usage:
#   bash tools/assemble-workspace.sh           # 조립
#   bash tools/assemble-workspace.sh --verify  # 심링크 검증만
#   bash tools/assemble-workspace.sh --clean   # workspace/ 심링크 정리

set -e

BASE=$(cd "$(dirname "$0")/.." && pwd)
PIPELINE="$BASE/pipeline"
WS="$BASE/workspace"

if [ ! -d "$PIPELINE" ]; then
  echo "ERROR: $PIPELINE does not exist. Run pipeline steps first."
  exit 1
fi

# ── Verify mode ──
if [ "$1" = "--verify" ]; then
  echo "=== Verifying workspace symlinks ==="
  errors=0
  for link in \
    "$WS/results/_samples" \
    "$WS/results/_validation" \
    "$WS/results/_extracted_pg" \
    "$WS/results/_extracted" \
    "$WS/results/_test-cases/merged-tc.json"; do
    if [ -L "$link" ]; then
      target=$(readlink -f "$link" 2>/dev/null)
      if [ -e "$target" ]; then
        echo "  OK: $link → $target"
      else
        echo "  BROKEN: $link → $target (target missing)"
        errors=$((errors + 1))
      fi
    elif [ -e "$link" ]; then
      echo "  REAL: $link (not a symlink)"
    else
      echo "  MISSING: $link"
      errors=$((errors + 1))
    fi
  done
  # Check per-file result dirs
  for d in "$PIPELINE/step-1-convert/output/results/"*/; do
    [ -d "$d" ] || continue
    fname=$(basename "$d")
    link="$WS/results/$fname"
    if [ -L "$link" ]; then
      echo "  OK: $link"
    else
      echo "  MISSING: $link"
      errors=$((errors + 1))
    fi
  done
  echo "=== Errors: $errors ==="
  exit $errors
fi

# ── Clean mode ──
if [ "$1" = "--clean" ]; then
  echo "=== Cleaning workspace symlinks ==="
  # Remove symlinks only (not real files)
  find "$WS/results" -maxdepth 1 -type l -delete 2>/dev/null || true
  find "$WS/results/_test-cases" -maxdepth 1 -type l -delete 2>/dev/null || true
  [ -L "$WS/output" ] && rm "$WS/output"
  [ -L "$WS/reports" ] && rm "$WS/reports"
  for link in "$WS/results/"_validation_batch-*; do
    [ -L "$link" ] && rm "$link"
  done
  echo "Done."
  exit 0
fi

# ── Assemble mode (default) ──
echo "=== Assembling workspace from pipeline ==="

# 0. workspace/input 안전 확인 — 원본 Oracle XML을 가리켜야 함
#    절대로 변환된 XML(step-1-convert/output/xml)을 가리키면 안 됨!
if [ -L "$WS/input" ]; then
  INPUT_TARGET=$(readlink -f "$WS/input")
  if echo "$INPUT_TARGET" | grep -q "step-1-convert/output/xml"; then
    echo "  ERROR: workspace/input이 변환된 XML을 가리킴! 원본으로 복구."
    rm "$WS/input"
    if [ -d "$PIPELINE/shared/input" ] && [ "$(ls -A $PIPELINE/shared/input/*.xml 2>/dev/null)" ]; then
      ln -sfn "$PIPELINE/shared/input" "$WS/input"
      echo "  FIXED: workspace/input → pipeline/shared/input"
    fi
  fi
fi

# 1. output/ — step-3 fixes가 있으면 병합, 없으면 step-1 링크
STEP1_XML="$PIPELINE/step-1-convert/output/xml"
STEP3_FIXES="$PIPELINE/step-3-validate-fix/output/xml-fixes"

if [ -d "$STEP3_FIXES" ] && ls "$STEP3_FIXES"/*.xml >/dev/null 2>&1; then
  # Step-3 fixes exist: copy step-1 base + overwrite with fixes
  echo "  output/: merging step-1 xml + step-3 fixes"
  [ -L "$WS/output" ] && rm "$WS/output"
  mkdir -p "$WS/output"
  cp "$STEP1_XML"/*.xml "$WS/output/" 2>/dev/null || true
  cp "$STEP3_FIXES"/*.xml "$WS/output/" 2>/dev/null || true
else
  echo "  output/: symlink → step-1 xml"
  [ -d "$WS/output" ] && [ ! -L "$WS/output" ] && rm -rf "$WS/output"
  ln -sfn "$STEP1_XML" "$WS/output"
fi

# 2. results/ — per-file symlinks
mkdir -p "$WS/results"
for d in "$PIPELINE/step-1-convert/output/results/"*/; do
  [ -d "$d" ] || continue
  fname=$(basename "$d")
  ln -sfn "$d" "$WS/results/$fname"
done
echo "  results/{file}/: $(ls -d "$PIPELINE/step-1-convert/output/results/"*/ 2>/dev/null | wc -l) dirs linked"

# 3. _samples → step-0
if [ -d "$PIPELINE/step-0-preflight/output/samples" ]; then
  ln -sfn "$PIPELINE/step-0-preflight/output/samples" "$WS/results/_samples"
  echo "  _samples/: linked"
fi

# 4. _test-cases/merged-tc.json → step-2
MERGED_TC="$PIPELINE/step-2-tc-generate/output/merged-tc.json"
if [ -f "$MERGED_TC" ]; then
  mkdir -p "$WS/results/_test-cases"
  ln -sfn "$MERGED_TC" "$WS/results/_test-cases/merged-tc.json"
  echo "  _test-cases/merged-tc.json: linked"
fi

# 5. _validation → step-3 validation
if [ -d "$PIPELINE/step-3-validate-fix/output/validation" ]; then
  ln -sfn "$PIPELINE/step-3-validate-fix/output/validation" "$WS/results/_validation"
  echo "  _validation/: linked"
fi

# 6. batch dirs → _validation_batch* (batch-N, batch_N, batch_00 등 모든 형태)
for bd in "$PIPELINE/step-3-validate-fix/output/batches/"*/; do
  [ -d "$bd" ] || continue
  bname=$(basename "$bd")
  ln -sfn "$bd" "$WS/results/_validation_$bname"
  echo "  _validation_$bname/: linked"
done

# 7. _extracted_pg → step-3
if [ -d "$PIPELINE/step-3-validate-fix/output/extracted_pg" ]; then
  ln -sfn "$PIPELINE/step-3-validate-fix/output/extracted_pg" "$WS/results/_extracted_pg"
  echo "  _extracted_pg/: linked"
fi

# 8. _extracted (oracle) → step-1
if [ -d "$PIPELINE/step-1-convert/output/extracted_oracle" ]; then
  ln -sfn "$PIPELINE/step-1-convert/output/extracted_oracle" "$WS/results/_extracted"
  echo "  _extracted/: linked"
fi

# 9. reports → step-4
if [ -d "$PIPELINE/step-4-report/output" ]; then
  [ -d "$WS/reports" ] && [ ! -L "$WS/reports" ] && rm -rf "$WS/reports"
  ln -sfn "$PIPELINE/step-4-report/output" "$WS/reports"
  echo "  reports/: linked"
fi

echo "=== Workspace assembled ==="

# Verify
echo ""
bash "$0" --verify
