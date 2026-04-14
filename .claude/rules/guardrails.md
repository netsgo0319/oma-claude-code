---
inclusion: always
---

# OMA 가드레일 (모든 에이전트 필수 적용)

## 절대 금지 행동

### SQL 안전
- **DML은 PG: BEGIN/ROLLBACK + 5s timeout, Oracle: SELECT COUNT(*) WHERE**
- DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE 실행 금지
- statement_timeout 30초 설정 필수

### 파일 안전
- **workspace/ 아래에 임시 .py/.sh 파일을 만들지 마라.** 기존 도구만 사용
- output XML 수정 전 반드시 버저닝: `cp file file.v{N}.bak`

### MyBatis 파라미터
- **`#{param}`은 MyBatis 바인드 파라미터.** Oracle 구문이 아님. 변환 금지
- `#{sysdate}` → 그대로 유지. bare `SYSDATE`만 CURRENT_TIMESTAMP로 변환

### 검증 원칙
- **EXPLAIN 통과 ≠ 변환 성공.** Execute + Compare까지 필수
- **0건==0건도 유효한 PASS.** Compare를 스킵하지 마라
- 스키마 에러(relation/column/function_missing)는 수정 루프 돌리지 않고 즉시 DBA 마킹

### PG 환경
- **search_path 필수 확인.** 스키마가 public이 아니면 `SET search_path TO {schema}, public;`
- pgcrypto extension 확인 (PKG_CRYPTO 변환에 필수)

## 리더 전용 금지

- 리더가 직접 validate-queries.py를 실행하는 것 → **validate-and-fix에 위임**
- 리더가 직접 generate-report.py를 실행하는 것 → **reporter에 위임**
- "결과가 분산되어 있어 전체 통합 검증하겠다" → **reporter가 glob으로 통합**
- "전체 EXPLAIN 먼저 돌리고 그다음 Execute" → **--full 원자적 실행만**
- 배치 에이전트 결과를 무시하고 단일 재실행 → **기존 결과 덮어씌워짐**
