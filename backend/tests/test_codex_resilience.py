"""Synthetic provider events and a harmless local cleanup control; no CLI/provider/EDA."""
import asyncio
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.llm.codex import (CodexCLIClient, ProviderError, MalformedProposal,
    build_command, check_event, classify_fatal, MAX_OUTPUT_BYTES, wrapped_prompt,parse_completion)
from app.llm.types import Budget, BudgetExceeded, Message, ToolDefinition
from app.llm.policy import RequestOptions, MAX_PROMPT_BYTES


SECRET = 'DO_NOT_LOG_PRIVATE_PROMPT_ERROR_AUTH_OR_MODEL_CODE'
MESSAGES = [Message(role='user', content=SECRET)]
TOOLS = [ToolDefinition(name='write_file', description='synthetic', parameters={'type':'object'})]


def events(text=None, calls=None):
    if text is None:
        text = json.dumps({'content':'ok', 'tool_calls':calls or []})
    return [{'type':'thread.started','thread_id':'synthetic'}, {'type':'turn.started'},
            {'type':'item.completed','item':{'id':'unit','type':'agent_message','text':text}},
            {'type':'turn.completed','usage':{'input_tokens':11,'cached_input_tokens':3,
                'cache_write_input_tokens':0,'output_tokens':7,'reasoning_output_tokens':2}}]


class Harness(CodexCLIClient):
    def __init__(self, outcomes, **kwargs):
        self.outcomes, self.requests, self.records, self.delays, self.preflights = list(outcomes), [], [], [], 0
        async def sleep(delay):
            self.delays.append(delay)
        kwargs.setdefault('model','gpt-6.1-sol')
        super().__init__(executable='SYNTHETIC_CODEX', callback=self.records.append,
            sleep=sleep, jitter=lambda:0, environment_factory=lambda:{}, **kwargs)

    async def _check_cli(self, env, executable):
        self.preflights += 1

    async def _request(self, args, prompt, env, incoming):
        self.requests.append((args, prompt))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        for event in outcome:
            incoming(event)


