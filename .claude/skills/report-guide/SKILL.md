---
name: report-guide
description: HTML 리포트 가이드. reporter 에이전트가 4탭(Overview/Explorer/DBA/Log) 드릴다운 리포트를 생성할 때 참조합니다. query-matrix.json이 유일한 데이터 소스입니다.
---

## 입력

- workspace/progress.json
- workspace/results/*/v*/query-tracking.json (쿼리별 추적 — before/after SQL, EXPLAIN, TC, timing)
- workspace/results/*/v*/parsed.json
- workspace/results/*/v*/conversion-report.json
- workspace/results/_validation/validated.json
- workspace/results/_validation/execute_validated.json
- workspace/results/_extracted/*-extracted.json (Step 3 렌더링 결과)
- workspace/logs/activity-log.jsonl

## 산출물: workspace/reports/migration-report.html

단일 self-contained HTML 파일. 브라우저에서 바로 열기 가능 (서버 불필요).

### 4-탭 구조

**Overview 탭:**
- **Migration Readiness %** 카드 (전체 너비 — verified OK / needs attention / escalated)
- Step 진행 막대 (Step별 소요시간, done/running/pending)
- 요약 카드 (파일수, 쿼리수, EXPLAIN, Execute, Compare Oracle vs PG, 패턴수)
- Oracle 패턴 분포 차트
- 복잡도 분포 차트 (L0~L4)
- MyBatis 추출 결과 테이블

**Query Detail 탭:**
- 접기/펼치기 파일 목록 (파일별 compare match/mismatch 표시)
- 파일 클릭 → 쿼리 목록 펼침
- 쿼리 클릭 → 상세 펼침:
  - Oracle SQL / PostgreSQL SQL 나란히 (syntax highlighting)
  - 적용된 패턴, 룰, 변환 방법
  - EXPLAIN 결과 (pass/fail + plan/error)
  - 실행 결과 (row count, duration)
  - **Oracle vs PG Compare** (쿼리별 TC 단위 비교 — match/mismatch + 에러 분류 + 액션 추천)
  - 테스트 케이스별 Oracle/PG 결과 비교
  - 타이밍 (parse, convert, explain, execute, total)
  - 버전 히스토리 (v1→v2→v3, 각 시도의 status/error/fix)

**Timeline 탭:**
- activity-log.jsonl 기반 시간순 이벤트 목록
- 이벤트 타입별 색상 구분

**Log 탭:**
- 전체 활동 로그
- 필터 버튼 (All, Error, Decision, Learning, Warning)
- 텍스트 검색

### 기술 특성
- 순수 HTML/CSS/JS (외부 의존 없음)
- Dark 테마
- SQL 키워드 syntax highlighting
- 5초 auto-refresh 토글
- 반응형 (노트북 화면 대응)

## 실행 방법

```bash
python3 tools/generate-report.py
# → workspace/reports/migration-report.html
```

## 처리 절차

1. workspace/progress.json 로드 → 전체 상태 파악
2. 모든 query-tracking.json 수집 → 쿼리별 상태 통합
3. parsed.json 폴백 (query-tracking.json 없는 파일용)
4. validated.json, execute_validated.json 로드 → 검증 결과
5. activity-log.jsonl 로드 → 타임라인
6. input/*.xml, output/*.xml 크기 비교
7. JSON으로 직렬화 → HTML 내 `const DATA = {...}` 임베드
8. JS가 클라이언트에서 렌더링
