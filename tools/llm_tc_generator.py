#!/usr/bin/env python3
"""
LLM-based Test Case Generator
Bedrock Claude로 SQL 문맥 기반 TC 생성. structured output 활용.

Usage:
    from llm_tc_generator import generate_tcs_batch
    results = generate_tcs_batch(queries, sample_hint={})
    # results = {query_id: [{name, params, source}]}
"""

import json
import os
import re
import time
from pathlib import Path

# ── Configuration ──

LLM_TC_MODEL = os.environ.get('LLM_TC_MODEL', 'global.anthropic.claude-sonnet-4-6')
LLM_TC_REGION = os.environ.get('AWS_REGION', 'us-east-1')
LLM_TC_MAX_BATCH = int(os.environ.get('LLM_TC_MAX_QUERIES_PER_BATCH', '10'))
LLM_TC_ENABLED = os.environ.get('LLM_TC_ENABLED', '1') == '1'
LLM_TC_MAX_TCS = int(os.environ.get('LLM_TC_MAX_TCS_PER_QUERY', '3'))


def _get_bedrock_client():
    """Bedrock Runtime 클라이언트 생성."""
    import boto3

    # Bearer token 방식 (Claude Code Bedrock 환경)
    bearer = os.environ.get('AWS_BEARER_TOKEN_BEDROCK', '')
    region = LLM_TC_REGION

    if bearer:
        from botocore.config import Config
        session = boto3.Session(region_name=region)
        client = session.client(
            'bedrock-runtime',
            config=Config(
                retries={'max_attempts': 3, 'mode': 'adaptive'}
            ),
            endpoint_url=f'https://bedrock-runtime.{region}.amazonaws.com',
        )
        # Bearer token은 환경변수로 boto3가 자동 인식하므로 별도 설정 불필요
        return client
    else:
        # 기본 AWS credentials (IAM role, profile 등)
        return boto3.client('bedrock-runtime', region_name=region)


def _build_prompt(queries_batch, sample_hint=None):
    """배치 프롬프트 생성. structured output 유도."""

    queries_text = ""
    for q in queries_batch:
        qid = q.get('query_id', '')
        sql = q.get('sql', '')[:500]  # 토큰 절약
        params = q.get('params', [])
        qtype = q.get('type', 'select')
        dynamic_tags = q.get('dynamic_tags', [])

        queries_text += f"""
--- Query: {qid} (type: {qtype}) ---
SQL: {sql}
Parameters: {json.dumps(params)}
Dynamic tags: {json.dumps(dynamic_tags[:5])}
"""

    sample_text = ""
    if sample_hint:
        sample_text = f"\nAvailable sample data (reference only):\n{json.dumps(sample_hint, ensure_ascii=False)[:1000]}\n"

    prompt = f"""You are a database test case generator. For each Oracle SQL query below, generate {LLM_TC_MAX_TCS} test cases with realistic parameter values.

Rules:
- Each test case must have ALL parameters filled with plausible values
- For date parameters (yyyymmdd, dt, date): use '20260115' format
- For Y/N flags (yn, delyn, useyn): use 'Y' or 'N'
- For numeric IDs (seq, num, idx): use small integers (1-100)
- For codes (cd, code, type, status): use short uppercase strings ('A', 'ACTIVE', 'Y')
- For text search (keyword, search, nm): use realistic Korean or English text
- For pagination (page, pageSize, limit, offset): use (1, 10) or (2, 20)
- If dynamic tags show <if test="X != null">, provide one TC with X=value and one with X=null
- For <foreach collection="list">, provide list=['1','2']
- DML queries (insert/update/delete): focus on WHERE clause parameters
{sample_text}
{queries_text}

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "query_id_1": [
    {{"name": "tc_llm_1", "params": {{"param1": "value1", "param2": "value2"}}}},
    {{"name": "tc_llm_2", "params": {{"param1": "other_value", "param2": null}}}}
  ],
  "query_id_2": [...]
}}"""

    return prompt


