"""Real external Worker/factory/Codex/RunObserver; only native process is mocked.

The orchestrator is deliberately synthetic and produces no RTL/physical/package
claim. No corpus, retained fixture, provider, Docker or sandbox process is used.
"""
import asyncio,hashlib,json,os
from pathlib import Path
from unittest.mock import patch
import pytest
from app import worker
from app.llm import codex,read_boundary,factory
from app.llm.types import BudgetExceeded,Message
from app.observability import RunObserver
from app.schemas import Outcome
from app.storage import RunStore
from boundary_test_support import install_neutral_policy

class Input:
 def __init__(self):self.raw=b''
 def write(self,value):self.raw+=value
 async def drain(self):pass
 def close(self):pass
class Stream:
 def __init__(self,events=(),block=None):self.lines=[json.dumps(x).encode()+b'\n'for x in events];self.block=block
 async def readline(self):
  if self.block is not None:
   self.block.set();await asyncio.Event().wait()
  return self.lines.pop(0)if self.lines else b''
 async def read(self,count):return b''
class Process:
 pid=999999999
 def __init__(self,output=b'',events=(),block=None):self.output=output;self.returncode=None;self.stdin=Input();self.stdout=Stream(events,block);self.stderr=Stream();self.waits=0
 async def communicate(self):self.returncode=0;return self.output,b''
 async def wait(self):self.waits+=1;self.returncode=0;return 0

def response_events():return [{'type':'thread.started'},{'type':'turn.started'},{'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'content':'neutral synthetic response','tool_calls':[]})}},{'type':'turn.completed','usage':{'input_tokens':10,'cached_input_tokens':2,'output_tokens':4}}]

@pytest.fixture
def host(monkeypatch,tmp_path):
 project=tmp_path/'project';project.mkdir();configdir=tmp_path/'config';configdir.mkdir(mode=0o700)
 binary=tmp_path/'synthetic-sandbox';binary.write_bytes(b'neutral nonexecuted mock identity');binary.chmod(0o755)
 installed=install_neutral_policy(monkeypatch,project,configdir,tmp_path/'installed-generation',binary)
 config=installed['config'];private=installed['private']
 # Keep the normal home for unnamed container UIDs; never invent a fallback.
 inherited_home=os.environ.get('HOME')
 env={'LLM_PROVIDER':'codex','CODEX_MODEL':'gpt-6.1-sol','LLM_MAX_CALLS':'32','LLM_MAX_TOKENS':'300000','RUN_BUDGET_USD':'1','SILICON_CODEX_BOUNDARY_CONFIG':str(config)}
 if inherited_home is not None:env['HOME']=inherited_home
 with patch.dict(os.environ,env,clear=True):
  assert os.environ.get('HOME')==inherited_home
  monkeypatch.setattr(read_boundary.sys,'platform','darwin');monkeypatch.setattr(read_boundary,'SANDBOX_EXEC',str(binary));monkeypatch.setattr(codex.shutil,'which',lambda name:'/usr/bin/neutral-codex')
  store=RunStore(project/'runs');store.create_run('Handwritten neutral synthetic Worker composition control');run=store.claim_pending()
  yield {'project':project,'private':private,'binary':binary,'config':config,'store':store,'run':run,'calls':[],'killpg':[],'captured':{},'git_calls':installed['git_calls']}

class SyntheticOrchestrator:
 def __init__(self,llm,tools,*,observer,**kwargs):
  self.llm,self.observer=llm,observer
  assert type(llm)is codex.CodexCLIClient
  assert tools.observer is observer
  assert worker.create_llm is factory.create_llm
  self.design_spec=None
 async def run(self):
  self.observer.transition('SPEC')
  async def ordinary_two_arg(messages,tools):return await self.observer.ask(self.llm,messages,tools)
  completion=await ordinary_two_arg([Message(role='user',content='neutral data only')],[])
  assert completion.content=='neutral synthetic response'
  self.observer.transition('DONE',previous_ok=True)
  return Outcome(status='done',summary='Synthetic Worker transport control; no hardware execution')

def setup(monkeypatch,host,*,events=None,block=None,observer_fault=False):
 processes=[Process(b'codex-cli 0.163.0'),Process(b'Logged in using ChatGPT'),Process(events=response_events()if events is None else events,block=block)]
 async def spawn(*args,**kwargs):
  host['calls'].append((args,kwargs))
  cwd=Path(kwargs['cwd']);assert cwd.stat().st_mode&0o777==0o700 and list(cwd.iterdir())==[]
  assert args[0]==str(host['binary']) and kwargs['close_fds']is True and kwargs['start_new_session']is True
  assert not {'pass_fds','shell','preexec_fn'}&set(kwargs)
  assert 'SILICON_CODEX_BOUNDARY_CONFIG'not in kwargs['env']
  return processes.pop(0)
 monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn);monkeypatch.setattr(os,'killpg',lambda pid,sig:host['killpg'].append((pid,sig)))
 def observer_factory(work,run_id):
  observer=worker._run_observer(work,run_id)
  host['captured']['observer']=observer
  if observer_fault:
   original=observer._provider_callback
   def fail_usage(payload):
    if payload['event']=='usage':raise OSError('synthetic observer sentinel')
    original(payload)
   observer._provider_callback=fail_usage
  return observer
 class Capture(SyntheticOrchestrator):
  def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);host['captured']['llm']=self.llm
 return worker.Worker(host['store'],poll_interval=.001,orchestrator_factory=Capture,observer_factory=observer_factory)