class ProviderTests(unittest.TestCase):
    def complete(self, client, options=None):
        return asyncio.run(client.complete(MESSAGES, TOOLS, options))

    def finished(self, client):
        return [r for r in client.records if r['event'] == 'attempt_finished']

    def test_plan_cost_unknown_at_initialization_and_first_failed_call(self):
        budget = Budget()
        self.assertEqual(budget.cost_usd, 0)
        client = Harness([ProviderError('unknown_fatal')], budget=budget)
        self.assertIsNone(budget.cost_usd)
        with self.assertRaises(ProviderError): self.complete(client)
        self.assertIsNone(budget.cost_usd)
        self.assertIsNone(self.finished(client)[0]['usage'])

    def test_strict_budget_limits_reject_nonfinite_bool_and_fractional_caps(self):
        for key in ('max_calls','max_tokens'):
            for value in (True,False,0,-1,1.0,1.5,float('inf'),float('nan'),'3'):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    Budget(**{key:value})
        for value in (True,False,-1,float('inf'),float('nan'),'2',None):
            with self.subTest(usd=value),self.assertRaises(ValueError):Budget(max_usd=value)
        self.assertEqual(Budget(max_usd=0,max_calls=1,max_tokens=1).max_tokens,1)
        self.assertIsNone(Budget(max_tokens=None).max_tokens)

    def test_unexpected_local_exception_is_sanitized_and_never_completed(self):
        client=Harness([RuntimeError(SECRET),events()])
        with self.assertRaises(ProviderError) as caught:self.complete(client)
        self.assertEqual(caught.exception.kind,'local_unexpected_exception')
        self.assertNotIn(SECRET,str(caught.exception))
        self.assertEqual(self.finished(client)[0]['kind'],'local_unexpected_exception')
        self.assertEqual(len(client.requests),1)

    def test_nonfatal_error_item_then_valid_response_uses_one_attempt(self):
        warning = {'type':'item.completed','item':{'id':'warn','type':'error','message':SECRET}}
        client = Harness([[warning, *events()]])
        result = self.complete(client)
        self.assertEqual((result.input_tokens, result.output_tokens), (11,7))
        self.assertEqual(client.budget.calls, 1)
        self.assertEqual([r['kind'] for r in client.records if r['event']=='provider_warning'], ['nonfatal_error_item'])
        self.assertEqual(self.finished(client)[0]['kind'], 'completed')
        self.assertNotIn(SECRET, json.dumps(client.records))

    def test_transient_top_error_retries_then_success_with_exponential_delay(self):
        client = Harness([[{'type':'error','message':'HTTP 503 temporarily unavailable '+SECRET}],
                          [{'type':'turn.failed','error':{'message':'connection reset '+SECRET}}], events()])
        self.complete(client)
        self.assertEqual((client.budget.calls, len(client.requests)), (3,3))
        self.assertEqual(client.delays, [0.5,1.0])
        self.assertEqual([r['kind'] for r in self.finished(client)], ['transient_transport','transient_transport','completed'])
        self.assertNotIn(SECRET, json.dumps(client.records))

    def test_timeouts_bounded_to_three_total_attempts_unknown_usage(self):
        client = Harness([TimeoutError(SECRET)]*3)
        with self.assertRaises(ProviderError) as caught: self.complete(client)
        self.assertEqual(caught.exception.kind, 'timeout')
        self.assertEqual((client.budget.calls, len(client.requests)), (3,3))
        self.assertEqual(client.delays, [0.5,1])
        self.assertTrue(all(r['usage'] is None for r in self.finished(client)))
        self.assertIsNone(client.budget.cost_usd)

    def test_auth_quota_config_and_unknown_fatal_failfast(self):
        for text, kind in [('authentication failed','authentication'),('usage limit reached','quota'),
                           ('unknown model','bad_configuration'),('unclassified failure','unknown_fatal')]:
            client = Harness([[{'type':'error','message':text+' '+SECRET}],events()])
            with self.subTest(kind=kind), self.assertRaises(ProviderError) as caught: self.complete(client)
            self.assertEqual(caught.exception.kind, kind)
            self.assertEqual((len(client.requests),client.budget.calls), (1,1))
            self.assertEqual(client.delays, [])
            self.assertNotIn(SECRET, str(caught.exception))

    def test_quota_takes_precedence_over_transient_http_message(self):
        error = classify_fatal('HTTP 429 quota exceeded '+SECRET)
        self.assertEqual((error.kind,error.retryable), ('quota',False))
        self.assertNotIn(SECRET,str(error))

    def test_native_tool_event_never_retries_even_with_transient_message(self):
        for name in ('command_execution','file_change','mcp_tool_call','collab_tool_call','web_search','todo_list'):
            client = Harness([[{'type':'item.started','item':{'id':'x','type':name,'message':'HTTP 503'}}],events()])
            with self.subTest(name=name), self.assertRaises(ProviderError) as caught: self.complete(client)
            self.assertEqual(caught.exception.kind,'native_tool_violation')
            self.assertEqual(len(client.requests),1)

    def test_usage_callback_precedes_budget_guard_and_triggering_usage_retained(self):
        client = Harness([events()], budget=Budget(max_tokens=10))
        seen = []
        def callback(record):
            client.records.append(record)
            if record['event']=='usage': seen.append((client.budget.input_tokens,record['usage']))
        client.callback = callback
        with self.assertRaises(BudgetExceeded): self.complete(client)
        self.assertEqual(seen[0][0],0)
        self.assertEqual(seen[0][1]['cached_input_tokens'],3)
        self.assertEqual((client.budget.input_tokens,client.budget.output_tokens),(11,7))
        self.assertEqual(self.finished(client)[0]['kind'],'budget_exceeded')
        self.assertEqual(len(client.requests),1)

    def test_usage_is_recorded_even_if_usage_observer_raises(self):
        client = Harness([events()])
        def callback(record):
            if record['event']=='usage': raise RuntimeError(SECRET)
            client.records.append(record)
        client.callback=callback
        with self.assertRaises(ProviderError) as caught: self.complete(client)
        self.assertEqual(caught.exception.kind,'observer_failure')
        self.assertEqual(client.budget.total_tokens,18)
        self.assertEqual(len(client.requests),1)

    def test_budget_attempt_cap_prevents_second_send(self):
        client = Harness([TimeoutError(),events()], budget=Budget(max_calls=1))
        with self.assertRaises(BudgetExceeded): self.complete(client)
        self.assertEqual((len(client.requests),client.budget.calls),(1,1))

    def test_malformed_proposals_have_two_corrections_max_and_no_raw_feedback(self):
        bad = json.dumps({'content':'x','tool_calls':[{'id':'a','name':'write_file','arguments_json':'{\n"private":}'}]})
        client = Harness([events(bad)]*3)
        with self.assertRaises(MalformedProposal) as caught: self.complete(client)
        detail = caught.exception.diagnostic
        self.assertEqual((detail['field'],detail['line']),('tool_calls[0].arguments_json',2))
        self.assertGreater(detail['column'],0)
        self.assertEqual((client.budget.calls,client.budget.total_tokens),(3,54))
        self.assertEqual(client.delays,[])
        self.assertEqual(len(MESSAGES),1)
        self.assertNotIn('"private":}',client.requests[-1][1])
        self.assertNotIn('"private":}',str(caught.exception))

    def test_transients_and_corrections_share_three_attempt_ceiling(self):
        client = Harness([TimeoutError(),events('{invalid'),events()])
        self.complete(client)
        self.assertEqual(len(client.requests),3)
        self.assertEqual(client.budget.calls,3)
        self.assertEqual(client.budget.total_tokens,36)

    def test_returned_model_code_is_only_opaque_proposal_data(self):
        source='raise RuntimeError("'+SECRET+'")'
        calls=[{'id':'a','name':'write_file','arguments_json':json.dumps({'path':'src/a.v','content':source})}]
        client=Harness([events(calls=calls)])
        result=self.complete(client)
        self.assertEqual(result.tool_calls[0].arguments['content'],source)
        self.assertNotIn(source,json.dumps(client.records))

    def test_unknown_tool_feedback_names_field_without_echoing_unknown_value(self):
        bad=json.dumps({'content':'','tool_calls':[{'id':'a','name':SECRET,'arguments_json':'{}'}]})
        client=Harness([events(bad)]*3)
        with self.assertRaises(MalformedProposal) as caught:self.complete(client)
        self.assertEqual(caught.exception.diagnostic['field'],'tool_calls[0].name')
        self.assertNotIn(SECRET,str(caught.exception))

    def test_invalid_surrogate_proposal_is_sanitized_and_bounded(self):
        bad=json.dumps({'content':'','tool_calls':[{'id':'\ud800','name':'write_file','arguments_json':'{}'}]})
        client=Harness([events(bad)]*3)
        with self.assertRaises(MalformedProposal) as caught:self.complete(client)
        self.assertEqual(caught.exception.diagnostic['reason'],'invalid_json_values')
        self.assertEqual(len(client.requests),3)

    def test_missing_duplicate_invalid_usage_are_fatal_not_proposal_corrections(self):
        for case,kind in [(events()[:-1],'missing_usage'),([*events(),events()[-1]],'duplicate_usage'),
                          ([{'type':'turn.completed','usage':{'input_tokens':True}}],'invalid_usage')]:
            client=Harness([case,events()])
            with self.subTest(kind=kind),self.assertRaises(ProviderError) as caught:self.complete(client)
            self.assertEqual(caught.exception.kind,kind)
            self.assertEqual(len(client.requests),1)

    def test_cancellation_during_request_or_backoff_never_retries(self):
        client=Harness([asyncio.CancelledError(),events()])
        with self.assertRaises(asyncio.CancelledError):self.complete(client)
        self.assertEqual((len(client.requests),client.delays),(1,[]))
        client=Harness([TimeoutError(),events()])
        async def cancel(delay):raise asyncio.CancelledError()
        client.sleep=cancel
        with self.assertRaises(asyncio.CancelledError):self.complete(client)
        self.assertEqual(len(client.requests),1)

    def test_finished_observer_failure_does_not_replace_cancellation(self):
        client=Harness([asyncio.CancelledError(),events()])
        def callback(record):
            if record['event']=='attempt_finished':raise RuntimeError(SECRET)
            client.records.append(record)
        client.callback=callback
        with self.assertRaises(asyncio.CancelledError) as caught:self.complete(client)
        self.assertEqual((len(client.requests),client.budget.calls),(1,1))
        self.assertTrue(client.observer_failed)
        self.assertEqual(client.observer_failure_count,1)
        self.assertEqual(caught.exception.__notes__,['observer_failure during attempt_finished'])
        self.assertNotIn(SECRET,str(caught.exception)+repr(caught.exception.__notes__))

    def test_finished_observer_failure_does_not_replace_budget_trigger_or_usage(self):
        client=Harness([events()],budget=Budget(max_tokens=10))
        def callback(record):
            if record['event']=='attempt_finished':raise RuntimeError(SECRET)
            client.records.append(record)
        client.callback=callback
        with self.assertRaises(BudgetExceeded) as caught:self.complete(client)
        self.assertEqual((client.budget.total_tokens,len(client.requests)),(18,1))
        self.assertIsNone(client.budget.cost_usd)
        self.assertTrue(client.observer_failed)
        self.assertEqual(caught.exception.__notes__,['observer_failure during attempt_finished'])
        self.assertEqual([r['usage']['input_tokens'] for r in client.records if r['event']=='usage'],[11])

    def test_finished_observer_failure_preserves_terminal_provider_cause(self):
        client=Harness([ProviderError('native_tool_violation'),events()])
        def callback(record):
            if record['event']=='attempt_finished':raise RuntimeError(SECRET)
        client.callback=callback
        with self.assertRaises(ProviderError) as caught:self.complete(client)
        self.assertEqual(caught.exception.kind,'native_tool_violation')
        self.assertTrue(client.observer_failed)
        self.assertEqual(len(client.requests),1)

    def test_finished_observer_failure_after_success_is_not_silently_accepted(self):
        client=Harness([events()])
        def callback(record):
            if record['event']=='attempt_finished':raise RuntimeError(SECRET)
        client.callback=callback
        with self.assertRaises(ProviderError) as caught:self.complete(client)
        self.assertEqual(caught.exception.kind,'observer_failure')
        self.assertEqual(client.budget.total_tokens,18)
        self.assertTrue(client.observer_failed)

    def test_caller_handled_exception_does_not_hide_success_observer_failure(self):
        client=Harness([events()])
        def callback(record):
            if record['event']=='attempt_finished':raise RuntimeError(SECRET)
        client.callback=callback
        try:
            raise ValueError('unrelated caller context')
        except ValueError:
            with self.assertRaises(ProviderError) as caught:self.complete(client)
        self.assertEqual(caught.exception.kind,'observer_failure')

    def test_executable_and_timeout_are_captured_before_preflight_await(self):
        client=Harness([events()],timeout=1)
        captured=[]
        async def check(env,executable):
            captured.append(executable)
            client.executable='MUTATED_WHILE_PENDING'
            client.timeout=True
            await asyncio.sleep(0)
        client._check_cli=check
        self.complete(client)
        self.assertEqual(captured,['SYNTHETIC_CODEX'])
        self.assertEqual(client.requests[0][0][0],'SYNTHETIC_CODEX')

    def test_timeout_requires_finite_positive_exact_numeric_value(self):
        for timeout in (True,False,0,-1,float('nan'),float('inf'),'1',None):
            with self.subTest(timeout=timeout),self.assertRaises(ValueError):
                Harness([events()],timeout=timeout)
        client=Harness([events()]);client.timeout=True
        with self.assertRaises(ValueError):self.complete(client)
        self.assertEqual((client.preflights,client.budget.calls,len(client.requests)),(0,0,0))

    def test_options_immutable_and_parallel_calls_keep_distinct_invocation_overrides(self):
        class Parallel(Harness):
            async def _request(self,args,prompt,env,incoming):
                self.requests.append((args,prompt))
                await asyncio.sleep(0)
                for event in events():incoming(event)
        client=Parallel([])
        low,high=RequestOptions('low'),RequestOptions('high')
        with self.assertRaises(FrozenInstanceError):low.reasoning_effort='max'
        async def exercise():await asyncio.gather(client.complete(MESSAGES,TOOLS,low),client.complete(MESSAGES,TOOLS,high))
        asyncio.run(exercise())
        overrides=[a[a.index('model_reasoning_effort="low"')] if 'model_reasoning_effort="low"' in a else a[a.index('model_reasoning_effort="high"')] for a,_ in client.requests]
        self.assertEqual(set(overrides),{'model_reasoning_effort="low"','model_reasoning_effort="high"'})
        self.assertEqual(client.model,'gpt-6.1-sol')
        self.assertEqual(client.budget.calls,2)
        self.assertFalse(any('temperature' in arg for a,_ in client.requests for arg in a))

    def test_minimal_effort_rejected_before_preflight_or_budget_reserve(self):
        client=Harness([events()])
        with self.assertRaises(ValueError):self.complete(client,RequestOptions('minimal'))
        self.assertEqual((client.preflights,client.budget.calls,len(client.requests)),(0,0,0))

    def test_jitter_bounded_and_invalid_configuration_not_sent(self):
        client=Harness([TimeoutError(),events()]);client.jitter=lambda:.25
        self.complete(client)
        self.assertEqual(client.delays,[.75])
        client=Harness([TimeoutError(),events()]);client.jitter=lambda:float('nan')
        with self.assertRaises(ProviderError):self.complete(client)
        self.assertEqual(len(client.requests),1)

    def test_security_command_defaults_and_effort_are_invocation_local(self):
        args=build_command('codex','gpt-6.1-sol',Path('/tmp/work'),Path('/tmp/schema'))
        self.assertIn('--ignore-user-config',args);self.assertIn('--ephemeral',args)
        self.assertEqual(args[args.index('--sandbox')+1],'read-only')
        self.assertIn('approval_policy="never"',args)
        self.assertIn('forced_login_method="chatgpt"',args)
        self.assertIn('web_search="disabled"',args)
        self.assertNotIn('model_reasoning_effort="medium"',args)
        self.assertEqual(args[-1],'-')

    def test_exact_native_wrapper_prompt_byte_boundary_includes_schema_and_wrapper(self):
        empty=[Message(role='user',content='')]
        _,prompt=wrapped_prompt(empty,TOOLS)
        overhead=len(prompt.encode())
        for excess in (0,1):
            messages=[Message(role='user',content='x'*(MAX_PROMPT_BYTES-overhead+excess))]
            client=Harness([events()])
            if excess:
                with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(messages,TOOLS))
                self.assertEqual(caught.exception.kind,'context_overflow')
                self.assertEqual((client.budget.calls,client.preflights,len(client.requests)),(0,0,0))
            else:
                asyncio.run(client.complete(messages,TOOLS))
                self.assertEqual(len(client.requests[0][1].encode()),MAX_PROMPT_BYTES)

    def test_local_authentication_failure_stops_before_reserve_and_cost_stays_unknown(self):
        client=Harness([events()])
        async def check(env, executable):raise ProviderError('local_authentication_or_version')
        client._check_cli=check
        with self.assertRaises(ProviderError):self.complete(client)
        self.assertEqual((client.budget.calls,len(client.requests)),(0,0))
        self.assertIsNone(client.budget.cost_usd)

    def test_unadvertised_error_status_fields_do_not_make_unknown_message_transient(self):
        with self.assertRaises(ProviderError) as caught:
            check_event({'type':'error','message':'unclassified '+SECRET,'status':503,'code':'rate_limit'})
        self.assertEqual((caught.exception.kind,caught.exception.retryable),('unknown_fatal',False))
        self.assertNotIn(SECRET,str(caught.exception))

    def test_completed_usage_before_later_fatal_is_not_discarded(self):
        client=Harness([[*events(),{'type':'error','message':'authentication failed'}]])
        with self.assertRaises(ProviderError):self.complete(client)
        self.assertEqual((client.budget.calls,client.budget.total_tokens),(1,18))
        self.assertEqual(self.finished(client)[0]['usage']['input_tokens'],11)


