"""OpenAI tool-calling CLI. Set OPENAI_API_KEY to enable."""
import json
import logging
import os
import sys
import httpx
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('assistant')
BASE = os.getenv('API_URL', 'http://localhost:8000')

TOOLS = [
    {'type': 'function', 'function': {'name': 'query_shipments', 'description': 'Query curated shipments using optional filters',
     'parameters': {'type': 'object', 'properties': {'origin': {'type': 'string'}, 'destination': {'type': 'string'},
      'status': {'type': 'string'}, 'start_date': {'type': 'string'}, 'end_date': {'type': 'string'}}, 'additionalProperties': False}}},
    {'type': 'function', 'function': {'name': 'get_route_stats', 'description': 'Return aggregated route delay and on-time statistics',
     'parameters': {'type': 'object', 'properties': {'origin': {'type': 'string'}, 'destination': {'type': 'string'}},
      'required': ['origin', 'destination'], 'additionalProperties': False}}},
    {'type': 'function', 'function': {'name': 'predict_delay', 'description': 'Predict delay risk for a shipment ID',
     'parameters': {'type': 'object', 'properties': {'shipment_id': {'type': 'string'}},
      'required': ['shipment_id'], 'additionalProperties': False}}}
]


def invoke(name, args):
    with httpx.Client(timeout=15) as client:
        if name == 'query_shipments':
            r = client.get(f'{BASE}/shipments', params={**args, 'page_size': 100})
        elif name == 'get_route_stats':
            r = client.get(f"{BASE}/routes/{args['origin']}/{args['destination']}/stats")
        elif name == 'predict_delay':
            r = client.post(f'{BASE}/predict-delay', json=args)
        else:
            raise ValueError('Tool not allowed')
        r.raise_for_status()
        return r.json()


def ask(question):
    client = OpenAI()
    messages = [{'role': 'system', 'content': 'You answer only supply-chain questions using available tools. Cite tool names in factual answers. Do not invent data. If a tool cannot answer, say so.'},
                {'role': 'user', 'content': question}]
    for step in range(4):
        logger.info(json.dumps({'event': 'llm_request', 'messages': messages}, default=str))
        response = client.chat.completions.create(model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'), messages=messages, tools=TOOLS)
        msg = response.choices[0].message
        logger.info(json.dumps({'event': 'llm_response', 'content': msg.content, 'tools': [t.function.name for t in msg.tool_calls or []]}))
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return msg.content
        for tool in msg.tool_calls:
            try:
                result = invoke(tool.function.name, json.loads(tool.function.arguments))
            except Exception as exc:
                result = {'error': str(exc)}
            logger.info(json.dumps({'event': 'tool_response', 'tool': tool.function.name, 'response': result}, default=str))
            messages.append({'role': 'tool', 'tool_call_id': tool.id, 'content': json.dumps(result, default=str)})
    return 'Tool call limit reached; please ask a narrower question.'


if __name__ == '__main__':
    print(ask(' '.join(sys.argv[1:]) or input('Question: ')))
