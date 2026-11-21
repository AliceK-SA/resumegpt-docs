#!/usr/bin/env python3
"""Project-level checks beyond OpenAPI/AsyncAPI schemas. Does not replace official validators."""
from __future__ import annotations
import sys
from pathlib import Path
import yaml
from jsonschema import Draft7Validator, FormatChecker
from jsonschema.validators import RefResolver

ROOT=Path(__file__).resolve().parent.parent
errors=[]
METHODS={'get','post','put','patch','delete'}
for f in sorted((ROOT/'docs/api/openapi').glob('*.yaml')):
    doc=yaml.safe_load(f.read_text(encoding='utf-8'))
    for path,methods in doc.get('paths',{}).items():
        for meth,op in methods.items():
            if meth not in METHODS:continue
            label=f'{f.name} {meth.upper()} {path}'
            if 'security' not in op:errors.append(f'{label}: security must be explicitly defined (or [])')
            if op.get('security') and '401' not in op.get('responses',{}):errors.append(f'{label}: missing 401 response')
            if meth in {'post','patch','put','delete'} and 'responses' not in op:errors.append(f'{label}: no response documentation')
            if path=='/analyses' and meth=='post' and '429' not in op.get('responses',{}):errors.append(f'{label}: gateway rate-limit 429 required')
    if f.name=='billing-service.yaml':
        op=doc['paths']['/credits/history']['get']
        if not {'page','size'}.issubset({p.get('name') for p in op.get('parameters',[])}):errors.append(f'{f.name}: history pagination missing')
        props=op['responses']['200']['content']['application/json']['schema'].get('properties',{})
        if not {'items','page','size','total'}.issubset(props):errors.append(f'{f.name}: history pagination response fields missing')
    if f.name=='analysis-service.yaml':
        if 'leaseToken' not in doc['components']['schemas']['LeaseGrant']['required']:errors.append('analysis-service: fencing token missing from LeaseGrant')
        if '/internal/analyses/{analysisId}/lease/renew' not in doc['paths']:errors.append('analysis-service: missing lease renew endpoint')
    if f.name=='payment-service.yaml':
        desc=doc['paths']['/payments']['post'].get('description','')
        if 'Idempotence-Key' not in desc:errors.append('payment-service: payment recovery not documented')
        if '24 час' not in doc.get('info', {}).get('description', ''):
            errors.append('payment-service: 24-hour provider idempotence limit must be documented')

f=ROOT/'docs/api/asyncapi/events.yaml'; doc=yaml.safe_load(f.read_text(encoding='utf-8'))
for name,ch in doc['channels'].items():
    bindings=ch.get('bindings',{})
    if '$ref' not in bindings or 'amqp' in bindings:errors.append(f'AsyncAPI channel {name}: reference must be on whole bindings object')
for name,component in doc['components']['channelBindings'].items():
    if 'amqp' not in component:errors.append(f'AsyncAPI channel binding {name}: missing amqp wrapper')
for name in ('AnalysisCompleted','AnalysisFailed'):
    fields=doc['components']['messages'][name]['payload']['allOf'][1]['properties']['data']
    if 'leaseToken' not in fields['required']:errors.append(f'AsyncAPI {name}: missing leaseToken')
# Cross-contract consistency: JSON types of common result fields must match.
# OpenAPI has an additional `model` field; AsyncAPI carries the model in the outer event.
analysis=yaml.safe_load((ROOT/'docs/api/openapi/analysis-service.yaml').read_text(encoding='utf-8'))
http_result=analysis['components']['schemas']['AnalysisResult']
event_result=doc['components']['schemas']['AnalysisResult']
def core_schema(node):
    if isinstance(node, dict):
        return {k:core_schema(v) for k,v in node.items() if k not in ('description','example','examples')}
    if isinstance(node, list):return [core_schema(x) for x in node]
    return node
for name, prop in event_result.get('properties', {}).items():
    other=http_result.get('properties', {}).get(name)
    if other is None or core_schema(other)!=core_schema(prop):
        errors.append(f'AnalysisResult field {name}: AsyncAPI and OpenAPI differ')
for name in event_result.get('required', []):
    if name not in http_result.get('required', []):
        errors.append(f'AnalysisResult required field {name}: missing from OpenAPI')

# An example in a contract is also part of the contract: check against payload schema.
# The official CLI is still required to validate AsyncAPI itself.
resolver=RefResolver.from_schema(doc)
for message_name, message in doc['components']['messages'].items():
    if not isinstance(message, dict) or 'payload' not in message:
        continue
    validator=Draft7Validator(message['payload'], resolver=resolver, format_checker=FormatChecker())
    for example in message.get('examples', []):
        for err in validator.iter_errors(example.get('payload')):
            loc='.'.join(str(p) for p in err.absolute_path) or '$'
            errors.append(f'AsyncAPI {message_name} example {example.get("name", "unnamed")} {loc}: {err.message}')

for err in errors:print('ERROR:',err)
print(f'Custom contract checks: {len(errors)} problem(s)')
sys.exit(bool(errors))
