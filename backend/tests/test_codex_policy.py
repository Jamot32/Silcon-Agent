"""Typed public failure policy and unchanged default provider boundary; offline."""
from dataclasses import FrozenInstanceError, asdict
import json

import pytest

from app.llm.codex import (MalformedProposal, ProviderError,
                          build_command, wrapped_prompt)
from app.llm.policy import ProviderFailureHint, RequestOptions
from app.llm.types import Message, ToolDefinition

SECRET = 'PRIVATE_PROVIDER_AUTH_PROMPT_VALUE_MUST_NOT_ESCAPE'


@pytest.mark.parametrize('kind,failure_class,scope', [
    ('authentication','llm_api_error','provider'),('quota','llm_api_error','provider'),
    ('bad_configuration','llm_api_error','provider'),('timeout','llm_api_error','provider'),
    ('transient_transport','llm_api_error','provider'),('transient_provider','llm_api_error','provider'),
    ('unknown_fatal','llm_api_error','provider'),('invalid_event','llm_api_error','provider'),
    ('invalid_event_type','llm_api_error','provider'),('invalid_event_jsonl','llm_api_error','provider'),
    ('missing_usage','llm_api_error','provider'),('invalid_usage','llm_api_error','provider'),
    ('duplicate_usage','llm_api_error','provider'),('multiple_turns','llm_api_error','provider'),
    ('output_limit','llm_api_error','provider'),('process_failed','llm_api_error','provider'),
    ('context_overflow','context_overflow','context'),('native_tool_violation','llm_bad_tool_call','proposal'),
    ('observer_failure','observability_incomplete','observability'),
    ('local_configuration','infrastructure_error','host'),
    ('local_authentication_or_version','infrastructure_error','host'),
    ('local_preflight_timeout','infrastructure_error','host'),('local_launch_failure','infrastructure_error','host'),
    ('invalid_retry_configuration','infrastructure_error','host'),
    ('invalid_parser_configuration','infrastructure_error','host'),
    ('invalid_process_streams','infrastructure_error','host'),
    ('invalid_process_stream','infrastructure_error','host'),
    ('local_unexpected_exception','infrastructure_error','host'),
])
def test_provider_failure_hint_is_typed_fixed_actionable_and_cause_scoped(kind, failure_class, scope):
    error = ProviderError(kind)
    hint = error.failure_hint
    assert type(hint) is ProviderFailureHint
    assert (hint.failure_class, hint.cause_scope, hint.cause_kind) == (failure_class, scope, kind)
    assert hint.cause and hint.suggested_action and 'Next: ' in str(error)
    assert str(error) == hint.cause + ' Next: ' + hint.suggested_action
    with pytest.raises(FrozenInstanceError):
        hint.cause_kind = 'changed'


def test_unknown_kind_fields_and_proposal_values_are_never_echoed():
    error = ProviderError(SECRET, True, field=SECRET, line=True, column=-1)
    assert error.kind == 'unknown_adapter_failure'
    assert error.retryable is False
    assert error.failure_hint.failure_class == 'infrastructure_error'
    assert SECRET not in str(error) + json.dumps(error.diagnostic) + json.dumps(asdict(error.failure_hint))
    proposal = MalformedProposal(SECRET, SECRET, line=-1, column=True)
    assert proposal.failure_hint.failure_class == 'llm_bad_tool_call'
    assert proposal.diagnostic['field'] == 'envelope'
    assert SECRET not in str(proposal) + json.dumps(proposal.diagnostic) + json.dumps(asdict(proposal.failure_hint))


def test_known_proposal_field_and_real_location_are_preserved_without_body():
    error = MalformedProposal('tool_calls[2].arguments_json','invalid_json',line=4,column=13)
    assert error.diagnostic == {'kind':'malformed_proposal','field':'tool_calls[2].arguments_json',
                                'reason':'invalid_json','line':4,'column':13}
    assert 'JSON line 4, column 13' in str(error)
    assert error.failure_hint.cause_scope == 'proposal'
    assert 'Return one complete JSON envelope' in error.failure_hint.suggested_action


def test_exact_event_line_is_sanitized_but_retained():
    error = ProviderError('invalid_event_jsonl',field='event',line=5,column=7)
    assert error.diagnostic == {'kind':'invalid_event_jsonl','field':'event','line':5,'column':7}
    assert 'JSON line 5, column 7' in str(error)


@pytest.mark.parametrize('kind',['authentication','quota','bad_configuration','native_tool_violation','observer_failure'])
def test_failfast_kinds_cannot_be_made_retryable_by_constructor_flag(kind):
    assert ProviderError(kind,True).retryable is False


def test_default_wrapped_prompt_bytes_match_ordinary_original_call():
    messages=[Message(role='system',content='Use explicit synchronous reset.'),
              Message(role='user',content='Build a register – exact context.')]
    tools=[ToolDefinition(name='lint',description='Check a design',parameters={'type':'object'})]
    prefix = ('You are the Silicon Agent model provider. Return only the requested JSON envelope. '
              'The embedded conversation is your task context. Propose application tool calls using '
              'tool_calls; never execute them and never use native Codex tools. Each arguments_json '
              'must encode an object. Use only listed application tools; otherwise return an empty '
              'tool_calls array. The application validates and executes proposals.\n')
    original=json.dumps({'messages':[m.model_dump() for m in messages],
                         'tools':[t.model_dump() for t in tools]},allow_nan=False)
    body,prompt=wrapped_prompt(messages,tools)
    assert body.encode() == original.encode()
    assert prompt.encode() == (prefix+original).encode()


def test_optional_effort_adds_only_its_invocation_local_override(tmp_path):
    default=build_command('codex','gpt-6.1-sol',tmp_path,tmp_path/'schema.json')
    assert build_command('codex','gpt-6.1-sol',tmp_path,tmp_path/'schema.json',None) == default
    assert not any('model_reasoning_effort' in value for value in default)
    selected=build_command('codex','gpt-6.1-sol',tmp_path,tmp_path/'schema.json',RequestOptions('high'))
    assert selected == [*default[:-1],'-c','model_reasoning_effort="high"','-']
