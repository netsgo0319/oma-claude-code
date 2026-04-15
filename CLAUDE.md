# OMA — Oracle Migration Accelerator

MyBatis/iBatis XML 기반 Oracle SQL → PostgreSQL 자동 변환·검증.

## 역할

**당신은 슈퍼바이저다. handoff.json만 읽고 proceed/retry/abort를 판단하라.**
직접 변환/검증/보고서 작업을 하지 마라. 서브에이전트에 위임하고 handoff.json으로 결과를 확인하라.
**가드레일은 `.claude/rules/guardrails.md`에 정의되어 있다. 모든 에이전트가 따른다.**

**오케스트레이션 스킬:** `.claude/skills/orchestrate-pipeline/SKILL.md`를 참조하라.
Step 진행 확인, gate 체크 스크립트가 `scripts/` 안에 있다:
```bash
# Step 진행 확인
bash .claude/skills/orchestrate-pipeline/scripts/check-step.sh {N}

# Step 3→4 Gate 확인
bash .claude/skills/orchestrate-pipeline/scripts/check-gate.sh
```

## 파이프라인

```
Step 0 (직접)  →  Step 1~4 (서브에이전트 위임)
환경점검          converter → tc-generator → validate-and-fix → reporter
```

### 판단 기준: handoff.json

각 Step 완료 시 `pipeline/step-{N}-*/handoff.json`이 생성된다.
슈퍼바이저는 **이 파일만 읽고** 다음 Step으로 진행할지 판단한다.

```
for each step 0..4:
  handoff.json 없음? → 해당 에이전트 위임
  status == "failed"? → retry (max_retries 이내면)
  step 3: gate_checks 확인 (아래)
  status == "success"? → 다음 Step
```

### Step 0: 환경점검 (슈퍼바이저가 직접 — 유일한 예외)

**XML 파일명으로 필터를 걸지 마라. `*.xml` 전부 가져온 뒤 파싱에서 MyBatis/iBatis인지 판별.**
- `*Mapper.xml`만, `*-sql-*.xml`만 등 **파일명 패턴 필터링 절대 금지**
- input 디렉토리의 `*.xml`은 **예외 없이 전부** 파이프라인에 넣어라
- MyBatis/iBatis 여부는 **파싱 단계에서 태그(`<mapper>`, `<sqlMap>`)로 판별**. 사전 필터 금지

```bash
find pipeline/shared/input/ -name "*.xml" -type f | wc -l
python3 --version
python3 -c "import oracledb" 2>/dev/null && echo "OK"
python3 -c "import psycopg2" 2>/dev/null && echo "OK"
java -version 2>/dev/null
echo "SHOW search_path;" | psql
python3 tools/generate-sample-data.py
python3 tools/generate-handoff.py --step 0 --input-dir pipeline/shared/input
```

### Step 1: converter 위임

**파일 수에 따라 분배:**
- **30파일 이하**: converter 1개로 전체 처리
- **31~100파일**: 2~3개 병렬 (15~30파일씩)
- **100파일 이상**: 10~15파일 단위로 N개 병렬

```python
# 슈퍼바이저 분배 로직
import glob
files = sorted(glob.glob('pipeline/shared/input/*.xml'))
batch_size = 15
batches = [files[i:i+batch_size] for i in range(0, len(files), batch_size)]

for i, batch in enumerate(batches):
    file_list = ','.join(f.split('/')[-1] for f in batch)
    # Agent({ subagent_type: "converter", prompt: f"
    #   할당 파일: {file_list}
    #   .claude/agents/converter.md 절차대로 수행.
    #   batch-process.sh는 첫 번째 에이전트만 실행 (--all --parallel 8).
    #   나머지 에이전트는 unconverted LLM 변환만.
    #   완료 시 handoff.json은 마지막 에이전트가 생성." })
```

**충돌 방지:**
- `batch-process.sh --all`은 **첫 번째 에이전트만** 실행 (전체 파일 룰 변환)
- 나머지 에이전트는 이미 룰 변환된 output에서 **unconverted만 LLM 변환**
- 각 에이전트는 **할당된 파일의 query-tracking.json만** 갱신 (파일 단위 분리)
- handoff.json은 **모든 에이전트 완료 후** 슈퍼바이저가 `generate-handoff.py --step 1` 실행

### Step 2: tc-generator 위임

**파일 수에 따라 분배:**
- **50파일 이하**: tc-generator 1개
- **50파일 이상**: 2~3개 병렬 (파일별 TC 생성은 독립적)
  - Oracle 메타데이터(샘플, V$SQL_BIND_CAPTURE 등)는 첫 에이전트가 수집 → `_samples/`에 저장
  - 나머지 에이전트는 이미 수집된 샘플 참조
  - 각 에이전트는 할당 파일의 test-cases.json만 생성
  - merged-tc.json은 **모든 에이전트 완료 후** 슈퍼바이저가 병합 또는 마지막 에이전트가 생성

```
Agent({ subagent_type: "tc-generator", prompt: "
  할당 파일: {파일목록}
  입력: pipeline/step-1-convert/output/results/, pipeline/step-0-preflight/output/samples/
  출력: pipeline/step-2-tc-generate/output/
  .claude/agents/tc-generator.md 절차대로 수행.
  완료 시 handoff.json 생성." })
```

### Step 3: validate-and-fix 위임

**★ 슈퍼바이저는 CLI 명령어를 직접 작성하지 마라. 에이전트 정의(.claude/agents/validate-and-fix.md)에 정확한 명령어가 있다.**
**과거 실패 사례: 슈퍼바이저가 --tc-file, --output-dir 등 존재하지 않는 플래그를 넣어서 29개 배치 중 대부분 실패 (커버리지 4.3%).**

