#!/usr/bin/env python3
"""
Hook 스크립트: TC 커버리지 검증.
SubagentStop hook에서 호출 — tc-generator 에이전트 종료 시 TC가 충분한지 확인.
"""
import glob
import json
from pathlib import Path


def check():
    # merged-tc.json 확인
    for p in ['pipeline/step-2-tc-generate/output/merged-tc.json',
              'workspace/results/_test-cases/merged-tc.json']:
        if Path(p).exists():
            merged = json.loads(Path(p).read_text(encoding='utf-8'))
            tc_qids = len(merged)
            break
    else:
        return  # TC 생성 안 됨 (Step 2 미완료)

    # 전체 쿼리 수
    total_qids = 0
    for f in glob.glob('pipeline/step-1-convert/output/results/*/v1/parsed.json'):
        try:
            data = json.loads(Path(f).read_text(encoding='utf-8'))
            total_qids += len(data.get('queries', []))
        except Exception:
            pass

    if total_qids == 0:
        return

    coverage = round(tc_qids / total_qids * 100, 1)

    # LLM TC 확인
    llm_count = 0
    for f in glob.glob('pipeline/step-2-tc-generate/output/per-file/*/v1/test-cases.json'):
        try:
            data = json.loads(Path(f).read_text(encoding='utf-8'))
            for tcs in data.values():
                for tc in tcs:
                    if isinstance(tc, dict) and tc.get('source') == 'LLM':
                        llm_count += 1
        except Exception:
            pass

    if coverage < 80:
        print(f"⚠️  TC COVERAGE: {tc_qids}/{total_qids} ({coverage}%) — 80% 미만!")
        print(f"    LLM TC: {llm_count}건")
        if llm_count == 0:
            print(f"❌  LLM TC 0건 — boto3/LLM_TC_REGIONS/LLM_TC_ENABLED 확인")
        print(f"    generate-test-cases.py 재실행 필요")
    else:
        print(f"✅  TC COVERAGE: {tc_qids}/{total_qids} ({coverage}%), LLM: {llm_count}건")


if __name__ == '__main__':
    check()
