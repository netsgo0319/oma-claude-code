---
inclusion: always
---

# 기술 스택 & 의존성

## 에이전트 런타임
- Claude Code CLI + Custom Agent (Markdown)
- 모델:
  - 오케스트레이터/분석: claude-opus-4.6 (1M context)
  - 변환/검증: claude-sonnet-4.6 (1M context)

## DB 연결
- Oracle: sqlplus CLI (db-oracle 스킬 참조)
- PostgreSQL: psql CLI (db-postgresql 스킬 참조)
- 접속 정보: 환경변수로 관리 (.env)

## 외부 도구
- gh CLI: PR/Issue 자동 생성
- git: 형상관리
- Java 11+ / Gradle: MyBatis SQL Extractor (선택)

## 파일 형식
- 입력: MyBatis 3.x / iBatis 2.x XML
- 중간 산출물: JSON (버전별)
- 최종 산출물: XML + HTML 리포트 + Markdown 리포트

## 디렉토리 규약
- workspace/input/       — 원본 (불변)
- workspace/output/      — 최종 변환 결과
- workspace/results/     — 버전별 중간 산출물 ({filename}/v{n}/)
- workspace/results/_validation/ — EXPLAIN/실행 검증 스크립트 + 결과
- workspace/results/_extracted/  — MyBatis 추출 결과
- workspace/reports/     — 리포트 (migration-report.html 등)
- workspace/progress.json — 진행 상황 추적
- workspace/logs/        — 감사 로그 (activity-log.jsonl)

## 에이전트 구성
- 오케스트레이터 (메인 세션)
- converter: 변환 서브에이전트
- validate-and-fix: 검증 + 수정 루프 서브에이전트

## 파이프라인
Step 0 → Step 1 → Step 2 → Step 3 → Step 4

## 도구 (Python/Java/Shell)

| 도구 | Step | 역할 |
|------|------|------|
| `tools/xml-splitter.py` | Step 1 | 대형 XML을 쿼리 단위로 분할 |
| `tools/parse-xml.py` | Step 1 | chunk → parsed.json (Oracle 패턴 감지) |
| `tools/query-analyzer.py` | Step 1 | 의존성 그래프 + 복잡도 L0~L4 + 위상 정렬 |
| `tools/oracle-to-pg-converter.py` | Step 1 | 기계적 SQL 변환 (40+ 룰, CDATA/멀티라인/ROWNUM/INTERVAL) |
| `tools/validate-queries.py` | Step 2 | EXPLAIN (--local) + 실행 (--execute) + SSM 원격 + Integrity Guard |
| `tools/generate-test-cases.py` | Step 1 | 테스트 케이스 자동 생성 (V$SQL_BIND_CAPTURE, 컬럼 통계, FK) |
| `tools/generate-report.py` | Step 4 | 전체 결과 종합 → 단일 HTML 리포트 |
| `tools/run-extractor.sh` | Step 2 | MyBatis SQL 추출 + 검증 (빌드/추출/EXPLAIN/실행 원커맨드) |
| `tools/mybatis-sql-extractor/` | Step 2 | Java — SqlSessionFactory + BoundSql (DTO 자동 대체, 파일별 독립 처리) |
| `tools/reset-workspace.sh` | 초기화 | workspace 초기화 (input 보존) |
