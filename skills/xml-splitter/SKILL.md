---
name: xml-splitter
description: 대형 MyBatis/iBatis XML 파일을 쿼리 단위로 분할한다. LLM 컨텍스트 한계를 우회하여 수만 줄 XML도 처리할 수 있게 한다.
---

## 개요

실제 운영 XML 파일은 수만 줄에 달할 수 있다. LLM의 컨텍스트 윈도우에 통째로 넣을 수 없으므로,
XML을 쿼리 단위로 분할하여 각각 독립적으로 처리한다.

## 사전 조건
- Python 3.x 설치 필요
- xml.etree.ElementTree (표준 라이브러리)

## 사용법

```bash
python3 tools/xml-splitter.py workspace/input/{filename}.xml workspace/results/{filename}/v1/chunks/
```

## 처리 절차

1. XML 파일을 Python xml.etree.ElementTree로 파싱
2. 루트 태그 확인 (<mapper> 또는 <sqlMap>)
3. 각 쿼리 요소를 개별 파일로 추출:
   - <sql> fragments → {id}.sql.xml
   - <select> → {id}.select.xml
   - <insert> → {id}.insert.xml
   - <update> → {id}.update.xml
   - <delete> → {id}.delete.xml
   - <resultMap> → {id}.resultmap.xml
   - <parameterMap> → {id}.parametermap.xml
4. 메타데이터 파일 생성: chunks/_metadata.json
   - 원본 파일명, namespace, 총 쿼리 수, chunk 파일 목록

## 출력 구조

```
workspace/results/{filename}/v1/chunks/
  _metadata.json        ← 원본 정보 + chunk 목록
  commonColumns.sql.xml ← <sql id="commonColumns">
  selectUserById.select.xml
  insertUser.insert.xml
  getOrgHierarchy.select.xml
  ...
```

## _metadata.json 형식

```json
{
  "source_file": "UserMapper.xml",
  "source_size_lines": 57652,
  "framework": "mybatis3",
  "namespace": "com.example.mapper.UserMapper",
  "total_chunks": 45,
  "chunks": [
    {"id": "commonColumns", "type": "sql", "file": "commonColumns.sql.xml", "lines": 5},
    {"id": "selectUserById", "type": "select", "file": "selectUserById.select.xml", "lines": 20},
    ...
  ]
}
```

## Leader가 이 스킬을 사용하는 방법

Phase 1에서:
1. 먼저 XML 파일 크기 확인 (wc -l)
2. 1000줄 이상이면 xml-splitter로 분할
3. 분할된 chunk를 개별적으로 parse-xml 처리
4. 1000줄 미만이면 기존 방식대로 직접 처리
