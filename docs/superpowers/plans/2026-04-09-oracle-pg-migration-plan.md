# Oracle→PostgreSQL Migration Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kiro custom agent 시스템을 구축하여 MyBatis/iBatis Oracle SQL을 PostgreSQL로 자동 변환, 검증, 학습한다.

**Architecture:** Leader 오케스트레이터가 Converter/Validator/Reviewer/Learner 서브에이전트를 호출. 파일 기반 통신으로 컨텍스트 격리. Steering에 룰셋/에지케이스 누적.

**Tech Stack:** Kiro CLI, Custom Agents (JSON), Skills (SKILL.md), Steering (Markdown), MCP Servers (Oracle/PostgreSQL)

**Spec:** `docs/superpowers/specs/2026-04-09-oracle-pg-migration-agent-design.md`

---

## Plan Structure

이 플랜은 4개 파트로 분리되어 있습니다:

| 파트 | 파일 | 태스크 | 내용 |
|------|------|--------|------|
| Part 1 | [part1-scaffolding-steering.md](./part1-scaffolding-steering.md) | Task 1~2 | 프로젝트 구조 + Steering 파일 |
| Part 2 | [part2-skills.md](./part2-skills.md) | Task 3~7 | 11개 스킬 + 레퍼런스 파일 |
| Part 3 | [part3-agents.md](./part3-agents.md) | Task 8~12 | 6개 에이전트 (프롬프트 + JSON) |
| Part 4 | [part4-integration.md](./part4-integration.md) | Task 13 | 통합 검증 + 최종 커밋 |
| Part 5 | [part5-test-generator.md](./part5-test-generator.md) | Task 14~16 | 테스트 케이스 생성 에이전트 + 검증 연동 |

## Task Overview

- [ ] **Task 1:** 프로젝트 스캐폴딩 (디렉토리 구조 + .gitignore)
- [ ] **Task 2:** Steering 파일 5개 (product, tech, oracle-pg-rules, edge-cases, db-config)
- [ ] **Task 3:** parse-xml 스킬 + mybatis-ibatis-tag-reference
- [ ] **Task 4:** rule-convert 스킬 + rule-catalog 레퍼런스
- [ ] **Task 5:** llm-convert 스킬 + 패턴 레퍼런스 3개
- [ ] **Task 6:** 검증 스킬 3개 (explain-test, execute-test, compare-test)
- [ ] **Task 7:** report + learn-edge-case 스킬
- [ ] **Task 8:** Leader 에이전트 (프롬프트 + JSON)
- [ ] **Task 9:** Converter 에이전트 (프롬프트 + JSON)
- [ ] **Task 10:** Validator 에이전트 (프롬프트 + JSON)
- [ ] **Task 11:** Reviewer 에이전트 (프롬프트 + JSON)
- [ ] **Task 12:** Learner 에이전트 (프롬프트 + JSON)
- [ ] **Task 13:** 통합 검증 + 최종 커밋
- [ ] **Task 14:** generate-test-cases 스킬 + Oracle 딕셔너리 쿼리 레퍼런스
- [ ] **Task 15:** Test Generator 에이전트 (프롬프트 + JSON)
- [ ] **Task 16:** Validator 스킬/프롬프트/Leader 연동 업데이트

## Execution Order

```
Task 1 (scaffolding)
  └→ Task 2 (steering) ─── foundation, all agents reference these
       └→ Task 3~7 (skills) ─── can be parallel
       └→ Task 14 (test-cases skill) ─── can be parallel with 3~7
            └→ Task 8~12 (agents) ─── can be parallel, depend on skills + steering
            └→ Task 15 (test-generator agent)
                 └→ Task 16 (validator/leader integration update)
                      └→ Task 13 (integration verification)
```
