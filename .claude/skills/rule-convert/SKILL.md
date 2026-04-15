---
name: rule-convert
description: Oracle SQL을 PostgreSQL로 룰 기반 변환. converter 에이전트가 NVL→COALESCE, DECODE→CASE, SYSDATE→CURRENT_TIMESTAMP 등 40+ 패턴을 기계적으로 치환할 때 사용합니다. oracle-pg-rules.md 룰셋을 참조합니다.
disable-model-invocation: true
---

## 입력
- `pipeline/step-1-convert/output/results/{filename}/v{n}/parsed.json`

## 참조 문서

- [40+ 룰 카탈로그](references/rule-catalog.md) — 각 룰의 변환 예시 + 엣지 케이스
- `.claude/rules/oracle-pg-rules.md` — 전체 룰셋 (항상 로드됨)
- `.claude/rules/edge-cases.md` — 과거 실행에서 학습된 패턴 (우선 적용)

## 처리 체크리스트

```
룰 변환 진행:
- [ ] 1. parsed.json에서 oracle_tags="rule" 쿼리 필터링
- [ ] 2. oracle-pg-rules.md + edge-cases.md 로드
- [ ] 3. 각 쿼리에 룰 적용 (아래 순서)
- [ ] 4. 동적 SQL 분기별 각각 적용 (<if>, <choose>, <foreach>)
- [ ] 5. 잔존 Oracle 구문 스캔 → 있으면 LLM 에스컬레이션
- [ ] 6. 변환 XML + converted.json 생성
- [ ] 7. 결과 검증: 잔존 0건 확인
```

## 룰 적용 순서 (반드시 이 순서)

1. **함수 변환**: NVL→COALESCE, DECODE→CASE, NVL2→CASE WHEN 등
2. **조인 변환**: (+) → ANSI LEFT/RIGHT JOIN
3. **데이터 타입**: VARCHAR2→VARCHAR, NUMBER→NUMERIC (DDL 포함 시)
4. **날짜 포맷**: TO_DATE/TO_CHAR 내 RR→YY, HH24→HH24, FF→MS
5. **기타 구문**: DUAL 제거, MINUS→EXCEPT, ROWNUM→LIMIT
6. **MyBatis 특수**: selectKey, #{param} 보존 (변환 금지!)

## 잔존 검사 (피드백 루프)

변환 후 반드시 잔존 스캔:
```
정규식: NVL\(|DECODE\(|(?<!\#\{)SYSDATE|ROWNUM|\(\+\)|FROM\s+DUAL
```
- 잔존 0건 → confidence: "high", method: "rule"
- 잔존 있음 → 해당 쿼리를 oracle_tags: "llm"으로 에스컬레이션

## 주의사항

- 하나의 쿼리에 여러 룰 중복 적용 가능 (NVL + SYSDATE + DUAL)
- **#{param} 안의 키워드는 변환 금지** — `#{sysdate}`는 MyBatis 파라미터, bare `SYSDATE`만 변환
- 동적 SQL 태그 속성(test 조건)은 변환 안 함 — SQL 본문만
- edge-cases.md에 있으면 일반 룰보다 우선 적용

## 출력

- `pipeline/step-1-convert/output/xml/{filename}.xml` — 변환 XML
- `pipeline/step-1-convert/output/results/{filename}/v{n}/converted.json` — 메타데이터
