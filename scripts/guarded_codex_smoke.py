#!/usr/bin/env python3
"""One guarded factory/observer transport smoke; no hardware/tool execution."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
from app.llm.factory import create_llm
from app.llm.types import BudgetExceeded, Message, ToolDefinition
from app.observability import RunObserver

ADD=ToolDefinition(name='add',description='Propose adding two integers; the host validates only.',parameters={
    'type':'object','properties':{'a':{'type':'integer'},'b':{'type':'integer'}},
    'required':['a','b'],'additionalProperties':False})

async def smoke(policy_path,run_root):
    if os.getenv('LLM_PROVIDER','codex')!='codex':
        raise ValueError('Guarded smoke requires the selected Codex provider')
    # The actual factory validates installed inventory before provider/preflight.
    root=Path(run_root).resolve(strict=True)
    run_id=uuid4().hex;work=root/('guarded-smoke-'+run_id);work.mkdir(mode=0o700)
    llm=observer=None;primary=None;result=None
    try:
        observer=RunObserver(work,run_id,budget_exceptions=(BudgetExceeded,))
        # This process-local explicit host locator is never written to user .env.
        os.environ['SILICON_CODEX_BOUNDARY_CONFIG']=str(policy_path)
        llm=create_llm(run_work_dir=work)
        observer.configure_llm(llm,'codex');observer.transition('SMOKE')
        async def complete(messages,tools):return await llm.complete(messages,tools)
        class Facade:
            def __getattr__(self,name):return getattr(llm,name)
            async def complete(self,messages,tools):return await complete(messages,tools)
        response=await observer.ask(Facade(),[Message(role='user',content='Propose one call to add with a=2 and b=3. Do not execute anything.')],[ADD])
        if len(response.tool_calls)!=1 or response.tool_calls[0].name!='add' or response.tool_calls[0].arguments!={'a':2,'b':3}:
            raise ValueError('Unexpected neutral smoke proposal')
        result={'status':'passed','provider':'codex','selected_model':llm.model,'serving_model':None,
            'calls':llm.budget.calls,'response_usage_scope':'last_returned_response_only',
            'all_reported_attempt_input_tokens':llm.budget.input_tokens,
            'all_reported_attempt_output_tokens':llm.budget.output_tokens,
            'unreported_attempt_consumption':'unknown','reported_input_tokens':response.input_tokens,
            'reported_cached_input_tokens':response.cached_input_tokens,'reported_output_tokens':response.output_tokens,
            'cost_usd':llm.budget.cost_usd,'trace_path':str(work/'trace.jsonl'),
            'hardware_or_tool_execution':False,'whole_filesystem_isolation_proved':False}
    except BaseException as error:
        primary=error;raise
    finally:
        faults=[]
        if observer is not None:
            try:observer.finish_run('done'if primary is None else 'failed',error=primary)
            except BaseException as error:faults.append(error)
        closer = getattr(llm, "aclose", None) if llm is not None else None
        if closer is not None:
            try:await closer()
            except BaseException as error:faults.append(error)
        if observer is not None:
            try:observer.close()
            except BaseException as error:faults.append(error)
        if faults:
            if primary is None:raise faults[0]
            primary.add_note('Guarded smoke cleanup also failed.')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-policy',default=os.getenv('SILICON_CODEX_BOUNDARY_CONFIG'))
    parser.add_argument('--run-root',type=Path,default=Path(__file__).resolve().parents[1]/'runs')
    args=parser.parse_args()
    try:
        print(json.dumps(asyncio.run(smoke(args.codex_policy,args.run_root)),sort_keys=True));return 0
    except Exception as error:
        print('Guarded Codex smoke failed ('+type(error).__name__+').',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
