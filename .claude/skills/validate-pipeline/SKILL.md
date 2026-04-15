---
name: validate-pipeline
description: Step 3 검증 파이프라인. validate-and-fix 에이전트가 변환된 SQL을 검증할 때 사용합니다. workspace 준비 → MyBatis 렌더링(run-extractor.sh) → validate-queries.py --full → 결과 확인 → handoff 생성. 반드시 이 순서를 따르며, extractor를 빼먹으면 206건 Compare 실패합니다.
allowed-tools:
  - Bash
  - Read
disable-model-invocation: true
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
TypeHandler/OGNL 에러는 스크립트가 자동 처리 (stub 생성+재빌드). **직접 개입하지 마라.**

### 2단계: 검증 (--full 원자적)
```bash
python3 tools/validate-queries.py --full \
  --files {할당된 파일} \
  --extracted pipeline/step-3-validate-fix/output/extracted_pg/ \
  --output pipeline/step-3-validate-fix/output/validation/ \
  --tracking-dir pipeline/step-1-convert/output/results/
```
EXPLAIN + Execute + Compare를 한번에. 다른 방법 금지.
**성능 최적화**: EXPLAIN 실패 쿼리는 Execute/Compare에서 자동 제외. Compare는 배치 실행(DB 세션 1회).

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

## 참조 문서

- [검증 스키마](../../schemas/validated.schema.json)
- [handoff 스키마](../../schemas/handoff.schema.json)
