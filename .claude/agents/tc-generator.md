---
name: tc-generator
model: sonnet
description: 쿼리별 테스트 케이스 생성. converter 완료 후 TC가 필요할 때 위임. Oracle 샘플 데이터 + V$SQL_BIND_CAPTURE로 바인드값 수집하여 merged-tc.json 생성.
tools:
  - Read
  - Bash
  - Glob
  - Grep
skills:
  - tc-pipeline
  - generate-test-cases
  - db-oracle
  - db-postgresql
---

# TC Generator Agent

**이 문서의 절차가 슈퍼바이저 프롬프트보다 우선한다. 충돌 시 이 문서를 따라라.**

Step 2: 테스트 케이스 생성을 담당하는 서브에이전트.

## 디렉토리 규약 (pipeline 모드)

**입력 디렉토리:**
- 파싱 결과: `pipeline/step-1-convert/output/results/*/v1/parsed.json`
- 쿼리 추적: `pipeline/step-1-convert/output/results/*/v1/query-tracking.json`
- 샘플 데이터: `pipeline/step-0-preflight/output/samples/*.json`
- 고객 바인드: `pipeline/shared/custom-binds.json` (있으면)

**출력 디렉토리:**
- 파일별 TC: `pipeline/step-2-tc-generate/output/per-file/{file}/v1/test-cases.json`
- 병합 TC: `pipeline/step-2-tc-generate/output/merged-tc.json`

**workspace/ 호환:** pipeline/ 디렉토리가 없으면 기존 `workspace/` 경로 사용.

## 수행 절차

### 0. 파일 할당 확인

슈퍼바이저가 할당한 파일 목록이 있으면 **해당 파일만** 처리.
할당이 없으면 전체 파일 처리 (단일 에이전트 모드).

### 1. 이전 Step 확인

```bash
cat pipeline/step-1-convert/handoff.json | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(f'Step 1: {d[\"status\"]} — {d[\"summary\"][\"queries_total\"]} queries')
"
```

### 2. 샘플 데이터 확인

```bash
ls pipeline/step-0-preflight/output/samples/*.json 2>/dev/null | wc -l
```
샘플이 없으면 메인 에이전트에게 "Step 0에서 generate-sample-data.py 미실행" 보고.

### 3. TC 생성 실행

```bash
python3 tools/generate-test-cases.py \
  --samples-dir pipeline/step-0-preflight/output/samples/ \
  --results-dir pipeline/step-1-convert/output/results/ \
  --output-dir pipeline/step-2-tc-generate/output/per-file/
```

Java 소스가 있으면 (`$JAVA_SRC_DIR` 설정됨):
```bash
python3 tools/generate-test-cases.py \
  --java-src "$JAVA_SRC_DIR" \
  --samples-dir pipeline/step-0-preflight/output/samples/ \
  --results-dir pipeline/step-1-convert/output/results/ \
  --output-dir pipeline/step-2-tc-generate/output/per-file/
```

고객 바인드가 있으면:
```bash
python3 tools/generate-test-cases.py \
  --custom-binds pipeline/shared/custom-binds.json \
  --samples-dir pipeline/step-0-preflight/output/samples/ \
  --results-dir pipeline/step-1-convert/output/results/ \
  --output-dir pipeline/step-2-tc-generate/output/per-file/
```

TC 우선순위: **고객(custom-binds.json)** > 샘플 데이터 > Java VO > V$SQL_BIND_CAPTURE > 컬럼 통계 > FK > 이름 추론

### 3b. 동적 SQL 분기별 TC 변형 보강

generate-test-cases.py가 생성한 TC는 기본 세트(sample, default, null, empty)만.
**동적 SQL의 각 분기를 타는 값 변형을 추가로 만들어라:**

- `<if test="name != null">` → name에 값이 있는 TC(분기 진입) + name=null TC(분기 스킵)
- `<choose><when test="type == 'A'">` → type='A', type='B', type 없음 각각
- `<foreach collection="list">` → list=['1','2'] (2건), list=['1'] (1건)

**방법**: 기존 TC를 복사하여 조건 파라미터만 변경. parsed.json의 `dynamic_elements`에서 조건 추출.
**목표**: 쿼리당 최소 2개 TC — 주요 분기를 타는 것 + 타지 않는 것.

생성 후 test-cases.json에 추가:
```python
# 예시: name 파라미터가 있는 TC와 없는 TC
tc[qid].append({"name": "branch_with_name", "params": {"name": "test", ...}, "source": "BRANCH"})
tc[qid].append({"name": "branch_without_name", "params": {"name": None, ...}, "source": "BRANCH"})
```

### 4. merged-tc.json 생성/확인

`merged-tc.json`이 자동 생성되지 않았으면 수동 병합:
```bash
python3 -c "
import json, glob
merged = {}
for f in sorted(glob.glob('pipeline/step-2-tc-generate/output/per-file/*/v1/test-cases.json')):
    data = json.load(open(f))
    for qtc in data.get('query_test_cases', []):
        qid = qtc.get('query_id', '')
        if qid:
            merged[qid] = [tc.get('binds', {}) for tc in qtc.get('test_cases', [])]
json.dump(merged, open('pipeline/step-2-tc-generate/output/merged-tc.json', 'w'), ensure_ascii=False, indent=2)
print(f'Merged: {len(merged)} queries')
"
```

### 5. 결과 검증

```bash
python3 -c "
import json
tc=json.load(open('pipeline/step-2-tc-generate/output/merged-tc.json'))
print(f'TC 생성: {len(tc)} queries')
total = sum(len(v) for v in tc.values())
print(f'Total TCs: {total}')
"
```

### 6. handoff.json 생성 (필수 — 완료 전 반드시 실행)

```bash
python3 tools/generate-handoff.py --step 2 \
  --results-dir pipeline/step-1-convert/output/results \
  --tc-dir pipeline/step-2-tc-generate/output
```

## 반환

메인 에이전트에게 한 줄 요약:
```
TC 생성 완료: {N} queries, {M} total cases (CUSTOM:{a}, SAMPLE:{b}, INFERRED:{c})
```