def trace(host):
 p=host['store'].root/host['run'].id/'trace.jsonl';return [json.loads(x)for x in p.read_text().splitlines()]
def terminal(host):
 values=[json.loads(x.payload_json)for x in host['store'].events(host['run'].id)if x.type=='run_finished'];assert len(values)==1;return values[0]
def assert_closed(host,status):
 saved=host['store'].get_run(host['run'].id);assert saved.status==status
 rows=trace(host);assert rows[-1]['type']=='run_finished'and rows[-1]['payload']['status']==status
 assert rows[-1]['payload']['outcome_authority']=='store_confirmed'
 assert not any(x['type']in {'tool_call','command_finished'}for x in rows)
 assert list(host['private'].iterdir())==[]
 return rows

def test_worker_real_factory_client_observer_success(monkeypatch,host):
 runtime=setup(monkeypatch,host);asyncio.run(runtime.execute(host['run']));rows=assert_closed(host,'done');llm=host['captured']['llm'];observer=host['captured']['observer']
 assert observer.failure is None and not llm.observer_failed
 assert (host['config'].parent/'installation.json').is_file()
 assert len(host['git_calls'])==8  # real setup+factory admission, each with two Git points
 assert (llm.budget.calls,llm.budget.input_tokens,llm.budget.output_tokens)==(1,10,4)and llm.budget.cost_usd is None
 assert len(host['calls'])==3 and len({x[1]['cwd']for x in host['calls']})==1
 assert all(not Path(x[1]['cwd']).exists()for x in host['calls'])
 ends=[x['payload']for x in rows if x['type']=='llm_call'and x['payload']['phase']=='attempt_finished'];assert len(ends)==1 and ends[0]['kind']=='completed'and ends[0]['usage']['input_tokens']==10
 assert 'neutral data only'not in json.dumps(rows)
 assert host['calls'][0][1]['stdin']==asyncio.subprocess.DEVNULL and host['calls'][2][1]['stdin']==asyncio.subprocess.PIPE

def test_worker_missing_host_config_fails_before_native_process(monkeypatch,host):
 runtime=setup(monkeypatch,host);monkeypatch.delenv('SILICON_CODEX_BOUNDARY_CONFIG');asyncio.run(runtime.execute(host['run']));rows=assert_closed(host,'failed')
 assert host['calls']==[] and 'llm'not in host['captured']
 assert str(host['config'])not in host['store'].get_run(host['run'].id).error
 assert not any(x['type']=='llm_call'for x in rows)

@pytest.mark.parametrize('observer_fault,budget_limit,expected',[(False,1,'budget_exceeded'),(True,300000,'observability_incomplete'),(True,1,'budget_exceeded')])
def test_worker_real_usage_budget_and_observer_primary(monkeypatch,host,observer_fault,budget_limit,expected):
 monkeypatch.setenv('LLM_MAX_TOKENS',str(budget_limit));runtime=setup(monkeypatch,host,observer_fault=observer_fault);asyncio.run(runtime.execute(host['run']));rows=assert_closed(host,'failed');llm=host['captured']['llm']
 assert terminal(host)['failure_class']==expected
 assert (llm.budget.calls,llm.budget.input_tokens,llm.budget.output_tokens)==(1,10,4)and llm.budget.cost_usd is None
 assert llm.observer_failed is observer_fault and len(host['calls'])==3
 assert 'synthetic observer sentinel'not in json.dumps(rows)

def test_worker_actual_provider_error_preserves_unknown_usage(monkeypatch,host):
 runtime=setup(monkeypatch,host,events=[{'type':'error','message':'unauthorized'}]);asyncio.run(runtime.execute(host['run']));rows=assert_closed(host,'failed');llm=host['captured']['llm']
 assert terminal(host)['failure_class']=='llm_api_error'and llm.budget.calls==1 and llm.budget.cost_usd is None
 ends=[x['payload']for x in rows if x['type']=='llm_call'and x['payload']['phase']=='attempt_finished'];assert len(ends)==1 and ends[0]['kind']=='authentication'and ends[0]['usage']is None
 assert len(host['killpg'])==1 and len(host['calls'])==3

def test_worker_cancellation_settles_process_then_removes_cwd(monkeypatch,host):
 async def check():
  entered=asyncio.Event();runtime=setup(monkeypatch,host,block=entered);task=asyncio.create_task(runtime.execute(host['run']));await asyncio.wait_for(entered.wait(),2);host['store'].request_cancel(host['run'].id);await asyncio.wait_for(task,2)
 asyncio.run(check());rows=assert_closed(host,'cancelled');llm=host['captured']['llm'];assert llm.budget.calls==1 and llm.budget.cost_usd is None and len(host['killpg'])==1
 ends=[x['payload']for x in rows if x['type']=='llm_call'and x['payload']['phase']=='attempt_finished'];assert len(ends)==1 and ends[0]['kind']=='cancelled'and ends[0]['usage']is None
