---
inclusion: always
---

# Oracle → PostgreSQL Migration Accelerator

## 목적
MyBatis/iBatis XML 기반 Oracle SQL을 PostgreSQL로 자동 변환하고
검증하는 Claude Code 에이전트 시스템.

## 워크플로우
Step 0: 사전 점검 (XML 존재, sqlplus/psql 설치, DB 접속 테스트)
Step 1: 파싱 + 룰 변환 (XML 파싱, 룰 기반 40+ 변환, LLM 복합 변환)
Step 2: TC 생성 (테스트 케이스 생성)
Step 3: 검증 + 수정 루프 (EXPLAIN → 실행 → Oracle/PG 비교 → 실패 시 수정+재검증, 최대 3회)
Step 4: 리포트 (Query Matrix + HTML 리포트)

## 서브에이전트
- converter: Oracle→PG SQL 변환 (룰 + LLM)
- validate-and-fix: 검증 + 실패 시 수정 루프

## 산출물
- 변환된 XML 파일 (workspace/output/)
- 버전별 중간 결과 (workspace/results/{file}/v{n}/)
- EXPLAIN/실행 검증 결과 (workspace/results/_validation/)
- **통합 HTML 리포트 (workspace/reports/migration-report.html)**
- 변환 리포트 Markdown (workspace/reports/conversion-report.md)

## 사용법
1. workspace/input/ 에 변환 대상 XML 배치
2. .env 파일에 Oracle/PostgreSQL 접속 정보 설정
3. `/convert` 명령으로 파이프라인 실행
