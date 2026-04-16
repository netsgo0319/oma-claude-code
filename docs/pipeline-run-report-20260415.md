# Daiso Migration Pipeline 실행 보고서

**실행일**: 2026-04-15
**대상**: 431개 XML 파일, 7개 프로젝트 (daiso-wms 192, daiso-ams 91, daiso-oms 70, daiso-batch 48, daiso-wif 19, daiso-api 5, 기타 6)

## 파이프라인 실행 요약

| Step | 소요 | 결과 |
|------|------|------|
| Step 0: 환경점검 | ~1분 | 431 XML, Oracle/PG 접속 OK, 바인드변수 5,350쿼리 |
| Step 1: 변환 | ~20분 | 8,924 룰 적용 + ~208 LLM 변환, 4,972 쿼리 |
| Step 2: TC 생성 | ~2분 | 19,956 TC (CUSTOM 4,095 + BRANCH 6,633 + INFERRED 4,131) |
| Step 3: 검증+수정 | ~30분 | 29개 배치 병렬, ~90건 XML 수정 |
| Step 4: 보고서 | ~2분 | query-matrix.csv/json + HTML 리포트 |

## 검증 결과 (4,974 쿼리)

| 상태 | 건수 | 비율 |
|------|------|------|
| PASS_COMPLETE | 1,293 | 26.0% |
| PASS_HEALED | 3 | 0.1% |
| FAIL_SYNTAX | 858 | 17.2% |
| FAIL_SCHEMA_MISSING | 534 | 10.7% |
| NOT_TESTED_NO_RENDER | 584 | 11.7% |
| NOT_TESTED_DML_SKIP | 454 | 9.1% |
| FAIL_COLUMN_MISSING | 446 | 9.0% |
| FAIL_COMPARE_DIFF | 306 | 6.2% |
| FAIL_FUNCTION_MISSING | 296 | 5.9% |
| FAIL_TC_TYPE_MISMATCH | 115 | 2.3% |
| FAIL_TC_OPERATOR | 72 | 1.4% |
| FAIL_ESCALATED | 13 | 0.3% |

## 실패 원인 분석

### 1. 추출 경로 오류 (~800건+, 가장 큰 원인)
- `validate-queries.py`에 `--extracted workspace/results/_extracted`(Oracle)를 전달
- 올바른 경로: `--extracted workspace/results/_extracted_pg`(PG 변환)
- Oracle SQL이 PG EXPLAIN에 테스트되어 NVL, DECODE 등이 당연히 실패

### 2. GRIDPAGING 프레임워크 (~310건)
- `#{GRIDPAGING_ROWNUMTYPE_TOP/BOTTOM}` — Java 런타임 페이징 주입
- 정적 추출 시 빈값으로 치환 → invalid SQL

### 3. DBA 스키마 누락 (1,276건)
- `tt_*` 접두사 테이블 (TMS 모듈) PG 미생성
- 특정 컬럼, 스토어드 프로시저 미생성
- 일부(~188건)는 추출 아티팩트가 DBA로 오분류

### 4. TC 바인드 타입 (187건)
- `'20260115'` → smallint 오버플로
- `varchar = integer` 암묵적 캐스팅 불가

### 5. 수정 루프 미실행 (FAIL 코드 1,364건 중 80%)
- 에이전트가 "추출 아티팩트"로 판단하여 수정 건너뜀
- fix-loop SKILL.md에 아티팩트 판별→재검증 절차가 없었음

## 개선 사항 (이번 커밋)

1. **validate-queries.py**: `_extracted_pg` 자동 감지 우선순위 추가, `--extracted-pg` 옵션 신설
2. **validate-queries.py**: GRIDPAGING SQL 정리 로직 추가
3. **oracle-to-pg-converter.py**: FROM DUAL 정규식 `re.DOTALL` 플래그 추가, residual에 DUAL 추가
4. **validate-pipeline SKILL.md**: `--extracted` 경로를 `_extracted_pg`로 명시, 경고 추가
5. **fix-loop SKILL.md**: 추출 아티팩트 판별 절차 추가 (xml_after 확인→재검증)
6. **converter.md**: residual_patterns 확인 의무화 (LLM 변환 후)
7. **validate-and-fix.md**: `--extracted _extracted_pg` 경로 주의 추가

## 예상 개선 효과

| 수정 | 영향 | PASS율 기여 |
|------|------|-----------|
| 추출 경로 수정 | ~800건+ | +16% |
| GRIDPAGING 처리 | ~310건 | +6% |
| FROM DUAL 강화 | ~50건 | +1% |
| 합계 예상 | | 26% → 49%+ |

추가로 수정 루프 정상 실행 시 +10~15% 추가 개선 가능 (→ 60%+ 예상).
