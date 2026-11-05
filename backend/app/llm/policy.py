"""Explicit host per-call options and sanitized provider failure policy."""
from dataclasses import dataclass
from typing import Literal
import json
import re

MODEL = 'gpt-6.1-sol'
META_MODEL = 'muse-spark-1.3'
CODEX_EFFORTS = frozenset({'low','medium','high','xhigh','max'})
META_EFFORTS = frozenset({'minimal','low','medium','high','xhigh'})
MAX_PROMPT_BYTES = 90000


@dataclass(frozen=True)
class RequestOptions:
    reasoning_effort: str
    diversity_label: str | None = None

    def __post_init__(self):
        if type(self.reasoning_effort) is not str or self.reasoning_effort not in CODEX_EFFORTS | META_EFFORTS:
            raise ValueError('Unrecognized host effort')
        if self.diversity_label is not None and (type(self.diversity_label) is not str
             or not re.fullmatch(r'candidate_[1-3]',self.diversity_label)):
            raise ValueError('Diversity label must be a host candidate identifier')


def codex_override(options: RequestOptions, *, selected_model: str):
    if type(options) is not RequestOptions or selected_model != MODEL:
        raise ValueError('Capability profile is pinned only to the selected model')
    if options.reasoning_effort not in CODEX_EFFORTS:
        raise ValueError('The selected Codex model does not advertise this effort')
    # An invocation-only TOML scalar; no user/global mutable configuration.
    return ('-c','model_reasoning_effort='+json.dumps(options.reasoning_effort))


@dataclass(frozen=True)
class ProviderFailureHint:
    """Host exception metadata; model/tool-result dictionaries cannot attest it."""

    failure_class: Literal['llm_bad_tool_call','context_overflow','llm_api_error','infrastructure_error','observability_incomplete']
    cause_scope: Literal['proposal','context','provider','host','observability']
    cause_kind: str
    cause: str
    suggested_action: str


# Fixed host-authored text. Never interpolate provider stderr/messages or values.
_FAILURE_POLICY = {
    'local_configuration': ('infrastructure_error','host','Local Codex CLI is unavailable.',
        'Configure the pinned CLI 0.163.0 executable and retry.'),
    'boundary_policy': ('infrastructure_error','host','The Codex read-boundary policy is missing, stale or could not be admitted.',
        'Rerun scripts/setup_codex_boundary.py for the current worktree and set SILICON_CODEX_BOUNDARY_CONFIG to the generated policy.'),
    'local_authentication_or_version': ('infrastructure_error','host','Local Codex authentication or version check did not match.',
        'Verify CLI 0.163.0 and run codex login before retrying.'),
    'local_preflight_timeout': ('infrastructure_error','host','Local Codex version/login check timed out before a model request.',
        'Check the local CLI and retry.'),
    'local_launch_failure': ('infrastructure_error','host','The host could not start the local Codex process.',
        'Check the configured executable and host runtime.'),
    'authentication': ('llm_api_error','provider','Codex reported an authentication failure.',
        'Run codex login and retry.'),
    'quota': ('llm_api_error','provider','Codex reported a usage limit.',
        'Wait for the plan limit to reset or explicitly select another configured provider.'),
    'bad_configuration': ('llm_api_error','provider','Codex rejected configured request options.',
        'Check the selected model and effort against the pinned client profile.'),
    'timeout': ('llm_api_error','provider','A Codex CLI invocation timed out.',
        'Automatic retries are bounded; preserve partial work and retry later.'),
    'transient_transport': ('llm_api_error','provider','The Codex response stream was interrupted.',
        'Automatic retries are bounded; retry later.'),
    'transient_stream': ('llm_api_error','provider','The Codex response stream was interrupted.',
        'Automatic retries are bounded; retry later.'),
    'transient_provider': ('llm_api_error','provider','Codex reported a transient request failure.',
        'Automatic retries are bounded; retry later.'),
    'unknown_fatal': ('llm_api_error','provider','Codex reported an unclassified fatal failure; the adapter stopped without guessing a retry category.',
        'Inspect the sanitized recorded kind before retrying.'),
    'context_overflow': ('context_overflow','context','The wrapped request exceeds the configured 90,000 UTF-8-byte cap, including messages, tool schemas and provider wrapper.',
        'Send bounded context before retrying.'),
    'native_tool_violation': ('llm_bad_tool_call','proposal','The Codex native-event guard rejected an unexpected tool event; no application tool proposal from this response was dispatched.',
        'Check the pinned native-tool guards before requesting another proposal.'),
    'output_limit': ('llm_api_error','provider',"The Codex event stream exceeded the adapter's bounded output limit.",
        'Send smaller context and inspect the pinned adapter.'),
    'process_failed': ('llm_api_error','provider','The local Codex process exited unsuccessfully; the cause is not established.',
        'Retain any validated usage and inspect sanitized host diagnostics.'),
    'observer_failure': ('observability_incomplete','observability','Host observability is incomplete.',
        'Inspect retained artifacts and repair the evidence/trace path before relying on a complete run record.'),
    'invalid_retry_configuration': ('infrastructure_error','host','The host retry configuration is invalid.',
        'Correct its bounded backoff/jitter settings before retrying.'),
    'invalid_parser_configuration': ('infrastructure_error','host','The host event-parser configuration is invalid.',
        'Correct the parser inputs or callback configuration.'),
    'local_unexpected_exception': ('infrastructure_error','host','The host provider adapter failed unexpectedly.',
        'Inspect the sanitized local failure kind and pinned runtime before retrying.'),
    'unknown_adapter_failure': ('infrastructure_error','host','The host provider adapter reported an unsupported failure kind.',
        'Inspect the pinned adapter and its sanitized failure policy before retrying.'),
}
for _kind in ('invalid_event','invalid_event_type','invalid_error_event','invalid_event_jsonl'):
    _FAILURE_POLICY[_kind] = ('llm_api_error','provider','The Codex event stream did not match the pinned protocol.',
        'Retain the sanitized event field/line/column and check CLI 0.163.0 compatibility.')
for _kind in ('missing_usage','invalid_usage','duplicate_usage','multiple_turns'):
    _FAILURE_POLICY[_kind] = ('llm_api_error','provider','Codex did not return one valid measurable turn; unknown usage remains unknown.',
        'Check pinned CLI compatibility before retrying.')
for _kind in ('invalid_process_streams','invalid_process_stream'):
    _FAILURE_POLICY[_kind] = ('infrastructure_error','host','The local Codex process streams did not match the expected interface.',
        'Check the pinned CLI and host adapter.')
del _kind


def provider_failure_hint(kind: str) -> ProviderFailureHint:
    safe_kind = kind if type(kind) is str and kind in _FAILURE_POLICY else 'unknown_adapter_failure'
    failure_class, scope, cause, action = _FAILURE_POLICY[safe_kind]
    return ProviderFailureHint(failure_class,scope,safe_kind,cause,action)
