---
name: report-guide
description: HTML 리포트 가이드. reporter 에이전트가 4탭(Overview/Explorer/DBA/Log) 드릴다운 리포트를 생성할 때 참조합니다. query-matrix.json이 유일한 데이터 소스입니다.
---

## 핵심 원칙

**query-matrix.json이 유일한 데이터 소스.** 다른 파일에서 독립적으로 데이터를 모으지 않는다.

## 입력/출력

- **입력**: `pipeline/step-4-report/output/query-matrix.json` + `workspace/logs/activity-log.jsonl`
- **출력**: `pipeline/step-4-report/output/migration-report.html` (self-contained, 서버 불필요)

## 4탭 구조

| 탭 | 내용 | 데이터 소스 |
|----|------|-----------|
| **Overview** | 6카드 + Step Progress + 패턴/복잡도 차트 | query-matrix.json summary, file_stats |
| **Explorer** | 파일→쿼리 트리 + MyBatis XML diff + 렌더링 SQL diff | query-matrix.json queries[] |
| **DBA** | 누락 오브젝트 그룹핑 + Oracle 0건 쿼리 | query-matrix.json dba_objects, dba_zero_rows |
| **Log** | activity-log.jsonl 타임라인 + 필터 | activity-log.jsonl |

## 체크리스트

```
리포트 생성:
- [ ] query-matrix.json 존재 + 비어있지 않음 확인
- [ ] 필수 상위 필드: summary, file_stats, step_progress, queries
- [ ] 쿼리별 필수 필드: query_id, original_file, type, xml_before, xml_after, sql_before, sql_after, final_state
- [ ] HTML 파일 생성 + 크기 > 0 확인
- [ ] 브라우저에서 열었을 때 4탭 모두 렌더링
```

## 실행

```bash
python3 tools/generate-report.py --output pipeline/step-4-report/output/migration-report.html
```

## 기술 특성

- 순수 HTML/CSS/JS (외부 의존 없음), Dark 테마
- SQL syntax highlighting, 15-state 색상 배지
- Explorer: MyBatis XML diff (변환 전/후) + 렌더링 SQL diff

## 참조 문서

- [query-matrix.json 필드 정의](../../rules/guardrails.md)
- [handoff 스키마](../../schemas/handoff.schema.json)