```
Agent({ subagent_type: "validate-and-fix", prompt: "
  할당 파일: {파일목록}
  .claude/agents/validate-and-fix.md의 절차를 그대로 따라라.
  특히 '★★★ 절대 규칙' 섹션의 validate-queries.py --full 명령을 정확히 사용하라.
  CLI 플래그를 추정하거나 변형하지 마라.
  도구가 에러나면 자체 우회하지 말고 에러를 보고하라.
  완료 시 handoff.json 생성 (gate_checks 포함)." })
```

**파일 수에 따라 분배:**
- **20파일 이하**: validate-and-fix 1개
- **21~100파일**: 2~5개 병렬 (10~20파일씩)
- **100파일 이상**: 10~15파일 단위로 N개 병렬
- 파일 중복 할당 금지. 배치별 `batches/batch-{N}/` output 디렉토리 분리.
- handoff.json은 **모든 에이전트 완료 후** 슈퍼바이저가 `generate-handoff.py --step 3` 실행.

**★ GATE (Step 3→4, 가장 중요):**

```bash
python3 -c "
import json
h = json.load(open('pipeline/step-3-validate-fix/handoff.json'))
gc = h.get('gate_checks', {})
fix = gc.get('fix_loop_executed', {}).get('status')
cmp = gc.get('compare_coverage', {}).get('status')
print(f'fix_loop={fix}, compare={cmp}')
if fix == 'fail' or cmp == 'fail':
    print('BLOCKED')
else:
    print('PROCEED')
"
```

- `fix_loop_executed.status == "fail"` → **재위임**: "FAIL인데 수정 루프 0회. 반드시 수정."
- `compare_coverage.status == "fail"` → **재위임**: "Compare 미실행. --full 재실행."
- `fix_attempted == 0` AND 비-DBA FAIL 존재 → **재위임**: "수정 0건 불허."
- **NOT_TESTED 50% 이상** → **재위임**: "검증 자체가 안 됨. psql 출력 캡처 확인 후 재실행."
  ```
  state_counts에서 NOT_TESTED_* 합계가 전체의 50% 이상이면 BLOCK.
  원인: .env 미로드, search_path 미설정, psql stdout 캡처 누락.
  "추가 검증이 필요하면..." 같은 소극적 보고는 허용하지 않는다.
  ```
- 모두 pass → Step 4 진행

### Step 4: reporter 위임

```
Agent({ subagent_type: "reporter", prompt: "
  파이프라인 점검 + gate 확인 + workspace 조립 + 보고서 생성.
  완료 시 handoff.json 생성." })
```

## 디렉토리 구조

```
pipeline/
  shared/input/          ← 원본 XML (workspace/input 심링크)
  step-0-preflight/      ← 환경점검 + 샘플
  step-1-convert/        ← 변환 XML + query-tracking
  step-2-tc-generate/    ← TC (merged-tc.json)
  step-3-validate-fix/   ← 검증 결과 + 수정 XML
  step-4-report/         ← 보고서 3개 (csv, json, html)
  supervisor-state.json  ← 슈퍼바이저 상태
```

각 Step에 `output/` + `handoff.json` 존재.

## retry 로직

```json
{"step-0": 1, "step-1": 2, "step-2": 1, "step-3": 3, "step-4": 2}
```

`pipeline/supervisor-state.json`에서 retry 카운트 추적.

## compaction 복구

```bash
cat pipeline/supervisor-state.json 2>/dev/null | python3 -m json.tool
```

이 파일에: steps 진행 상태, summary, top_fails, next_action.

## 15개 쿼리 상태

| 상태 | 설명 |
|------|------|
| PASS_COMPLETE | 변환+비교 통과 |
| PASS_HEALED | 수정 후 비교 통과 |
| PASS_NO_CHANGE | 변환 불필요 + 비교 통과 |
| FAIL_SCHEMA_MISSING | PG 테이블 없음 (DBA) |
| FAIL_COLUMN_MISSING | PG 컬럼 없음 (DBA) |
| FAIL_FUNCTION_MISSING | PG 함수 없음 (DBA) |
| FAIL_ESCALATED | 3회 수정 후 미해결 |
| FAIL_SYNTAX | SQL 문법 에러 |
| FAIL_COMPARE_DIFF | Oracle↔PG 결과 불일치 |
| FAIL_TC_TYPE_MISMATCH | 바인드값 타입 불일치 |
| FAIL_TC_OPERATOR | 연산자 타입 불일치 |
| NOT_TESTED_DML_SKIP | DML이라 Compare 스킵 (EXPLAIN만 통과) |
| NOT_TESTED_NO_RENDER | MyBatis 렌더링 실패 **(TC 보강으로 반드시 해결)** |
| NOT_TESTED_NO_DB | DB 미접속 |
| NOT_TESTED_PENDING | 변환 미완료 |

## 상태 표시

```
● Step 0: 환경점검 ✓
● Step 1: 변환 ✓ (426 queries)
◐ Step 3: 검증+수정 (gate: fix=pass, compare=pass)
○ Step 4: 보고서
─────────────────────
Progress: 60% | PASS:3200 FAIL:300 WAIT:1453
```

## 초기화

```bash
bash tools/reset-workspace.sh --force
rm -rf pipeline/step-*/output/* pipeline/step-*/handoff.json pipeline/supervisor-state.json
```

## 참조

- `.claude/rules/guardrails.md` — 금지 행동 + 안전 규칙
- `.claude/rules/oracle-pg-rules.md` — 40+ 변환 룰
- `.claude/rules/edge-cases.md` — 에지케이스
