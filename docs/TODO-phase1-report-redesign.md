# TODO: Phase 1 보고서 톤앤매너 통일

> 상태: **미구현**
> 우선순위: 중간 (기능 동작에 영향 없음, UX 일관성)

## 목표

Phase 1(스키마 마이그레이션)의 보고서를 Phase 2(앱 마이그레이션)와 동일한 디자인으로 수정.
현재 Phase 1 보고서는 Strands SDK의 `analysis_tools.py`가 자체 생성하며, Phase 2와 스타일이 다름.

## 대상 파일

```
oma-migration/schema-migration/src/oma/tools/analysis_tools.py
```

- 크기: ~106KB
- 위치: `/tmp/oma-migration/schema-migration/src/oma/tools/analysis_tools.py`
- 보고서 생성 함수: `generate_html_report()` (파일 내 검색)

## 수정 사항

### 1. 디자인 통일
- Phase 2 보고서의 CSS 변수 (다크 테마, `--bg`, `--fg`, `--success`, `--fail` 등) 적용
- 탭 구조 (Overview, Explorer, DBA, Log) → Phase 1용으로 변형 (Overview, Objects, Data, Log)
- 카드 레이아웃, 테이블 스타일 통일

### 2. "Phase 1: Schema Migration" 라벨
- 보고서 제목에 "Phase 1: Schema Migration" 명시
- 향후 Phase 2 보고서와 나란히 볼 때 어느 Phase인지 구분

### 3. Phase 2 보고서 CSS/JS 참조
- Phase 2 보고서 CSS: `tools/generate-report.py` L620~660
- Phase 2 보고서 JS 패턴: `tools/generate-report.py` L870~1000

## 접근 방법

1. `analysis_tools.py`에서 `generate_html_report` 함수 찾기
2. HTML 템플릿 부분을 Phase 2 CSS로 교체
3. 기존 데이터 바인딩 로직은 유지 (Strands 결과 구조)
4. 테스트: Phase 1 보고서 생성 후 브라우저에서 확인

## 제약

- Phase 1은 Strands SDK 기반이라 `generate-report.py`를 직접 호출 불가
- `analysis_tools.py` 내부의 HTML 생성 코드를 수정해야 함
- 106KB 파일이라 컨텍스트 주의 — 보고서 관련 부분만 집중

## 참조

- Phase 2 보고서: `tools/generate-report.py` (oma-claude-code)
- Phase 1 보고서: `schema-migration/src/oma/tools/analysis_tools.py` (oma-migration)
- 디자인 스펙: Phase 2 HTML 보고서 실물 (`pipeline/step-4-report/output/migration-report.html`)
