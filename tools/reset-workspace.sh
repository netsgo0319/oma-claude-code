#!/bin/bash
# OMA Workspace + Pipeline Reset
# workspace/input/ 의 XML 원본은 보존하고, 나머지 중간 산출물을 모두 삭제합니다.
# pipeline/ 디렉토리도 초기화합니다 (구조는 유지, 데이터만 삭제).
#
# Usage:
#   bash tools/reset-workspace.sh          # 확인 후 삭제
#   bash tools/reset-workspace.sh --force  # 확인 없이 삭제

set -e

WORKSPACE="workspace"
PIPELINE="pipeline"

echo "==============================="
echo "  OMA Workspace + Pipeline Reset"
echo "==============================="
echo ""

# 보존 대상
INPUT_COUNT=$(ls "$WORKSPACE/input/"*.xml 2>/dev/null | wc -l)
echo "[보존] workspace/input/ — ${INPUT_COUNT}개 XML 파일"
echo ""

# 삭제 대상
echo "[삭제 대상]"
[ -d "$WORKSPACE/output" ] && echo "  workspace/output/     — $(find "$WORKSPACE/output" -type f 2>/dev/null | wc -l)개 파일"
[ -d "$WORKSPACE/results" ] && echo "  workspace/results/    — $(find "$WORKSPACE/results" -type f 2>/dev/null | wc -l)개 파일"
[ -d "$WORKSPACE/reports" ] && echo "  workspace/reports/    — $(find "$WORKSPACE/reports" -type f 2>/dev/null | wc -l)개 파일"
[ -d "$WORKSPACE/logs" ] && echo "  workspace/logs/       — $(find "$WORKSPACE/logs" -type f 2>/dev/null | wc -l)개 파일"
[ -f "$WORKSPACE/progress.json" ] && echo "  workspace/progress.json"
if [ -d "$PIPELINE" ]; then
  PIPELINE_FILES=$(find "$PIPELINE" -type f ! -name ".gitkeep" 2>/dev/null | wc -l)
  echo "  pipeline/             — ${PIPELINE_FILES}개 파일 (handoff.json + output 데이터)"
fi
echo ""

# 확인
if [ "$1" != "--force" ]; then
  read -p "정말 삭제하시겠습니까? (y/N) " confirm
  if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "취소됨."
    exit 0
  fi
fi

# 삭제 실행
echo ""
echo "삭제 중..."

# output (변환 결과)
if [ -d "$WORKSPACE/output" ]; then
  rm -rf "$WORKSPACE/output"/*
  echo "  [OK] workspace/output/ 비움"
fi

# results (중간 산출물)
if [ -d "$WORKSPACE/results" ]; then
  rm -rf "$WORKSPACE/results"/*
  echo "  [OK] workspace/results/ 비움"
fi

# reports (리포트)
if [ -d "$WORKSPACE/reports" ]; then
  rm -rf "$WORKSPACE/reports"/*
  echo "  [OK] workspace/reports/ 비움"
fi

# logs (감사 로그)
if [ -d "$WORKSPACE/logs" ]; then
  rm -rf "$WORKSPACE/logs"/*
  echo "  [OK] workspace/logs/ 비움"
fi

# progress.json
if [ -f "$WORKSPACE/progress.json" ]; then
  rm -f "$WORKSPACE/progress.json"
  echo "  [OK] workspace/progress.json 삭제"
fi

# state-snapshot.json
if [ -f "$WORKSPACE/state-snapshot.json" ]; then
  rm -f "$WORKSPACE/state-snapshot.json"
  echo "  [OK] workspace/state-snapshot.json 삭제"
fi

# pipeline/ 디렉토리 (구조 유지, 데이터만 삭제)
if [ -d "$PIPELINE" ]; then
  echo ""
  echo "pipeline/ 초기화 중..."

  # handoff.json 삭제
  find "$PIPELINE" -name "handoff.json" -delete 2>/dev/null
  echo "  [OK] handoff.json 전부 삭제"

  # supervisor-state.json 삭제
  rm -f "$PIPELINE/supervisor-state.json"
  echo "  [OK] supervisor-state.json 삭제"

  # 각 step의 output 내용 삭제 (.gitkeep 유지)
  for step_dir in "$PIPELINE"/step-*/output; do
    if [ -d "$step_dir" ]; then
      find "$step_dir" -type f ! -name ".gitkeep" -delete 2>/dev/null
      find "$step_dir" -type d -empty -not -path "$step_dir" -delete 2>/dev/null
      echo "  [OK] $(basename $(dirname $step_dir))/output/ 비움"
    fi
  done

  # workspace/ 심링크 정리
  if command -v bash &>/dev/null && [ -f "tools/assemble-workspace.sh" ]; then
    bash tools/assemble-workspace.sh --clean 2>/dev/null || true
    echo "  [OK] workspace/ 심링크 정리"
  fi
fi

echo ""
echo "완료. workspace/input/ (${INPUT_COUNT}개 XML)은 보존되었습니다."
echo "다시 시작하려면: '변환해줘'"
