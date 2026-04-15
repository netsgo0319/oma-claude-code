---
name: report-pipeline
description: Step 4 보고서 생성 파이프라인. reporter 에이전트가 최종 보고서를 만들 때 사용합니다. gate 확인 → workspace 조립 → query-matrix.json(유일한 데이터 소스) → HTML 리포트(4탭) → handoff 생성.
allowed-tools:
  - Bash
  - Read
---

# Report Pipeline

Step 4 보고서 생성의 전체 파이프라인.
**query-matrix.json이 보고서의 유일한 데이터 소스.**

## 사전 조건: Gate 확인

Step 3 handoff.json의 gate_checks를 확인:
```bash
python3 -c "
import json
h = json.load(open('pipeline/step-3-validate-fix/handoff.json'))
gc = h.get('gate_checks', {})
for name, check in gc.items():
    print(f'  {name}: {check.get(\"status\")}')
    if check.get('status') == 'fail':
        print(f'    BLOCKED: {check.get(\"detail\")}')
"
```
**gate fail이면 보고서 생성 불가. 슈퍼바이저에 반환.**

## 전체 실행 (gate 통과 후)

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/assemble-and-generate.sh
```

이 스크립트가 순서대로:
1. `assemble-workspace.sh` — pipeline → workspace 심링크 조립
2. `generate-query-matrix.py --json` — CSV + JSON 생성 (필드 완성도 검증 포함)
3. `generate-report.py` — HTML 리포트 (4탭: Overview, Explorer, DBA, Log)
4. 산출물 3개 존재+비어있지 않음 검증
5. `generate-handoff.py --step 4` — handoff 생성
