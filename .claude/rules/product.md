---
inclusion: always
---

# Oracle → PostgreSQL Migration Accelerator

## 목적
MyBatis/iBatis XML 기반 Oracle SQL을 PostgreSQL로 자동 변환하고
검증하는 Kiro 에이전트 시스템.

## 워크플로우
Phase 0:   사전 점검 (XML 존재, sqlplus/psql 설치, DB 접속 테스트)
Phase 1:   XML 파싱 (MyBatis 3.x / iBatis 2.x 자동 판별, 쿼리 추출)
Phase 1.5: 의존성 분석 + 복잡도 분류 (L0~L4, 위상 정렬)
Phase 2:   레이어별 변환 (리프 쿼리부터, 룰 기반 + LLM, 병렬)
Phase 2.5: 테스트 케이스 생성 (V$SQL_BIND_CAPTURE, 컬럼 통계, FK 등)
Phase 3:   검증 (EXPLAIN → 실행 → Oracle/PG 비교 → Integrity Guard 14개 경고)
Phase 3 (MyBatis): MyBatis 엔진 검증 (Java 있을 때, 힐링 전)
Phase 4:   셀프 힐링 (실패 → 원인 분석 → 수정 → 재시도, 최대 3회)
Phase 5:   학습 (에지케이스 축적 → steering 갱신 → 자동 PR)
Phase 6:   DBA/Expert 최종 검증 (필수)
Phase 7:   리포트 (마지막)

## 산출물
- 변환된 XML 파일 (workspace/output/)
- 버전별 중간 결과 (workspace/results/{file}/v{n}/)
- EXPLAIN/실행 검증 결과 (workspace/results/_validation/)
- Phase 3 (MyBatis) 추출 결과 (workspace/results/_extracted/)
- **통합 HTML 리포트 (workspace/reports/migration-report.html)**
- 변환 리포트 Markdown (workspace/reports/conversion-report.md)
- 마이그레이션 가이드 (workspace/reports/migration-guide.md)

## 사용법
1. workspace/input/ 에 변환 대상 XML 배치
2. .env 파일에 Oracle/PostgreSQL 접속 정보 설정
3. oracle-pg-leader 에이전트 실행: `kiro-cli --agent oracle-pg-leader`
