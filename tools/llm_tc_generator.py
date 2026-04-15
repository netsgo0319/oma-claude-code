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
    # SQL에서 테이블명 추출 → 해당 테이블 샘플만 첨부
    tables_needed = set()
    for q in queries_batch:
        qid = q.get('query_id', '')
        sql = q.get('sql', '')[:500]
        params = q.get('params', [])
        qtype = q.get('type', 'select')
        dynamic_tags = q.get('dynamic_tags', [])

        # 테이블명 추출
        for t in re.findall(r'\b(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)', sql, re.I):
            if t.upper() not in ('DUAL', 'SELECT', 'WHERE', 'SET', 'VALUES'):
                tables_needed.add(t.upper())

        queries_text += f"""
--- Query: {qid} (type: {qtype}) ---
SQL: {sql}
Parameters: {json.dumps(params)}
Dynamic tags: {json.dumps(dynamic_tags[:5])}
"""

    # 관련 테이블 샘플만 첨부 (토큰 효율)
    sample_text = ""
    if sample_hint:
        relevant = {}
        for tbl, rows in sample_hint.items():
            if tbl.upper() in tables_needed or any(tbl.upper() in t for t in tables_needed):
                # 컬럼명 + 샘플 2행만 (토큰 절약)
                if isinstance(rows, list) and rows:
                    relevant[tbl] = {
                        'columns': list(rows[0].keys()) if rows else [],
                        'sample_rows': rows[:2],
                    }
                elif isinstance(rows, dict) and 'columns' in rows:
                    relevant[tbl] = {
                        'columns': rows['columns'],
                        'sample_rows': rows.get('rows', [])[:2],
                    }
        if relevant:
            sample_text = f"\n## Table schemas and sample data\n{json.dumps(relevant, ensure_ascii=False, indent=1)}\n"

    prompt = f"""Generate {LLM_TC_MAX_TCS} test cases per query for Oracle→PostgreSQL migration validation.

    Analyze the SQL context (table names, column names, WHERE/JOIN conditions, data types) to infer realistic values.
    Each TC should test a different scenario — vary values meaningfully across TCs.

    Guidelines:
    - All parameter keys must be present in every TC
    - Values must be strings (even numbers: "1" not 1), except list parameters (string arrays like ["1","2"])
    - GRIDPAGING_* parameters = always empty string ""
    - If dynamic tags show <if test="X != null">, include one TC where X="" (branch off)
    - LIKE search parameters should include % wildcards (e.g. "%keyword%")
    - Date parameters: use YYYYMMDD format strings
    - Numeric range parameters (qty, amt, price): vary across small/medium/large values
    - List/array parameters: provide 2-3 element arrays
    - For DML queries, focus on realistic WHERE clause values
    {sample_text}
    ## Queries

    {queries_text}"""

    return prompt


def _call_bedrock(prompt, query_ids, max_retries=2):
    """Bedrock Claude API 호출. tool_use로 structured output 강제."""
    client = _get_bedrock_client()

    # tool_use 기반 structured output — JSON 스키마 강제
    tc_properties = {}
    for qid in query_ids:
        tc_properties[qid] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "TC 이름 (tc_llm_1 등)"},
                    "params": {"type": "object", "description": "파라미터명: 값 딕셔너리"},
                },
                "required": ["name", "params"],
            },
        }

    tool_def = {
        "name": "generate_test_cases",
        "description": "쿼리별 테스트 케이스를 생성하여 반환",
        "input_schema": {
            "type": "object",
            "properties": tc_properties,
            "required": query_ids,
        },
    }

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.3,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "tools": [tool_def],
        "tool_choice": {"type": "tool", "name": "generate_test_cases"},
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

            # tool_use 응답에서 input 추출
            for block in result.get('content', []):
                if block.get('type') == 'tool_use' and block.get('name') == 'generate_test_cases':
                    return block.get('input', {})

            # fallback: text 응답 (tool_use 미지원 시)
            for block in result.get('content', []):
                if block.get('type') == 'text':
                    text = block.get('text', '').strip()
                    if text.startswith('```'):
                        text = re.sub(r'^```\w*\n?', '', text)
                        text = re.sub(r'\n?```$', '', text)
                    return json.loads(text)

            return {}

        except json.JSONDecodeError as e:
            print(f"  WARN: response not valid JSON: {e}")
            if attempt < max_retries:
                continue
            return {}
        except Exception as e:
            err_str = str(e)
            if 'Throttling' in err_str or 'throttl' in err_str.lower():
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                print(f"  WARN: Bedrock throttled after {max_retries + 1} attempts")
            else:
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
        query_ids = [q['query_id'] for q in batch]
        raw = _call_bedrock(prompt, query_ids)

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