class CompatibilityParserTests(unittest.TestCase):
    """Actual retained public fixture parsing only, no actual model invocation."""
    def real_events(self):
        path=Path(__file__).parent/'fixtures/codex_smoke/events.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()]

    def parse(self,rows,*,budget=None,callback=None):
        tool=ToolDefinition(name='add',description='Add two integers',parameters={'type':'object'})
        return parse_completion(rows,model='gpt-6.1-sol',tools=[tool],latency_ms=1,
            budget=budget if budget is not None else Budget(),usage_callback=callback)

    def test_actual_public_smoke_fixture_keeps_entry_and_exact_usage(self):
        budget=Budget();result=self.parse(self.real_events(),budget=budget)
        self.assertEqual((result.input_tokens,result.cached_input_tokens,result.output_tokens),(8493,0,41))
        self.assertEqual((result.tool_calls[0].name,result.tool_calls[0].arguments),('add',{'a':2,'b':3}))
        self.assertEqual((budget.total_tokens,budget.calls),(8534,0))
        self.assertIsNone(budget.cost_usd)

    def test_callback_precedes_record_and_budget_trigger_retains_actual_tokens(self):
        budget=Budget(max_tokens=10);seen=[]
        def callback(usage):seen.append((budget.total_tokens,dict(usage)))
        with self.assertRaises(BudgetExceeded):self.parse(self.real_events(),budget=budget,callback=callback)
        self.assertEqual(seen[0][0],0)
        self.assertEqual(seen[0][1]['input_tokens'],8493)
        self.assertEqual(budget.total_tokens,8534)

    def test_callback_error_still_records_and_budget_error_remains_primary(self):
        def callback(usage):raise RuntimeError(SECRET)
        for cap,expected in ((10000,ProviderError),(10,BudgetExceeded)):
            budget=Budget(max_tokens=cap)
            with self.subTest(cap=cap),self.assertRaises(expected) as caught:
                self.parse(self.real_events(),budget=budget,callback=callback)
            self.assertEqual(budget.total_tokens,8534)
            self.assertNotIn(SECRET,str(caught.exception))
            if cap==10000:self.assertEqual(caught.exception.kind,'observer_failure')

    def test_shared_proposal_diagnostic_and_accounting_on_bad_public_fixture_copy(self):
        rows=self.real_events();message=next(r['item'] for r in rows if r.get('type')=='item.completed' and r['item'].get('type')=='agent_message')
        envelope=json.loads(message['text']);envelope['tool_calls'][0]['name']=SECRET
        message['text']=json.dumps(envelope);budget=Budget()
        with self.assertRaises(MalformedProposal) as caught:self.parse(rows,budget=budget)
        self.assertEqual(caught.exception.diagnostic['field'],'tool_calls[0].name')
        self.assertEqual(budget.total_tokens,8534)
        self.assertNotIn(SECRET,str(caught.exception))

    def test_warning_then_fixture_valid_but_later_fatal_retains_earlier_usage(self):
        warning={'type':'item.completed','item':{'type':'error','message':SECRET}}
        self.assertEqual(self.parse([warning,*self.real_events()]).output_tokens,41)
        budget=Budget()
        with self.assertRaises(ProviderError) as caught:self.parse([*self.real_events(),{'type':'error','message':'authentication failed'}],budget=budget)
        self.assertEqual(caught.exception.kind,'authentication')
        self.assertEqual(budget.total_tokens,8534)

    def test_multiple_turns_duplicate_usage_and_native_events_never_succeed(self):
        rows=self.real_events()
        completed=next(r for r in rows if r['type']=='turn.completed')
        for sequence,kind,tokens in (([{'type':'turn.started'},{'type':'turn.started'},*rows],'multiple_turns',0),
            ([*rows,completed],'duplicate_usage',8534),([*rows,{'type':'turn.started'}],'multiple_turns',8534),
            ([{'type':'item.started','item':{'type':'command_execution'}},*rows],'native_tool_violation',0)):
            budget=Budget()
            with self.subTest(kind=kind),self.assertRaises(ProviderError) as caught:self.parse(sequence,budget=budget)
            self.assertEqual(caught.exception.kind,kind)
            self.assertEqual(budget.total_tokens,tokens)