def _call_bedrock(prompt, max_retries=2):
    """Bedrock Claude API 호출. structured output."""
    client = _get_bedrock_client()

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.3,  # 약간의 다양성
        "messages": [
            {"role": "user", "content": prompt}
        ],
    })

    for attempt in range(max_retries + 1):
        try:
            response = client.invoke_model(
                modelId=LLM_TC_MODEL,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            result = json.loads(response['body'].read())
            text = result.get('content', [{}])[0].get('text', '')

            # JSON 추출 (마크다운 코드블록 안에 있을 수 있음)
            text = text.strip()
            if text.startswith('```'):
                text = re.sub(r'^```\w*\n?', '', text)
                text = re.sub(r'\n?```$', '', text)
                text = text.strip()

            return json.loads(text)

        except client.exceptions.ThrottlingException:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            print(f"  WARN: Bedrock throttled after {max_retries + 1} attempts")
            return {}
        except json.JSONDecodeError as e:
            print(f"  WARN: LLM response not valid JSON: {e}")
            if attempt < max_retries:
                continue
            return {}
        except Exception as e:
            print(f"  WARN: Bedrock call failed: {e}")
            return {}


def generate_tcs_batch(queries, sample_hint=None):
    """배치로 LLM TC 생성.

    Args:
        queries: [{query_id, sql, params: [str], type, dynamic_tags: [str]}]
        sample_hint: {table_name: [{col: val}]} 샘플 데이터 (참고용)

    Returns:
        {query_id: [{name, params, source}]}
    """
    if not LLM_TC_ENABLED:
        return {}

    if not queries:
        return {}

    results = {}
    total = len(queries)
    batches = [queries[i:i + LLM_TC_MAX_BATCH] for i in range(0, total, LLM_TC_MAX_BATCH)]

    print(f"  LLM TC: {total} queries in {len(batches)} batches (model: {LLM_TC_MODEL})")

    for bi, batch in enumerate(batches):
        prompt = _build_prompt(batch, sample_hint)
        raw = _call_bedrock(prompt)

        if not raw:
            continue

        for qid, tcs in raw.items():
            if not isinstance(tcs, list):
                continue
            cleaned = []
            for i, tc in enumerate(tcs):
                if isinstance(tc, dict) and 'params' in tc:
                    params = tc['params']
                elif isinstance(tc, dict):
                    # params 키 없이 직접 파라미터가 온 경우
                    params = tc
                else:
                    continue

                # None 값 정리
                params = {k: (v if v is not None else '') for k, v in params.items()}
                cleaned.append({
                    'name': tc.get('name', f'tc_llm_{i + 1}'),
                    'params': params,
                    'source': 'LLM',
                })
            if cleaned:
                results[qid] = cleaned

        if (bi + 1) % 5 == 0 or bi == len(batches) - 1:
            print(f"    batch {bi + 1}/{len(batches)}: {len(results)} queries generated")

    print(f"  LLM TC done: {len(results)} queries with TC")
    return results


def generate_tcs_for_query(sql, params, qtype='select', dynamic_tags=None, sample_hint=None):
    """단일 쿼리 LLM TC 생성 (디버깅/테스트용)."""
    queries = [{
        'query_id': 'test_query',
        'sql': sql,
        'params': params,
        'type': qtype,
        'dynamic_tags': dynamic_tags or [],
    }]
    results = generate_tcs_batch(queries, sample_hint)
    return results.get('test_query', [])


if __name__ == '__main__':
    # 테스트
    print("=== LLM TC Generator Test ===")
    print(f"Model: {LLM_TC_MODEL}")
    print(f"Region: {LLM_TC_REGION}")
    print(f"Enabled: {LLM_TC_ENABLED}")

    if LLM_TC_ENABLED:
        test_sql = "SELECT * FROM TB_USER WHERE USER_ID = #{userId} AND STATUS = #{status} AND REG_DATE >= #{startDate}"
        test_params = ['userId', 'status', 'startDate']
        tcs = generate_tcs_for_query(test_sql, test_params)
        print(f"\nGenerated {len(tcs)} TCs:")
        for tc in tcs:
            print(f"  {tc['name']}: {json.dumps(tc['params'], ensure_ascii=False)}")
    else:
        print("LLM TC disabled. Set LLM_TC_ENABLED=1 to enable.")
