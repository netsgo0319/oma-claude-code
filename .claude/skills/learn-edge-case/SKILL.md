---
name: learn-edge-case
description: 변환 과정에서 발견된 새 패턴과 에지케이스를 steering에 축적하고 자동으로 PR 또는 Issue를 생성한다. 반복 패턴은 룰셋에, 새 패턴은 에지케이스에 등록한다.
---

## 학습 트리거

### 1. 반복 실패 → 성공
- review.json에서 fix_applied 분석
- 동일 패턴이 3회 이상 다른 파일에서 Reviewer를 거쳤으면 → 룰셋 추가 후보

### 2. 새로운 LLM 변환 패턴
- converted.json에서 method: "llm"인 변환 중
- .claude/rules/edge-cases.md에 없는 새 패턴 → 에지케이스 등록

### 3. 사용자 에스컬레이션 후 해결
- progress.json에서 status가 "escalated" → "success"로 변한 건
- 사용자의 수동 수정 내역을 분석하여 학습

## 처리 절차

1. workspace/results/ 전체 스캔

2. 학습 대상 식별 및 분류:
   - rule_candidate: 반복 패턴 (3회 이상)
   - edge_case: 새로운 복잡 패턴
   - manual_resolved: 사용자 해결 건

3. steering 파일 갱신:
   - rule_candidate → .claude/rules/oracle-pg-rules.md에 새 룰 추가
   - edge_case, manual_resolved → .claude/rules/edge-cases.md에 항목 추가

   edge-cases.md 항목 형식:
   ```markdown
   ### {패턴 이름}
   - **Oracle**: 원본 SQL 패턴/예시
   - **PostgreSQL**: 변환 결과/예시
   - **주의**: 변환 시 주의사항
   - **발견일**: {YYYY-MM-DD}
   - **출처**: {파일명}#{쿼리ID}
   - **해결 방법**: rule | llm | manual
   ```

4. Git 커밋:
   ```bash
   git add .claude/rules/edge-cases.md .claude/rules/oracle-pg-rules.md
   git commit -m "chore: add learned edge case - {패턴 요약}"
   ```

5. PR 생성 (steering 변경):
   ```bash
   git checkout -b learn/{date}-{pattern-slug}
   gh pr create \
     --title "chore: add edge case - {패턴 요약}" \
     --body "## 학습된 패턴\n\n- Oracle: ...\n- PostgreSQL: ...\n- 출처: {파일}#{쿼리}\n- 해결: {방법}"
   ```

6. Issue 생성 (사용자 에스컬레이션 해결 건):
   ```bash
   gh issue create \
     --title "edge case: {패턴 요약}" \
     --label "learned-pattern" \
     --body "## 에스컬레이션 해결\n\n- 원본: ...\n- 해결: ...\n- 파일: {파일}#{쿼리}"
   ```

7. Leader에게 요약 반환

## 주의사항
- steering 파일 변경 시 기존 내용을 훼손하지 않도록 append만 수행
- PR 브랜치명: learn/{date}-{pattern-slug} (예: learn/2026-04-09-nocycle-recursion)
- edge-cases.md에 이미 동일 패턴이 있으면 중복 등록하지 않음