class FakeInput:
    def __init__(self):self.data=[]
    def write(self,raw):self.data.append(raw)
    async def drain(self):pass
    def close(self):pass


class FakeReader:
    def __init__(self,lines=(),block=False):self.lines=list(lines);self.block=block;self.started=asyncio.Event()
    async def readline(self):
        self.started.set()
        if self.lines:return self.lines.pop(0)
        if self.block:await asyncio.Event().wait()
        return b''
    async def read(self,size):return b''


class FakeProcess:
    def __init__(self,lines=(),block=False,rc=0):
        self.stdin,self.stdout,self.stderr=FakeInput(),FakeReader(lines,block),FakeReader()
        self.returncode=None;self.final_rc=rc;self.pid=440001;self.killed=False
    async def wait(self):
        if self.returncode is None:self.returncode=self.final_rc
        return self.returncode
    def kill(self):self.killed=True;self.returncode=-9


class ProcessTests(unittest.TestCase):
    def run_client(self,process,*,timeout=1):
        client=CodexCLIClient(executable='SYNTHETIC',timeout=timeout,environment_factory=lambda:{})
        async def check(env, executable):pass
        async def spawn(*args,**kwargs):return process
        client._check_cli=check
        def killpg(pid,sig):process.kill()
        return client,spawn,killpg

    def test_real_stream_parser_with_fake_process_accepts_warning_and_keeps_stderr_private(self):
        rows=[{'type':'item.completed','item':{'id':'w','type':'error','message':SECRET}},*events()]
        process=FakeProcess([json.dumps(e).encode()+b'\n' for e in rows])
        client,spawn,killpg=self.run_client(process)
        records=[];client.callback=records.append
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
            result=asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(result.input_tokens,11)
        self.assertNotIn(SECRET,json.dumps(records))

    def test_fake_jsonl_line_failure_reports_only_line_column_field(self):
        process=FakeProcess([b'{bad\n'])
        client,spawn,killpg=self.run_client(process)
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
            with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(caught.exception.diagnostic,{'kind':'invalid_event_jsonl','field':'event','line':1,'column':2})
        self.assertTrue(process.killed)

    def test_malformed_event_type_is_sanitized_and_reported_as_failure(self):
        for event in ({'type':[]},{'type':{}},{'type':None},
                      {'type':'item.completed','item':{'type':[]}},
                      {'type':'item.started','item':{'type':{'private':SECRET}}}):
            process=FakeProcess([json.dumps(event).encode()+b'\n'])
            client,spawn,killpg=self.run_client(process)
            records=[];client.callback=records.append
            with self.subTest(event=event),patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
                with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
            self.assertEqual(caught.exception.kind,'invalid_event_type')
            self.assertEqual([r['kind'] for r in records if r['event']=='attempt_finished'],['invalid_event_type'])
            self.assertNotIn(SECRET,str(caught.exception)+json.dumps(records))
            self.assertTrue(process.killed)
            self.assertEqual(client.budget.calls,1)

    def test_process_timeout_cleanup_and_budget_retry_cap_use_no_real_process(self):
        processes=[]
        client=CodexCLIClient(executable='SYNTHETIC',timeout=.001,environment_factory=lambda:{},
            sleep=lambda delay:asyncio.sleep(0),jitter=lambda:0)
        async def check(env, executable):pass
        client._check_cli=check
        async def spawn(*args,**kwargs):
            p=FakeProcess(block=True);processes.append(p);return p
        def killpg(pid,sig):processes[-1].kill()
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
            with self.assertRaises(ProviderError):asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(len(processes),3)
        self.assertTrue(all(p.killed for p in processes))
        self.assertEqual(client.budget.calls,3)

    def test_process_cancellation_cleans_child_without_retry(self):
        process=FakeProcess(block=True)
        client,spawn,killpg=self.run_client(process)
        async def exercise():
            task=asyncio.create_task(client.complete(MESSAGES,TOOLS))
            await process.stdout.started.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
            asyncio.run(exercise())
        self.assertTrue(process.killed)
        self.assertEqual(client.budget.calls,1)

    def test_exited_parent_native_guard_still_cleans_group_and_keeps_usage(self):
        native={'type':'item.started','item':{'type':'command_execution'}}
        process=FakeProcess([json.dumps(e).encode()+b'\n' for e in [*events(),native]])
        process.returncode=0
        client,spawn,_=self.run_client(process)
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg') as killpg:
            with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(caught.exception.kind,'native_tool_violation')
        killpg.assert_called_once_with(process.pid,signal.SIGKILL)
        self.assertEqual((client.budget.calls,client.budget.total_tokens),(1,18))
        self.assertIsNone(client.budget.cost_usd)

    def test_exited_parent_timeout_cleans_each_group_before_retry(self):
        processes=[]
        client=CodexCLIClient(executable='SYNTHETIC',timeout=.001,environment_factory=lambda:{},
            sleep=lambda delay:asyncio.sleep(0),jitter=lambda:0)
        async def check(env,executable):pass
        async def spawn(*args,**kwargs):
            self.assertTrue(all(p.killed for p in processes))
            p=FakeProcess(block=True);p.returncode=0;processes.append(p);return p
        def killpg(pid,sig):processes[-1].killed=True
        client._check_cli=check
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
            with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(caught.exception.kind,'timeout')
        self.assertEqual((len(processes),client.budget.calls),(3,3))
        self.assertTrue(all(p.killed for p in processes))

    def test_exited_parent_cancellation_still_cleans_owned_group(self):
        process=FakeProcess(block=True);process.returncode=0
        client,spawn,_=self.run_client(process)
        async def exercise():
            task=asyncio.create_task(client.complete(MESSAGES,TOOLS))
            await process.stdout.started.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg') as killpg:
            asyncio.run(exercise())
        killpg.assert_called_once_with(process.pid,signal.SIGKILL)
        self.assertEqual(client.budget.calls,1)

    def test_failed_teardown_keeps_primary_guard_budget_and_cancellation(self):
        native={'type':'item.started','item':{'type':'command_execution'}}
        for kind in ('guard','budget','cancel'):
            rows=[native] if kind=='guard' else events() if kind=='budget' else []
            process=FakeProcess([json.dumps(e).encode()+b'\n' for e in rows],block=kind=='cancel');process.returncode=0
            client,spawn,_=self.run_client(process)
            if kind=='budget':client.budget=Budget(max_tokens=10);client.budget.mark_unknown_cost()
            caught_error=[]
            async def exercise():
                task=asyncio.create_task(client.complete(MESSAGES,TOOLS))
                if kind=='cancel':await process.stdout.started.wait();task.cancel()
                try:await task
                except BaseException as error:caught_error.append(error)
            with self.subTest(kind=kind),patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',side_effect=OSError(SECRET)):
                asyncio.run(exercise())
            self.assertEqual(len(caught_error),1);error=caught_error[0]
            if kind=='guard':self.assertIsInstance(error,ProviderError);self.assertEqual(error.kind,'native_tool_violation')
            elif kind=='budget':self.assertIsInstance(error,BudgetExceeded);self.assertEqual(client.budget.total_tokens,18)
            else:self.assertIsInstance(error,asyncio.CancelledError)
            self.assertEqual(error.__notes__,['Codex process-group cleanup incomplete.'])
            self.assertNotIn(SECRET,str(error)+repr(error.__notes__))
            self.assertEqual(client.budget.calls,1)

    def test_failed_teardown_blocks_timeout_and_transient_retries(self):
        for kind in ('timeout','transient'):
            rows=[] if kind=='timeout' else [{'type':'error','message':'HTTP 503'}]
            process=FakeProcess([json.dumps(e).encode()+b'\n' for e in rows],block=kind=='timeout');process.returncode=0
            client,spawn,_=self.run_client(process,timeout=.001)
            client.sleep=lambda delay:asyncio.sleep(0)
            with self.subTest(kind=kind),patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',side_effect=OSError(SECRET)):
                with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
            self.assertEqual(caught.exception.kind,'timeout' if kind=='timeout' else 'transient_provider')
            self.assertFalse(caught.exception.retryable)
            self.assertEqual(client.budget.calls,1)
            self.assertNotIn(SECRET,str(caught.exception)+repr(caught.exception.__notes__))

    @unittest.skipUnless(os.name=='posix','Owned process-group control requires POSIX')
    def test_harmless_local_descendant_holding_pipes_is_stopped_after_parent_exit(self):
        # Local stdlib Python only. The parent exits; its child emits one fixed
        # forbidden event and keeps both inherited pipes open until teardown.
        child="import json,time\ntime.sleep(0.2)\nprint(json.dumps({'type':'item.started','item':{'type':'command_execution'}}),flush=True)\ntime.sleep(30)\n"
        parent="import subprocess,sys\nsubprocess.Popen([sys.executable,'-u','-c',"+repr(child)+"])\n"
        original_spawn=asyncio.create_subprocess_exec
        processes=[];parent_codes=[]
        async def spawn(*args,**kwargs):
            process=await original_spawn(*args,**kwargs);processes.append(process);return process
        def incoming(event):parent_codes.append(processes[0].returncode);check_event(event)
        async def exercise():
            client=CodexCLIClient(executable='SYNTHETIC',environment_factory=lambda:{})
            try:
                with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn):
                    with self.assertRaises(ProviderError) as caught:
                        await asyncio.wait_for(client._request([sys.executable,'-u','-c',parent],'{}',{},incoming),5)
                self.assertEqual(caught.exception.kind,'native_tool_violation')
                self.assertEqual(parent_codes,[0])
                self.assertEqual(await asyncio.wait_for(processes[0].stdout.read(),1),b'')
                self.assertEqual(await asyncio.wait_for(processes[0].stderr.read(),1),b'')
            finally:
                # Fault-safe cleanup also runs if this regression ever returns.
                for process in processes:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    await process.wait()
        asyncio.run(exercise())

    def test_output_limit_fails_fast_and_local_spawn_error_is_not_retried(self):
        process=FakeProcess([b'x'*(MAX_OUTPUT_BYTES+1)])
        client,spawn,killpg=self.run_client(process)
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
            with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(caught.exception.kind,'output_limit')
        async def failed(*args,**kwargs):raise OSError(SECRET)
        with patch('app.llm.codex.asyncio.create_subprocess_exec',failed):
            with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(caught.exception.kind,'local_launch_failure')
        self.assertNotIn(SECRET,str(caught.exception))

    def test_missing_process_streams_are_cleaned_and_nonzero_exit_retains_usage(self):
        process=FakeProcess();process.stdin=None
        client,spawn,killpg=self.run_client(process)
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
            with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(caught.exception.kind,'invalid_process_streams')
        self.assertTrue(process.killed)
        process=FakeProcess([json.dumps(e).encode()+b'\n' for e in events()],rc=1)
        client,spawn,killpg=self.run_client(process)
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',killpg):
            with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(caught.exception.kind,'process_failed')
        self.assertEqual(client.budget.total_tokens,18)

    def test_preflight_auth_and_cancellation_with_fake_process_only(self):
        class Local(FakeProcess):
            def __init__(self,output,block=False):
                super().__init__();self.output=output;self.block=block;self.entered=asyncio.Event()
            async def communicate(self):
                self.entered.set()
                if self.block:await asyncio.Event().wait()
                self.returncode=0
                return self.output,b''
        client=CodexCLIClient(executable='SYNTHETIC',environment_factory=lambda:{})
        processes=[Local(b'codex-cli 0.163.0'),Local(SECRET.encode())]
        async def spawn(*args,**kwargs):return processes.pop(0)
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn):
            with self.assertRaises(ProviderError) as caught:asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertEqual(caught.exception.kind,'local_authentication_or_version')
        self.assertEqual(client.budget.calls,0)
        self.assertNotIn(SECRET,str(caught.exception))
        process=Local(b'',block=True)
        async def blocked(*args,**kwargs):return process
        async def cancel():
            task=asyncio.create_task(client.complete(MESSAGES,TOOLS))
            await process.entered.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        with patch('app.llm.codex.asyncio.create_subprocess_exec',blocked),patch('app.llm.codex.os.killpg',lambda pid,sig:process.kill()):asyncio.run(cancel())
        self.assertTrue(process.killed)
        self.assertEqual(client.budget.calls,0)

    def test_preflight_exited_parent_timeout_and_cancel_clean_owned_group(self):
        class Local(FakeProcess):
            def __init__(self):super().__init__();self.returncode=0;self.entered=asyncio.Event()
            async def communicate(self):self.entered.set();await asyncio.Event().wait()
        for kind in ('timeout','cancel'):
            process=Local();client=CodexCLIClient(executable='SYNTHETIC',environment_factory=lambda:{})
            original_wait_for=asyncio.wait_for
            async def bounded(awaitable,timeout):return await original_wait_for(awaitable,.001)
            async def spawn(*args,**kwargs):
                self.assertTrue(kwargs['start_new_session']);return process
            caught=[]
            async def exercise():
                task=asyncio.create_task(client._check_cli({},'SYNTHETIC'))
                if kind=='cancel':await process.entered.wait();task.cancel()
                try:await task
                except BaseException as error:caught.append(error)
            with self.subTest(kind=kind),patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.asyncio.wait_for',bounded),patch('app.llm.codex.os.killpg') as killpg:
                asyncio.run(exercise())
            self.assertEqual(len(caught),1)
            if kind=='timeout':self.assertIsInstance(caught[0],ProviderError);self.assertEqual(caught[0].kind,'local_preflight_timeout')
            else:self.assertIsInstance(caught[0],asyncio.CancelledError)
            killpg.assert_called_once_with(process.pid,signal.SIGKILL)
            self.assertEqual(client.budget.calls,0)

    def test_preflight_cleanup_failure_preserves_cancellation_without_private_text(self):
        class Local(FakeProcess):
            def __init__(self):super().__init__();self.returncode=0;self.entered=asyncio.Event()
            async def communicate(self):self.entered.set();await asyncio.Event().wait()
        process=Local();client=CodexCLIClient(executable='SYNTHETIC',environment_factory=lambda:{})
        async def spawn(*args,**kwargs):return process
        async def exercise():
            task=asyncio.create_task(client._check_cli({},'SYNTHETIC'))
            await process.entered.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError) as caught:await task
            self.assertEqual(caught.exception.__notes__,['Codex process-group cleanup incomplete.'])
            self.assertNotIn(SECRET,str(caught.exception)+repr(caught.exception.__notes__))
        with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn),patch('app.llm.codex.os.killpg',side_effect=OSError(SECRET)):
            asyncio.run(exercise())
        self.assertEqual(client.budget.calls,0)

    @unittest.skipUnless(os.name=='posix','Owned process-group control requires POSIX')
    def test_harmless_local_preflight_descendant_holding_pipes_is_stopped(self):
        # Intercept the synthetic version argv with local stdlib Python; no
        # Codex executable, authentication, model or network is involved.
        parent="import subprocess,sys\nsubprocess.Popen([sys.executable,'-u','-c','import time; time.sleep(30)'])\n"
        original_spawn=asyncio.create_subprocess_exec
        processes=[]
        async def spawn(*args,**kwargs):
            self.assertEqual(args,('SYNTHETIC','--version'));self.assertTrue(kwargs['start_new_session'])
            process=await original_spawn(sys.executable,'-u','-c',parent,**kwargs);processes.append(process);return process
        async def exercise():
            client=CodexCLIClient(executable='SYNTHETIC',environment_factory=lambda:{})
            task=None
            try:
                with patch('app.llm.codex.asyncio.create_subprocess_exec',spawn):
                    task=asyncio.create_task(client._check_cli({},'SYNTHETIC'))
                    for _ in range(1000):
                        if processes and processes[0].returncode==0:break
                        await asyncio.sleep(.001)
                    self.assertTrue(processes);self.assertEqual(processes[0].returncode,0)
                    self.assertFalse(task.done());task.cancel()
                    with self.assertRaises(asyncio.CancelledError):await task
                self.assertEqual(await asyncio.wait_for(processes[0].stdout.read(),1),b'')
                self.assertEqual(await asyncio.wait_for(processes[0].stderr.read(),1),b'')
                self.assertEqual(client.budget.calls,0)
            finally:
                if task is not None and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
                for process in processes:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    await process.wait()
        asyncio.run(exercise())




class IntegratedLiveGuardTests(unittest.TestCase):
    """Exercise live incoming callbacks, with no provider/process launched."""

    def test_live_multiple_turn_guard_matches_captured_event_reducer(self):
        for stream in ([{'type':'turn.started'},{'type':'turn.started'},*events()],
                       [*events(),{'type':'turn.started'}]):
            client=Harness([stream,events()])
            with self.subTest(stream=stream),self.assertRaises(ProviderError) as caught:
                asyncio.run(client.complete(MESSAGES,TOOLS))
            self.assertEqual(caught.exception.kind,'multiple_turns')
            self.assertEqual(len(client.requests),1)

    def test_timeout_does_not_expose_raw_exception_chain(self):
        client=Harness([TimeoutError(SECRET)]*3)
        with self.assertRaises(ProviderError) as caught:
            asyncio.run(client.complete(MESSAGES,TOOLS))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertNotIn(SECRET,str(caught.exception))


if __name__ == '__main__':
    unittest.main()
