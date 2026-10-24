"""Pure synthetic controls only: no model requests or EDA tools."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4

from app.observability.observer import RequestMetadata, RunObserver
from app.observability.snapshot import LedgerSnapshots
from app.observability.trace import TraceWriter, canonical, prompt_hash
from app.agent.ledger import Artifact, ExecutionReceipt
from app.observability.integration import Integration


SOURCE, INPUTS, OTHER_INPUTS = "1" * 64, "2" * 64, "3" * 64
CONFIG = "4" * 64
IMAGE = "sha256:" + "5" * 64
RUN = "a" * 32
SECRET = "DO_NOT_RECORD_PROMPT_CODE_AUTH_ENV_OR_ERROR_BODY"


class BudgetStop(RuntimeError):
    pass


class MemoryWriter:
    def __init__(self):
        self.records = []

    def append(self, kind, stage, payload):
        self.records.append({"type": kind, "stage": stage, "payload": json.loads(canonical(payload))})

    def close(self):
        pass


def budget():
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": None}


def report(observer, *, model="selected", identity="reported", cost=None):
    observer.reported_usage(model=model, model_identity=identity, input_tokens=11,
                            cached_input_tokens=3, output_tokens=7, cost_usd=cost, latency_ms=14)


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.writer = MemoryWriter()
        self.observer = RunObserver(Path("unused"), RUN, writer=self.writer, budget_exceptions=(BudgetStop,))
        self.request = RequestMetadata("meta", "selected", CONFIG, "medium", "requested")

    def payloads(self, phase):
        return [r["payload"] for r in self.writer.records if r["payload"].get("phase") == phase]

    def inference(self, counters, request=None):
        return self.observer.inference([{"role": "user", "content": SECRET}], [], request or self.request,
                                       budget_snapshot=lambda: dict(counters))

    def test_success_records_actual_usage_hash_and_explicit_effort_without_content(self):
        counters = budget()
        self.observer.transition("SPEC")
        with self.inference(counters):
            counters["calls"] += 1
            with self.observer.provider_attempt():
                report(self.observer, model="reported-serving-model")
                counters.update(input_tokens=11, output_tokens=7)
        completed = [p for p in self.payloads("finished") if "prompt_sha256" in p][0]
        self.assertEqual(completed["usage"], {"input_tokens": 11, "cached_input_tokens": 3,
                                             "output_tokens": 7, "cost_usd": None})
        self.assertEqual(completed["recorded_budget_delta"]["calls"], 1)
        self.assertEqual(completed["prompt_sha256"], prompt_hash([{"role": "user", "content": SECRET}], []))
        self.assertEqual((completed["requested_effort"], completed["effort_status"]), ("medium", "requested"))
        self.assertEqual(completed["config_revision"], CONFIG)
        self.assertNotIn(SECRET, json.dumps(self.writer.records))

    def test_budget_triggering_response_keeps_tokens_before_exception(self):
        counters = budget()
        with self.assertRaises(BudgetStop):
            with self.inference(counters):
                counters["calls"] += 1
                with self.observer.provider_attempt():
                    report(self.observer)
                    counters.update(input_tokens=11, output_tokens=7)
                    raise BudgetStop(SECRET)
        completed = [p for p in self.payloads("finished") if "prompt_sha256" in p][0]
        self.assertEqual(completed["status"], "budget_exceeded")
        self.assertEqual(completed["usage"]["cached_input_tokens"], 3)
        self.assertEqual(completed["recorded_budget_delta"]["output_tokens"], 7)
        self.assertNotIn(SECRET, json.dumps(self.writer.records))

    def test_failed_request_usage_stays_unknown_even_when_reserved_counter_changes(self):
        counters = budget()
        with self.assertRaises(TimeoutError):
            with self.inference(counters):
                counters["calls"] += 1
                with self.observer.provider_attempt():
                    raise TimeoutError(SECRET)
        completed = [p for p in self.payloads("finished") if "prompt_sha256" in p][0]
        self.assertIsNone(completed["usage"])
        self.assertEqual(completed["usage_scope"], "unknown")
        self.assertEqual(completed["attempts_without_reported_usage"], 1)
        self.assertEqual(completed["exception_type"], "TimeoutError")
        self.assertEqual(completed["recorded_budget_delta"]["calls"], 1)

    def test_pre_send_budget_stop_does_not_invent_an_attempt_or_zero_token_usage(self):
        counters = budget()
        with self.assertRaises(BudgetStop):
            with self.inference(counters):
                raise BudgetStop(SECRET)
        completed = [p for p in self.payloads("finished") if "prompt_sha256" in p][0]
        self.assertEqual(completed["observed_provider_attempts"], 0)
        self.assertIsNone(completed["usage"])
        self.assertEqual(completed["status"], "budget_exceeded")

    def test_retry_failure_and_measured_response_have_distinct_attempts(self):
        counters = budget()
        with self.inference(counters):
            for failed in (True, False):
                counters["calls"] += 1
                try:
                    with self.observer.provider_attempt():
                        if failed:
                            raise TimeoutError(SECRET)
                        report(self.observer)
                        counters.update(input_tokens=11, output_tokens=7)
                except TimeoutError:
                    pass
        completed = [p for p in self.payloads("finished") if "prompt_sha256" in p][0]
        self.assertEqual(completed["observed_provider_attempts"], 2)
        self.assertEqual(completed["attempts_without_reported_usage"], 1)
        self.assertEqual(completed["usage_scope"], "reported_responses")
        attempts = self.payloads("attempt_finished")
        self.assertIsNone(attempts[0]["usage"])
        self.assertEqual(attempts[1]["usage"]["input_tokens"], 11)

    def test_codex_selection_does_not_claim_serving_model_or_unsent_effort(self):
        counters = budget()
        request = RequestMetadata("codex", "gpt-selected", CONFIG)
        with self.inference(counters, request):
            counters["calls"] = 1
            with self.observer.provider_attempt():
                report(self.observer, model="gpt-selected", identity="selection")
                counters.update(input_tokens=11, output_tokens=7)
        completed = [p for p in self.payloads("finished") if "prompt_sha256" in p][0]
        self.assertIsNone(completed["serving_model"])
        self.assertIsNone(completed["requested_effort"])
        self.assertEqual(completed["effort_status"], "unknown")
        self.assertEqual(self.payloads("attempt_finished")[0]["usage"]["model_identity"], "selection")

    def test_budget_window_delta_never_fabricates_per_call_usage(self):
        counters = budget()
        with self.assertRaises(BudgetStop):
            with self.inference(counters):
                counters.update(calls=1, input_tokens=19, output_tokens=4)
                raise BudgetStop(SECRET)
        completed = [p for p in self.payloads("finished") if "prompt_sha256" in p][0]
        self.assertEqual(completed["usage_scope"], "unknown")
        self.assertIsNone(completed["usage"])
        self.assertEqual(completed["recorded_budget_delta"]["input_tokens"],19)
        self.assertEqual(completed["recorded_budget_delta_scope"],"accounting_window_nonadditive")

    def test_async_inferences_use_distinct_host_contexts(self):
        async def exercise():
            ready = asyncio.Event()
            entered = 0
            async def call():
                nonlocal entered
                counters = budget()
                with self.inference(counters):
                    entered += 1
                    if entered == 2:
                        ready.set()
                    await ready.wait()
                    counters["calls"] = 1
                    with self.observer.provider_attempt():
                        report(self.observer)
                        await asyncio.sleep(0)
                        counters.update(input_tokens=11, output_tokens=7)
            await asyncio.gather(call(), call())
        asyncio.run(exercise())
        completed = [p for p in self.payloads("finished") if "prompt_sha256" in p]
        self.assertEqual(len({p["call_id"] for p in completed}), 2)
        self.assertEqual([p["observed_provider_attempts"] for p in completed], [1, 1])

    def test_shared_budget_overlapping_calls_never_attribute_double_window_usage(self):
        async def exercise(*,reported_hooks):
            entered,recorded=asyncio.Event(),asyncio.Event()
            arrivals,completed=0,0
            observer=self.observer
            class Fake:
                def __init__(self):self.budget=SimpleNamespace(calls=0,input_tokens=0,output_tokens=0,cost_usd=None)
                async def complete(self,messages,tools):
                    nonlocal arrivals,completed
                    arrivals+=1;self.budget.calls+=1
                    if arrivals==2:entered.set()
                    await entered.wait()
                    def account():
                        nonlocal completed
                        if reported_hooks:report(observer)
                        self.budget.input_tokens+=11;self.budget.output_tokens+=7;completed+=1
                        if completed==2:recorded.set()
                    if reported_hooks:
                        with observer.provider_attempt():
                            account();await recorded.wait()
                    else:
                        account();await recorded.wait()
                    return 'synthetic response'
            client=Fake();integration=Integration(observer)
            await asyncio.gather(*(integration.ask(client,[],[],self.request) for _ in range(2)))
            return client.budget
        for reported_hooks in (False,True):
            with self.subTest(reported_hooks=reported_hooks):
                self.writer.records.clear()
                actual=asyncio.run(exercise(reported_hooks=reported_hooks))
                rows=[p for p in self.payloads('finished') if 'prompt_sha256' in p]
                self.assertEqual((actual.input_tokens,actual.output_tokens),(22,14))
                self.assertEqual([p['recorded_budget_delta']['input_tokens'] for p in rows],[22,22])
                self.assertTrue(all(p['recorded_budget_delta_scope']=='accounting_window_nonadditive' for p in rows))
                if reported_hooks:
                    self.assertEqual(sum(p['usage']['input_tokens'] for p in rows),22)
                    self.assertEqual([p['usage_scope'] for p in rows],['reported_responses']*2)
                else:
                    self.assertTrue(all(p['usage'] is None and p['usage_scope']=='unknown' for p in rows))

    def test_all_state_transitions_and_one_terminal_outcome(self):
        for stage in ("SPEC", "RTL", "VERIFY", "RTL", "VERIFY", "FAIL"):
            self.observer.transition(stage, previous_ok=False)
        self.assertTrue(self.observer.finish_run("failed", failure_class="tool_failure", error=RuntimeError(SECRET)))
        self.assertFalse(self.observer.finish_run("failed"))
        states = [r for r in self.writer.records if r["type"] == "state_transition"]
        self.assertEqual(len(states), 6)
        self.assertEqual(states[0]["payload"]["from"], "BOOT")
        self.assertEqual(sum(r["type"] == "run_finished" for r in self.writer.records), 1)
        self.assertNotIn(SECRET, json.dumps(self.writer.records))

    def test_multi_command_tool_evidence_retains_actual_fields_without_argv_or_output(self):
        execution = "c" * 32
        def command(kind, rc):
            return {"command": ["python3", "/opt/silicon-agent/runtime.py", kind, SECRET],
                    "command_sha256": "b" * 64, "returncode": rc, "timed_out": False,
                    "process_launched": True, "duration_seconds": 0.125}
        wrapped = {"error": SECRET, "tool_evidence": {
            "execution_id": execution, "event": "executed_tool", "executed": True, "outcome": "failed",
            "observed_command_count": 2,
            "result": {"path": f".evidence/tools/{execution}/result.json", "sha256": "d" * 64},
            "receipt": {"path": f".evidence/tools/{execution}/receipt.json", "sha256": "e" * 64},
            "commands": [command("synth", 0), command("flow", 1)]}}
        with self.observer.tool("run_flow", SECRET, {"content": SECRET}):
            for observed in wrapped["tool_evidence"]["commands"]:
                self.observer.command_observed(**{k: observed[k] for k in
                    ("command", "returncode", "timed_out", "process_launched", "duration_seconds")})
            self.observer.evidence_finished(wrapped)
        commands = [r["payload"] for r in self.writer.records if r["type"] == "command_finished"]
        self.assertEqual([c["returncode"] for c in commands], [0, 1])
        self.assertEqual([c["command_class"] for c in commands], ["generic_synthesis", "physical_flow"])
        self.assertTrue(all(c["duration_seconds"] == 0.125 for c in commands))
        self.assertNotIn(SECRET, json.dumps(self.writer.records))

    def test_command_trace_survives_later_receipt_save_failure(self):
        with self.assertRaises(OSError):
            with self.observer.tool("run_flow", "id", {}):
                self.observer.command_observed(command=["python3", "-m", "librelane"],
                    returncode=1, timed_out=False, process_launched=True, duration_seconds=0.25)
                raise OSError(SECRET)  # Synthetic later host receipt write failure.
        commands = [r["payload"] for r in self.writer.records if r["type"] == "command_finished"]
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["command_class"], "mapped_synthesis")
        self.assertEqual(commands[0]["returncode"], 1)

    def test_failed_launch_trace_retains_real_attempt_fields(self):
        with self.observer.tool("lint", "id", {}):
            self.observer.command_observed(command=["python3", "/opt/silicon-agent/runtime.py", "lint"],
                returncode=127, timed_out=False, process_launched=False, duration_seconds=0.01)
        commands = [r["payload"] for r in self.writer.records if r["type"] == "command_finished"]
        self.assertFalse(commands[0]["process_launched"])
        self.assertEqual(commands[0]["returncode"], 127)

    def test_orphan_usage_and_command_callbacks_are_rejected(self):
        with self.assertRaises(ValueError):
            report(self.observer)
        with self.assertRaises(ValueError):
            self.observer.evidence_finished({})
        with self.assertRaises(ValueError):
            RequestMetadata("codex", "selected", CONFIG, "high", "unknown")

    def test_finalizer_append_fault_never_replaces_actual_body_exception(self):
        for scope in ('inference','attempt','tool'):
            for error_class in (asyncio.CancelledError,BudgetStop,RuntimeError):
                with self.subTest(scope=scope,primary=error_class.__name__):
                    writer=MemoryWriter();append=writer.append
                    def fault(kind,stage,payload):
                        if payload.get('phase')==('attempt_finished' if scope=='attempt' else 'finished'):
                            raise OSError(SECRET)
                        return append(kind,stage,payload)
                    writer.append=fault
                    observer=RunObserver(Path('unused'),RUN,writer=writer,budget_exceptions=(BudgetStop,))
                    primary=error_class('actual body failure')
                    with self.assertRaises(error_class) as caught:
                        if scope=='tool':
                            with observer.tool('run_flow','id',{}):raise primary
                        else:
                            with observer.inference([],[],self.request,budget_snapshot=budget):
                                if scope=='attempt':
                                    with observer.provider_attempt():raise primary
                                raise primary
                    self.assertIs(caught.exception,primary)
                    self.assertIsNotNone(observer.failure)
                    self.assertTrue(any('observability finalization failed' in note for note in primary.__notes__))
                    self.assertNotIn(SECRET,repr(primary.__notes__))
                    self.assertIsNone(observer._llm.get())
                    self.assertIsNone(observer._attempt.get())
                    self.assertIsNone(observer._tool.get())
                    if scope=='attempt' and error_class is BudgetStop:
                        finished=next(r['payload'] for r in writer.records if r['payload'].get('phase')=='finished')
                        self.assertEqual(finished['status'],'budget_exceeded')

    def test_snapshot_delta_and_clock_finalizer_faults_are_all_sticky(self):
        for fault in ('snapshot','delta','clock'):
            with self.subTest(fault=fault):
                reads=0
                def snapshot():
                    nonlocal reads
                    reads+=1
                    if fault=='snapshot' and reads==2:raise ValueError(SECRET)
                    return {**budget(),'input_tokens':5 if fault=='delta' and reads==1 else 0}
                clock=iter((1.0,float('nan'))).__next__ if fault=='clock' else self.observer.clock
                observer=RunObserver(Path('unused'),RUN,writer=MemoryWriter(),clock=clock,budget_exceptions=(BudgetStop,))
                primary=BudgetStop('actual budget stop')
                with self.assertRaises(BudgetStop) as caught:
                    with observer.inference([],[],self.request,budget_snapshot=snapshot):raise primary
                self.assertIs(caught.exception,primary)
                self.assertEqual(observer.failure['phase'],'inference_finished')
                # Use a valid clock for terminal reporting after the fault probe.
                observer.clock=self.observer.clock
                terminal=Integration(observer).finish_worker('done')
                self.assertEqual(terminal['failure_class'],'observability_incomplete')
                self.assertFalse(terminal['observability_complete'])

    def test_observer_fault_after_success_still_raises_and_is_not_hidden_by_caller_except(self):
        writer=MemoryWriter()
        def append(kind,stage,payload):
            if payload.get('phase')=='finished':raise OSError(SECRET)
        writer.append=append
        observer=RunObserver(Path('unused'),RUN,writer=writer)
        try:raise RuntimeError('unrelated handled caller error')
        except RuntimeError:
            with self.assertRaises(OSError):
                with observer.tool('lint','id',{}):pass
        self.assertIsNotNone(observer.failure)


class TraceDurabilityTests(unittest.TestCase):
    def test_private_new_file_and_fsync_failure_poison_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = TraceWriter(root, RUN)
            writer.append("state_transition", "SPEC", {"from": "BOOT", "to": "SPEC"})
            self.assertEqual(stat.S_IMODE((root / "trace.jsonl").stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                TraceWriter(root, RUN)
            with patch("app.observability.trace.os.fsync", side_effect=OSError("synthetic disk failure")):
                with self.assertRaises(OSError):
                    writer.append("run_finished", "FAIL", {"status": "failed"})
            with self.assertRaises(ValueError):
                writer.append("run_finished", "FAIL", {"status": "failed"})
            writer.close()

    def test_symlink_and_oversized_records_do_not_replace_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "outside"
            target.write_text("sentinel")
            (root / "trace.jsonl").symlink_to(target)
            with self.assertRaises(OSError):
                TraceWriter(root, RUN)
            self.assertEqual(target.read_text(), "sentinel")
            (root / "trace.jsonl").unlink()
            with TraceWriter(root, RUN) as writer:
                with self.assertRaises(ValueError):
                    writer.append("tool_call", "RTL", {"bad": "x" * 20000})
                writer.append("run_finished", "FAIL", {"status": "failed"})
            rows = [json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()]
            self.assertEqual([r["sequence"] for r in rows], [1])

    def test_partial_write_and_failed_close_poison_before_cleanup(self):
        import trace
        with tempfile.TemporaryDirectory() as directory:
            writer=TraceWriter(Path(directory),RUN);descriptor=writer._fd
            write,close=trace.os.write,trace.os.close
            def partial(fd,raw):write(fd,raw[:5]);return 5
            try:
                with patch('app.observability.trace.os.write',partial),patch('app.observability.trace.os.close',side_effect=OSError('secondary cleanup')):
                    with self.assertRaisesRegex(OSError,'Incomplete trace write') as caught:
                        writer.append('state_transition','SPEC',{'from':'BOOT','to':'SPEC'})
                self.assertIsNone(writer._fd)
                self.assertEqual(caught.exception.__notes__,['Trace cleanup also failed after uncertain write'])
                with self.assertRaisesRegex(ValueError,'closed'):
                    writer.append('run_finished','FAIL',{'status':'failed'})
                self.assertEqual(len((Path(directory)/'trace.jsonl').read_bytes()),5)
            finally:close(descriptor)  # Fake close did not close this test-owned fd.

    def test_context_exit_close_fault_preserves_primary_and_poisons_writer(self):
        import trace
        with tempfile.TemporaryDirectory() as directory:
            writer=TraceWriter(Path(directory),RUN);descriptor=writer._fd;close=trace.os.close
            primary=asyncio.CancelledError('actual cancellation')
            try:
                with patch('app.observability.trace.os.close',side_effect=OSError(SECRET)):
                    with self.assertRaises(asyncio.CancelledError) as caught:
                        with writer:raise primary
                self.assertIs(caught.exception,primary)
                self.assertIsNone(writer._fd)
                self.assertNotIn(SECRET,repr(primary.__notes__))
                with self.assertRaisesRegex(ValueError,'closed'):writer.append('run_finished','FAIL',{})
            finally:close(descriptor)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.writer = MemoryWriter()
        self.observer = RunObserver(Path("unused"), RUN, writer=self.writer, budget_exceptions=(BudgetStop,))
        self.integration = Integration(self.observer)

    def test_ask_and_child_tool_dispatch_use_real_callback_seams_with_synthetic_objects(self):
        observer = self.observer
        class FakeLLM:
            budget = SimpleNamespace(calls=0, input_tokens=0, output_tokens=0, cost_usd=None)
            async def complete(self, messages, tools):
                self.budget.calls += 1
                with observer.provider_attempt():
                    report(observer)
                    self.budget.input_tokens += 11
                    self.budget.output_tokens += 7
                return "opaque synthetic response"
        async def exercise():
            result = await self.integration.ask(FakeLLM(), [{"content": SECRET}], [],
                RequestMetadata("fake", "selected", CONFIG))
            async def dispatch():
                await asyncio.sleep(0)
                observer.command_observed(command=["synthetic"], returncode=2, timed_out=False,
                    process_launched=True, duration_seconds=0.25)
                return {"ok": False}
            call = SimpleNamespace(name="lint", id="arbitrary-provider-id", arguments={"content": SECRET})
            tool = await self.integration.tool(call, lambda: asyncio.wait_for(dispatch(), 1))
            return result, tool
        result, tool = asyncio.run(exercise())
        self.assertEqual(result, "opaque synthetic response")
        self.assertFalse(tool["ok"])
        self.assertEqual(sum(r["type"] == "command_finished" for r in self.writer.records), 1)
        self.assertNotIn(SECRET, json.dumps(self.writer.records))

    def test_swallowed_evidence_callback_error_is_sticky_before_terminal_claim(self):
        class Evidence:
            callback = None
            def observe(self, observation):
                pass
        class Snapshots:
            def record(self, wrapped, **view):
                raise OSError(SECRET)
        evidence = Evidence()
        sandbox = SimpleNamespace(completion_callback=evidence.observe)
        self.integration.bind(sandbox, evidence, Snapshots(), view=lambda wrapped: {})
        execution = "b" * 32
        wrapped = {"tool_evidence": {"execution_id": execution, "event": "no_execution", "executed": False,
            "observed_command_count": 0, "result": {"path": f".evidence/tools/{execution}/result.json", "sha256": "c" * 64}}}
        with self.observer.tool("write_file", "id", {}):
            # Match existing ToolEvidence: callback exceptions do not escape.
            try:
                evidence.callback(wrapped)
            except OSError:
                pass
        result = self.integration.finish_worker("done", store_confirmed=False)
        self.assertEqual(result, {"status": "failed", "failure_class": "observability_incomplete",
                                  "observability_complete": False})
        terminal = self.writer.records[-1]["payload"]
        self.assertEqual(terminal["outcome_authority"], "worker_local")
        self.assertNotIn(SECRET, json.dumps(self.writer.records))

    def test_bind_preserves_command_observation_even_when_receipt_is_not_saved(self):
        observed = []
        evidence = SimpleNamespace(callback=None, observe=observed.append)
        sandbox = SimpleNamespace(completion_callback=None)
        self.integration.bind(sandbox, evidence, SimpleNamespace(), view=lambda wrapped: {})
        command = SimpleNamespace(command=("python3", "/opt/silicon-agent/runtime.py", "lint"),
            result=SimpleNamespace(returncode=127, timed_out=False), process_launched=False, duration_seconds=0.1)
        with self.observer.tool("lint", "id", {}):
            sandbox.completion_callback(command)
        self.assertEqual(observed, [command])
        record = next(r for r in self.writer.records if r["type"] == "command_finished")
        self.assertFalse(record["payload"]["process_launched"])
        self.assertEqual(record["payload"]["returncode"], 127)

    def test_bind_refuses_silent_replacement_of_existing_callback(self):
        evidence = SimpleNamespace(callback=None, observe=lambda observation: None)
        sandbox = SimpleNamespace(completion_callback=lambda observation: None)
        with self.assertRaisesRegex(ValueError, "ownership"):
            self.integration.bind(sandbox, evidence, SimpleNamespace(), view=lambda wrapped: {})

    def test_evidence_observer_exception_is_sticky_even_if_caller_swallows_it(self):
        def fail(observation):
            raise OSError(SECRET)
        evidence = SimpleNamespace(callback=None, observe=fail)
        sandbox = SimpleNamespace(completion_callback=None)
        self.integration.bind(sandbox, evidence, SimpleNamespace(), view=lambda wrapped: {})
        try:
            sandbox.completion_callback(SimpleNamespace())
        except OSError:
            pass
        self.assertFalse(self.integration.finish_worker("done")["observability_complete"])

    def test_async_boundary_preserves_actual_cancel_budget_and_tool_errors(self):
        for scope,error in (('ask',asyncio.CancelledError()),('ask',BudgetStop('actual budget')),
                            ('tool',RuntimeError('actual tool error'))):
            with self.subTest(scope=scope,error=type(error).__name__):
                writer=MemoryWriter()
                def append(kind,stage,payload):
                    if payload.get('phase')=='finished':raise OSError(SECRET)
                writer.append=append
                observer=RunObserver(Path('unused'),RUN,writer=writer,budget_exceptions=(BudgetStop,))
                integration=Integration(observer)
                async def fail():raise error
                class Fake:
                    async def complete(self,messages,tools):return await fail()
                async def exercise():
                    if scope=='ask':return await integration.ask(Fake(),[],[],RequestMetadata('fake','selected',CONFIG))
                    return await integration.tool(SimpleNamespace(name='run_flow',id='id',arguments={}),fail)
                with self.assertRaises(type(error)) as caught:asyncio.run(exercise())
                self.assertIs(caught.exception,error)
                self.assertIsNotNone(observer.failure)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value, *, raw=False):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        contents = value if raw else canonical(value) + b"\n"
        path.write_bytes(contents)
        path.chmod(0o600)
        return {"path": path.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(contents).hexdigest()}

    def fixture(self, *, tool="run_flow", outcome="failed", event="executed_tool", source=SOURCE,
                inputs=INPUTS, rc=1, schema=2, relevant=None):
        execution = uuid4().hex
        prefix = f".evidence/tools/{execution}"
        launched = event == "executed_tool"
        observed = event in {"executed_tool", "launch_failure"}
        logs = [self.write(prefix + "/command-00.log", b"SYNTHETIC TOOL BYTES\n", raw=True)] if observed else []
        commands = [{"log": log, "process_launched": launched, "returncode": rc, "timed_out": False} for log in logs]
        envelope = {"schema_version": schema, "execution_id": execution, "call_id": "synthetic",
            "tool": tool, "source_revision": source, "input_revision": inputs, "image_id": IMAGE,
            "commands": commands, "capture_errors": [], "event": event,
            "execution_outcome": outcome if launched else None, "relevant_to": relevant or [tool],
            "observed_command_count": len(commands), "launched_command_count": sum(c["process_launched"] for c in commands),
            "diagnostic": {"kind": "tool_error", "message": "SYNTHETIC placement blocker"},
            "result": {"ok": outcome == "passed"}}
        result = self.write(prefix + "/result.json", envelope)
        receipt = None
        if launched:
            value = ExecutionReceipt(execution, tool, source, inputs, IMAGE, Artifact(**result),
                                     tuple(Artifact(**log) for log in logs), True).plain()
            receipt = self.write(prefix + "/receipt.json", value)
        return {"tool_evidence": {"execution_id": execution, "result": result, "receipt": receipt}}, envelope

    def record(self, store, wrapped, *, source=SOURCE, inputs=INPUTS):
        return store.record(wrapped, source_revision=source, input_revision=inputs,
                            relevant_tools=("run_flow",),
                            current_input_revisions_by_tool={"run_flow": inputs, "write_file": OTHER_INPUTS})

    def test_replay_keeps_measured_blocker_rejection_and_exact_receipt_binding(self):
        store = LedgerSnapshots(self.root, IMAGE)
        failed, _ = self.fixture()
        self.record(store, failed)
        rejected, _ = self.fixture(tool="write_file", event="schema_rejection", inputs=OTHER_INPUTS,
                                   relevant=["run_flow"])
        expected = self.record(store, rejected)
        path = self.root / ".evidence/ledger-summary.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(list(path.parent.glob(".ledger-*.tmp")), [])
        restored = LedgerSnapshots(self.root, IMAGE)
        actual = restored.ledger.summary(source_revision=SOURCE, input_revision=INPUTS,
            relevant_tools=("run_flow",), current_input_revisions_by_tool={"run_flow": INPUTS, "write_file": OTHER_INPUTS})
        self.assertEqual(actual, expected)
        self.assertEqual(actual["primary_blocker"]["receipt"]["execution_id"], failed["tool_evidence"]["execution_id"])
        self.assertEqual(actual["latest_blocked_repair"]["relationship"], "current_snapshot")
        passed, _ = self.fixture(outcome="passed", rc=0)
        self.assertIsNone(self.record(restored, passed)["primary_blocker"])

    def test_old_schema_is_unknown_not_upgraded_from_ok(self):
        store = LedgerSnapshots(self.root, IMAGE)
        old, _ = self.fixture(schema=1, outcome="passed", rc=0)
        with self.assertRaisesRegex(ValueError, "unknown.*schema2"):
            self.record(store, old)
        self.assertFalse((self.root / ".evidence/ledger-summary.json").exists())

    def test_failed_launch_replay_is_infrastructure_attempt_and_keeps_prior_blocker(self):
        store = LedgerSnapshots(self.root, IMAGE)
        failed, _ = self.fixture()
        self.record(store, failed)
        launch, _ = self.fixture(event="launch_failure", rc=127)
        summary = self.record(store, launch)
        self.assertEqual(summary["primary_blocker"]["receipt"]["execution_id"], failed["tool_evidence"]["execution_id"])
        self.assertEqual(summary["latest_blocked_repair"]["event"], "launch_failure")
        self.assertFalse(summary["latest_blocked_repair"]["executed"])
        restored = LedgerSnapshots(self.root, IMAGE)
        self.assertEqual(restored.events, store.events)

    def test_incomplete_new_schema_does_not_guess_an_outcome(self):
        store = LedgerSnapshots(self.root, IMAGE)
        wrapped, envelope = self.fixture(tool="write_file", event="schema_rejection")
        del envelope["relevant_to"]
        wrapped["tool_evidence"]["result"] = self.write(wrapped["tool_evidence"]["result"]["path"], envelope)
        with self.assertRaisesRegex(ValueError, "unknown.*schema2"):
            self.record(store, wrapped)

    def test_changed_log_receipt_and_image_are_rejected(self):
        for artifact in ("log", "receipt", "image"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as directory:
                original = self.root
                self.root = Path(directory)
                try:
                    store = LedgerSnapshots(self.root, IMAGE)
                    wrapped, _ = self.fixture()
                    self.record(store, wrapped)
                    execution = wrapped["tool_evidence"]["execution_id"]
                    if artifact == "log":
                        (self.root / f".evidence/tools/{execution}/command-00.log").write_text("CHANGED")
                    elif artifact == "receipt":
                        (self.root / wrapped["tool_evidence"]["receipt"]["path"]).write_text("{}")
                    with self.assertRaises(ValueError):
                        LedgerSnapshots(self.root, IMAGE if artifact != "image" else "sha256:" + "f" * 64)
                finally:
                    self.root = original

    def test_forged_pass_with_actual_nonzero_exit_is_rejected(self):
        store = LedgerSnapshots(self.root, IMAGE)
        wrapped, _ = self.fixture(outcome="passed", rc=1)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.record(store, wrapped)

    def test_snapshot_cannot_use_a_receipt_from_another_execution(self):
        store = LedgerSnapshots(self.root, IMAGE)
        first, _ = self.fixture()
        second, _ = self.fixture()
        first["tool_evidence"]["receipt"] = second["tool_evidence"]["receipt"]
        with self.assertRaisesRegex(ValueError, "another execution"):
            self.record(store, first)

    def test_symlink_or_hardlinked_summary_is_not_replaced(self):
        for link_type in ("symlink", "hardlink"):
            with self.subTest(link_type=link_type), tempfile.TemporaryDirectory() as directory:
                original = self.root
                self.root = Path(directory)
                try:
                    store = LedgerSnapshots(self.root, IMAGE)
                    target = self.root / "outside"
                    target.write_text("SENTINEL")
                    target.chmod(0o600)
                    path = self.root / ".evidence/ledger-summary.json"
                    if link_type == "symlink":
                        path.symlink_to(target)
                    else:
                        os.link(target, path)
                    wrapped, _ = self.fixture()
                    with self.assertRaises((OSError, ValueError)):
                        self.record(store, wrapped)
                    self.assertEqual(target.read_text(), "SENTINEL")
                finally:
                    self.root = original

    def test_fsync_failure_keeps_old_snapshot_and_disables_uncertain_writer(self):
        store = LedgerSnapshots(self.root, IMAGE)
        first, _ = self.fixture()
        self.record(store, first)
        path = self.root / ".evidence/ledger-summary.json"
        original = path.read_bytes()
        second, _ = self.fixture(tool="write_file", event="schema_rejection", relevant=["run_flow"])
        with patch("app.observability.snapshot.os.fsync", side_effect=OSError("SYNTHETIC disk failure")):
            with self.assertRaises(OSError):
                self.record(store, second)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.glob(".ledger-*.tmp")), [])
        with self.assertRaisesRegex(ValueError, "writer is failed"):
            self.record(store, second)

    def test_duplicate_event_or_changed_summary_cannot_invent_resolution(self):
        store = LedgerSnapshots(self.root, IMAGE)
        first, _ = self.fixture()
        self.record(store, first)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.record(store, first)
        path = self.root / ".evidence/ledger-summary.json"
        saved = json.loads(path.read_bytes())
        saved["summary"]["primary_blocker"] = None
        path.write_bytes(canonical(saved))
        with self.assertRaisesRegex(ValueError, "differs from authenticated replay"):
            LedgerSnapshots(self.root, IMAGE)

    def test_crash_between_sidecars_and_summary_cannot_silently_drop_a_blocker(self):
        store = LedgerSnapshots(self.root, IMAGE)
        first, _ = self.fixture()
        self.record(store, first)
        self.fixture()  # Complete synthetic sidecars, no atomic journal commit.
        with self.assertRaisesRegex(ValueError, "execution/order unknown"):
            LedgerSnapshots(self.root, IMAGE)


if __name__ == "__main__":
    unittest.main()
