---
name: rule-convert-tool
description: oracle-to-pg-converter.py 도구 실행. converter 에이전트가 XML 파일의 Oracle SQL을 일괄 변환할 때 사용합니다. CDATA, 멀티라인 함수를 정확히 처리. LLM 변환 전에 반드시 먼저 실행합니다.
---

## 개요

LLM이 직접 정규식을 짜는 대신, 사전 제작된 Python 도구로 기계적 변환을 수행한다.
이 도구는 CDATA 블록 내부, 멀티라인 함수 호출(NVL(\n\t...\n)), 중첩 함수를 모두 처리한다.

## 사용법

### 단일 파일 변환
```bash
python3 tools/oracle-to-pg-converter.py workspace/input/{file}.xml workspace/output/{file}.xml --report workspace/results/{file}/v1/conversion-report.json
```

### 배치 변환 (전체 디렉토리)
```bash
python3 tools/oracle-to-pg-converter.py --dir workspace/input/ --outdir workspace/output/ --report-dir workspace/results/
```

### chunk 단위 변환 (xml-splitter 분할 후)
```bash
for chunk in workspace/results/{file}/v1/chunks/*.xml; do
  python3 tools/oracle-to-pg-converter.py "$chunk" "${chunk%.xml}.pg.xml"
done
```

## 변환 범위 (자동 처리)

| 카테고리 | 변환 항목 |
|---------|----------|
| 함수 | NVL->COALESCE, NVL2->CASE, DECODE->CASE, TO_NUMBER->CAST |
| 날짜 | SYSDATE->CURRENT_TIMESTAMP, ADD_MONTHS, MONTHS_BETWEEN, LAST_DAY, TRUNC |
| 문자열 | INSTR->POSITION, LISTAGG->STRING_AGG, WM_CONCAT->STRING_AGG |
| 정규식 | REGEXP_LIKE->~, REGEXP_REPLACE->regexp_replace, REGEXP_SUBSTR->substring |
| LOB | DBMS_LOB.SUBSTR->SUBSTRING, GETLENGTH->LENGTH, INSTR->POSITION |
| 기타 | FROM DUAL 제거, sequence->nextval(), MINUS->EXCEPT, 힌트->주석, BITAND->& |

## 변환하지 않는 것 (LLM에 위임)

| 패턴 | 이유 |
|------|------|
| CONNECT BY / START WITH | 구조적 변환 필요 (WITH RECURSIVE) |
| MERGE INTO | 구조적 변환 필요 (INSERT ON CONFLICT) |
| (+) 아우터 조인 | FROM/WHERE 재구성 필요 |
| PIVOT / UNPIVOT | 구조적 변환 필요 |
| ROWNUM 페이징 (3중) | 구조적 변환 필요 |
| KEEP DENSE_RANK | 서브쿼리 재작성 필요 |
| GREATEST/LEAST | NULL 시멘틱스 판단 필요 (경고만) |

## 변환 리포트 (conversion-report.json)

```json
{
  "filename": "UserMapper.xml",
  "total_replacements": 45,
  "rules_applied": {
    "NVL->COALESCE": 12,
    "DECODE->CASE": 8,
    "SYSDATE->CURRENT_TIMESTAMP": 5
  },
  "cdata_conversions": 3,
  "unconverted_count": 2,
  "unconverted": [
    {"pattern": "CONNECT BY (hierarchical query)", "severity": "needs_llm"},
    {"pattern": "(+) outer join", "severity": "needs_llm"}
  ]
}
```

## Converter 에이전트가 이 도구를 사용하는 방법

1. **먼저** rule-convert-tool 실행 (기계적 변환)
2. conversion-report.json의 unconverted 목록 확인
3. unconverted가 있으면 -> LLM(llm-convert 스킬)으로 나머지 변환
4. unconverted가 없으면 -> 변환 완료

**절대로 Python 정규식 스크립트를 직접 작성하지 않는다. 이 도구를 사용한다.**

## 참조 문서

- [변환 룰셋](../../rules/oracle-pg-rules.md)
- [에지케이스](../../rules/edge-cases.md)
