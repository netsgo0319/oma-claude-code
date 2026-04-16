# TODO: PR 자동 리뷰 + 마이그레이션 피드백 루프 자동화

> 상태: **계획 완료, 구현 대기**
> 생성일: 2026-04-16

## 목표

두 EC2가 GitHub를 통해 자율적으로 피드백 루프를 돌게 자동화.

```
yejinkm-cc EC2 (코드 관리)                 omabox EC2 (실행)
┌──────────────────────────┐            ┌──────────────────────────┐
│ PR Reviewer (cron 10분)  │            │ Migration Runner (cron)  │
│                          │            │                          │
│ 1) gh pr list (open)     │  GitHub    │ main 새 커밋 감지 시:     │
│ 2) diff 분석 + 정합성    │◄──────────►│ 1) fresh clone            │
│ 3) 필요한 수정을 main에  │            │ 2) claude -p 마이그레이션 │
│    직접 반영 (merge 안함) │            │ 3) 결과 회고 (learn)      │
│ 4) PR close + 코멘트     │            │ 4) 이슈 정리 → PR 생성   │
│ 5) push main             │            │ 5) 보고서 → S3 업로드    │
└──────────────────────────┘            └──────────────────────────┘
```

**핵심 원칙:**
- PR을 그대로 merge하지 않음 → diff 분석 후 main에 직접 구현 → PR close
- omabox는 매번 fresh clone → 실행 → 회고 → fix PR + S3 업로드
- 세션 resume + 상태 파일로 누적 학습

---

## TODO 항목

### Part 1: yejinkm-cc — PR 자동 리뷰

- [ ] `gh auth login` (git remote의 PAT 활용)
- [ ] `tools/pr-review-checks.py` — PR diff 정합성 검증 스크립트
  - py_compile, 15-state enum, 스키마 정합성, isinstance, 필드명 표준화
- [ ] `.claude/skills/sync-prs/SKILL.md` — user-invocable `/sync-prs`
  - PR diff 분석 → main에 직접 반영 → PR close + 코멘트
- [ ] `tools/auto-sync-prs.sh` — cron 실행 스크립트
  - `--resume SESSION_ID` + `sync-state.json` 상태 파일
- [ ] CronCreate 등록 (매 10분)

### Part 2: omabox — 마이그레이션 러너

- [ ] `tools/auto-migration-runner.sh` — main 감지 + fresh clone + 실행
  - `claude -p` 실행 (서브에이전트 + 스킬 전부 동작)
  - omabox 기존 프롬프트 포함 (DB 가이드, 바인드 변수, 실행 규칙)
  - `--resume SESSION_ID` + `migration-state.json`
  - S3 업로드 fallback
  - 일일 최대 7회 제한

### Part 3: omabox 전용 스킬

- [ ] `.claude/skills/create-fix-pr/SKILL.md` + scripts/
  - 이슈 분류 → fix 브랜치 + PR (body 템플릿: 원인/수정/S3 링크)
- [ ] `.claude/skills/upload-report/SKILL.md` + scripts/
  - S3 경로: `s3://oma-896586841913/reports/{YYYYMMDD-HHMMSS}/`
- [ ] `.claude/skills/retrospective/SKILL.md`
  - learn + create-fix-pr + upload-report 통합

### Part 4: 안전장치

- [ ] PR 리뷰 기준 (런타임 파일 제외, 보고서만 PR은 skip)
- [ ] main push 전 검증 (py_compile, enum, 스키마)
- [ ] 일일 카운터 (omabox 7회, yejinkm-cc idle)

### 검증

- [ ] `/sync-prs` 수동 실행 → 열린 PR 처리 확인
- [ ] `auto-migration-runner.sh` dry-run → S3 경로 확인
- [ ] 전체 루프 1회: omabox PR → yejinkm-cc 반영 → omabox pull

---

## 상세 설계

### omabox 마이그레이션 프롬프트 (검증됨)

```
마이그레이션 파이프라인을 시작하세요.

<리소스>
- DB 연결 가이드: `~/workspace/yejinkm/DB-CONNECTION-GUIDE.md`
- XML 소스: 이미 input에 들어가있음.
- 바인드 변수: `/home/ec2-user/workspace/yejinkm/daiso-bind-variable-samples/`

<실행 규칙>
- 분석에서 그치지 않고 실제 수정 후 재검증 루프를 빠짐없이 수행할 것
- Compare까지 통과한 것만 성공으로 처리할 것
- 진행 중 질문은 최소화하고 최선의 판단으로 자동화하여 진행할 것
- 최종 실패 쿼리는 query_matrix.json에 쿼리별 시도 이력과 TC를 상세히 기록할 것
- 프로젝트 간 파일명·쿼리명 중복 가능성이 있으므로 반드시 프로젝트명을 prefix로 붙여 구분할 것
- 한국어로 답할 것

<완료 후 필수>
1) retrospective 스킬 실행 (learn + fix PR + S3 업로드)
2) migration-state.json 갱신 (pass_rate, patterns_found, s3_path)
3) 발견된 이슈는 create-fix-pr 스킬로 PR 생성
```

### S3 보고서 네이밍 규칙

```
s3://oma-896586841913/reports/
  20260415-143022/
    migration-report.html
    query-matrix.json
    query-matrix.csv
    learning/
      run-20260415.json
      cumulative.json
      promotion-candidates.md
```

### 상태 파일 구조

**sync-state.json (yejinkm-cc):**
```json
{
  "reviewed_prs": [8, 9],
  "last_run": "2026-04-16T03:00:00",
  "patterns_found": ["TIMESTAMP_MINUS_INT", "TRUNC_NUMERIC"],
  "last_main_commit": "2803dd8",
  "total_fixes_applied": 23
}
```

**migration-state.json (omabox):**
```json
{
  "runs": [
    {
      "timestamp": "20260416-091500",
      "main_commit": "2803dd8",
      "pass_rate": "49.2%",
      "s3_path": "s3://oma-896586841913/reports/20260416-091500/",
      "prs_created": [10, 11],
      "patterns_found": ["TRUNC_NUMERIC", "REGEXP_INSTR"]
    }
  ],
  "cumulative_patterns": ["TIMESTAMP_MINUS_INT", "TRUNC_NUMERIC", "REGEXP_INSTR"],
  "total_runs": 3,
  "best_pass_rate": "49.2%"
}
```
