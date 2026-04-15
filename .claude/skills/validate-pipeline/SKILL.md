---
name: validate-pipeline
description: Step 3 검증 파이프라인 — workspace 준비 → MyBatis 렌더링 → --full 검증 → 결과 확인 → handoff 생성. validate-and-fix 에이전트가 사용.
allowed-tools:
  - Bash
  - Read
---

# Validate Pipeline

Step 3 검증의 전체 파이프라인을 순서대로 실행하는 스킬.
**각 단계를 건너뛰면 안 된다. 특히 1단계(extractor)를 빼먹으면 206건 Compare 실패한다.**

## 실행 순서

### 0단계: Workspace 준비
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/prepare-workspace.sh
```
pipeline → workspace 복사 + merged-tc.json 병합.

### 1단계: MyBatis 렌더링 (★ 필수)
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/run-extractor.sh
```
동적 SQL(`<if>`, `<choose>`, `<foreach>`) → 실행 가능 SQL 추출.
**이 단계 없이 2단계만 실행하면 정적 fallback → Compare 실패.**

### 2단계: 검증 (--full 원자적)
```bash
python3 tools/validate-queries.py --full \
  --files {할당된 파일} \
  --extracted pipeline/step-3-validate-fix/output/extracted_pg/ \
  --output pipeline/step-3-validate-fix/output/validation/ \
  --tracking-dir pipeline/step-1-convert/output/results/
```
EXPLAIN + Execute + Compare를 한번에. 다른 방법 금지.

### 3단계: 결과 확인
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/check-results.sh
```
0건이면 CRITICAL. 50% 미만이면 WARNING. 재실행 필요.

### 4단계: Handoff 생성
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/generate-handoff.sh
```
gate_checks 포함. 슈퍼바이저가 이것만 읽고 판단.

## 금지 목록

- psql -c "EXPLAIN ..." 직접 실행
- SQL 파일 직접 작성
- --full 없이 --generate, --local 따로 실행
- run-extractor.sh 없이 validate-queries.py 직접 실행
- Python으로 subprocess.run(['psql', ...])
