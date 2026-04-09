#!/bin/bash
# OMA Kiro Workspace Reset
# workspace/input/ 의 XML 원본은 보존하고, 나머지 중간 산출물을 모두 삭제합니다.
#
# Usage:
#   bash tools/reset-workspace.sh          # 확인 후 삭제
#   bash tools/reset-workspace.sh --force  # 확인 없이 삭제

set -e

WORKSPACE="workspace"

echo "==============================="
echo "  OMA Kiro Workspace Reset"
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

echo ""
echo "완료. workspace/input/ (${INPUT_COUNT}개 XML)은 보존되었습니다."
echo "다시 시작하려면: '변환해줘'"
