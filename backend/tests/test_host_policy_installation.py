"""Fresh synthetic metadata, mocked Git/native processes. No CLI/provider/EDA/sandbox."""
import asyncio,hashlib,json,os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.llm import codex,read_boundary,host_policy,factory
from app.llm.types import BudgetExceeded
import manage_worker,guarded_codex_smoke,provider_smoke_test,codex_smoke_test

@pytest.fixture
def host(tmp_path,monkeypatch):
    project=tmp_path/'project';project.mkdir(mode=0o700)
    objects=project/'.git'/'objects';objects.mkdir(parents=True,mode=0o700)
    run=project/'runs';run.mkdir(mode=0o700)
    inputs=tmp_path/'trusted-input';inputs.mkdir(mode=0o700)
    binary=tmp_path/'synthetic-sandbox';binary.write_bytes(b'never executed');binary.chmod(0o755)
    value={'schema_version':1,'original_project_root':str(project),'registered_roots':[str(project)],
        'explicit_private_roots':[],'git_object_roots':[str(objects)],'retained_private_roots':[],
        'retained_inventory_complete':True,'max_entries':1000,'max_depth':16,
        'sandbox_exec_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
    source=inputs/'inventory.json'
    def save():source.write_text(json.dumps(value));source.chmod(0o600)
    save();calls=[];actual=[str(project)]
    def git(args,**kwargs):
        assert kwargs=={'stdin':-3,'stdout':-1,'stderr':-3,'check':False,'timeout':10}
        calls.append(args)
        assert args[:6]==['git','--no-optional-locks','-c','core.fsmonitor=false','-C',str(project)]
        if args[6:]==['worktree','list','--porcelain','-z']:
            raw=b''.join(b'worktree '+p.encode()+b'\0HEAD synthetic\0\0'for p in actual)
        else:
            assert args[6:]==['rev-parse','--path-format=absolute','--git-common-dir'];raw=str(objects.parent).encode()+b'\n'
        return SimpleNamespace(returncode=0,stdout=raw)
    monkeypatch.setattr(host_policy.subprocess,'run',git)
    monkeypatch.setattr(read_boundary,'SANDBOX_EXEC',str(binary))
    monkeypatch.setattr(read_boundary.sys,'platform','darwin')
    with patch.dict(os.environ,{'LLM_PROVIDER':'codex','CODEX_MODEL':'gpt-6.1-sol','LLM_MAX_CALLS':'32','LLM_MAX_TOKENS':'300000','RUN_BUDGET_USD':'1'},clear=True):
        yield {'project':project,'objects':objects,'run':run,'source':source,'value':value,'save':save,
            'generation':tmp_path/'generation','binary':binary,'actual':actual,'calls':calls}

def install(host):return host_policy.install(host['source'],host['generation'])

def test_clean_clone_policy_installs_and_factory_reads_actual_inventory(host,monkeypatch):
    policy=install(host);monkeypatch.setenv('SILICON_CODEX_BOUNDARY_CONFIG',str(policy))
    client=factory.create_llm(run_work_dir=host['run'])
    assert type(client)is codex.CodexCLIClient
    assert (client.budget.max_calls,client.budget.max_tokens,client.budget.max_usd)==(32,300000,1)
    assert len(host['calls'])==8  # two Git commands at two setup+two factory points
    assert policy.stat().st_mode&0o777==0o600 and host['generation'].stat().st_mode&0o777==0o700
    assert (host['generation']/'empty-cwd').stat().st_mode&0o777==0o700
    assert not (host['project']/'.env').exists()

def test_registered_drift_between_installation_and_client_is_rejected(host,monkeypatch):
    policy=install(host);host['actual'].append(str(host['project']/'new-worktree'))
    monkeypatch.setenv('SILICON_CODEX_BOUNDARY_CONFIG',str(policy))
    with pytest.raises(codex.ProviderError)as caught:factory.create_llm(run_work_dir=host['run'])
    assert caught.value.kind=='local_configuration'

@pytest.mark.parametrize('key,value',[('retained_inventory_complete',False),('git_object_roots',[]),('explicit_private_roots',['/private/tmp'])])
def test_unadmitted_incomplete_or_broad_inventory_refuses_before_install(host,key,value):
    host['value'][key]=value;host['save']()
    with pytest.raises(host_policy.HostSetupError):install(host)
    assert not host['generation'].exists()

def test_private_roots_are_separate_and_never_silently_dropped(host):
    private=host['source'].parent.parent/'retained';private.mkdir(mode=0o700)
    host['value']['explicit_private_roots']=[str(private)];host['value']['retained_private_roots']=[str(private)];host['save']()
    policy=install(host);data=json.loads(policy.read_text())
    assert data['worktree_roots']==[] and data['additional_archive_roots']==[str(private)]
    record=json.loads(policy.with_name('installation.json').read_text())
    assert all(len(r['registered_roots'])==1 for r in record['collector_receipts'])

@pytest.mark.parametrize('fault',['record_missing','inventory_tamper','existing_generation'])
def test_failed_or_modified_generation_cannot_be_used_or_overwritten(host,fault):
    policy=install(host)
    if fault=='record_missing':policy.with_name('installation.json').unlink()
    elif fault=='inventory_tamper':
        path=policy.with_name('inventory.json');value=json.loads(path.read_text());value['max_depth']=15;path.write_text(json.dumps(value))
    else:
        before=policy.read_bytes()
        with pytest.raises(host_policy.HostSetupError):install(host)
        assert policy.read_bytes()==before;return
    with pytest.raises(host_policy.HostSetupError):host_policy.admit_installed(policy,host['run'])

def test_meta_factory_ignores_stale_policy_and_preserves_unlimited_tokens(host,monkeypatch):
    class Meta:
        def __init__(self,*,budget):self.budget=budget
    from app.llm import client
    monkeypatch.setattr(client,'MetaLLM',Meta);monkeypatch.setenv('LLM_PROVIDER','meta');monkeypatch.setenv('SILICON_CODEX_BOUNDARY_CONFIG','/missing/stale')
    monkeypatch.setenv('LLM_MAX_TOKENS','')
    llm=factory.create_llm(run_work_dir=None)
    assert type(llm)is Meta and llm.budget.max_tokens is None and host['calls']==[]

def test_manager_only_forwards_locator_after_provider_is_left_to_child(host,monkeypatch):
    # The parent does not inspect .env or reject a stale policy for a Meta child.
    monkeypatch.delenv('LLM_PROVIDER');monkeypatch.setattr(manage_worker,'ROOT',host['project'])
    monkeypatch.setattr(manage_worker.shutil,'which',lambda name:'/synthetic/uv')
    monkeypatch.setattr(manage_worker.time,'sleep',lambda delay:None)
    launches=[]
    def launch(args,**kwargs):launches.append((args,kwargs));return SimpleNamespace(pid=987654321,poll=lambda:None)
    monkeypatch.setattr(manage_worker.subprocess,'Popen',launch)
    assert manage_worker.start(host['run'],codex_policy='/stale/external/policy')==0
    assert launches[0][1]['env']['SILICON_CODEX_BOUNDARY_CONFIG']=='/stale/external/policy'
    assert launches[0][0][-4:]==['--runs-dir',str(host['run']),'--owner-token',json.loads((host['run']/'worker.json').read_text())['token']]
    assert host['calls']==[]

class Input:
    def __init__(self):self.raw=b''
    def write(self,data):self.raw+=data
    async def drain(self):pass
    def close(self):pass
class Reader:
    def __init__(self,rows=(),block=None):self.rows=[json.dumps(x).encode()+b'\n'for x in rows];self.block=block
    async def readline(self):
        if self.block is not None:self.block.set();await asyncio.Event().wait()
        return self.rows.pop(0)if self.rows else b''
    async def read(self,n):return b''
class Process:
    pid=999999999
    def __init__(self,raw=b'',rows=(),block=None):self.raw=raw;self.stdin=Input();self.stdout=Reader(rows,block);self.stderr=Reader();self.returncode=None
    async def communicate(self):self.returncode=0;return self.raw,b''
    async def wait(self):self.returncode=0;return 0

def processes(host,monkeypatch,block=None,provider_error=False,usage_retry=False):
    response={'content':'','tool_calls':[{'id':'neutral','name':'add','arguments_json':'{"a":2,"b":3}'}]}
    rows=[{'type':'turn.started'},{'type':'item.completed','item':{'type':'agent_message','text':json.dumps(response)}},{'type':'turn.completed','usage':{'input_tokens':7,'cached_input_tokens':2,'output_tokens':5}}]
    if provider_error:rows=[{'type':'error','message':'authentication failed'}]
    queued=[Process(b'codex-cli 0.163.0'),Process(b'Logged in using ChatGPT'),Process(rows=rows,block=block)]
    if usage_retry:
        queued.insert(2,Process(rows=[*rows,{'type':'error','message':'HTTP 503'}]))
    launches=[]
    async def spawn(*args,**kwargs):
        assert args[0]==str(host['binary']) and args[1]=='-p' and kwargs['close_fds']is True and kwargs['start_new_session']is True
        assert not {'pass_fds','shell','preexec_fn'}&set(kwargs)
        assert 'SILICON_CODEX_BOUNDARY_CONFIG'not in kwargs['env']
        inner=args[args.index('--')+1:];assert inner[0]=='/synthetic/codex'
        assert Path(kwargs['cwd']).stat().st_mode&0o777==0o700 and list(Path(kwargs['cwd']).iterdir())==[]
        launches.append((args,kwargs));return queued.pop(0)
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn);monkeypatch.setattr(codex.shutil,'which',lambda name:'/synthetic/codex')
    monkeypatch.setattr(os,'killpg',lambda pid,sig:None)
    return launches

def test_guarded_smoke_actual_factory_observer_parser_and_usage(host,monkeypatch):
    policy=install(host);launches=processes(host,monkeypatch)
    result=asyncio.run(guarded_codex_smoke.smoke(policy,host['run']))
    assert result['status']=='passed' and result['calls']==1 and result['cost_usd']is None and result['serving_model']is None
    assert (result['reported_input_tokens'],result['reported_cached_input_tokens'],result['reported_output_tokens'])==(7,2,5)
    assert len(launches)==3 and list((host['generation']/'empty-cwd').iterdir())==[]
    trace=[json.loads(x)for x in Path(result['trace_path']).read_text().splitlines()]
    assert trace[-1]['type']=='run_finished' and trace[-1]['payload']['status']=='done'
    assert not any(r['type']in {'tool_call','command_finished'}for r in trace)
    assert result['hardware_or_tool_execution']is False and result['whole_filesystem_isolation_proved']is False

@pytest.mark.parametrize('primary_kind',['budget','cancel'])
def test_guarded_smoke_primary_error_survives_close_fault(host,monkeypatch,primary_kind):
    policy=install(host)
    original_close=guarded_codex_smoke.RunObserver.close
    def fail_close(self):
        original_close(self)
        raise OSError('private cleanup sentinel')
    monkeypatch.setattr(guarded_codex_smoke.RunObserver,'close',fail_close)
    async def exercise():
        entered=asyncio.Event()if primary_kind=='cancel'else None
        processes(host,monkeypatch,entered)
        if primary_kind=='budget':monkeypatch.setenv('LLM_MAX_TOKENS','1')
        task=asyncio.create_task(guarded_codex_smoke.smoke(policy,host['run']))
        if entered is not None:await asyncio.wait_for(entered.wait(),2);task.cancel()
        with pytest.raises(BudgetExceeded if primary_kind=='budget'else asyncio.CancelledError)as caught:await task
        assert caught.value.__notes__==['Guarded smoke cleanup also failed.']
        assert 'private cleanup sentinel'not in str(caught.value)
    asyncio.run(exercise())
    assert list((host['generation']/'empty-cwd').iterdir())==[]

def test_provider_dispatch_uses_guarded_codex_and_preserves_meta(host,monkeypatch):
    monkeypatch.setattr(guarded_codex_smoke,'main',lambda:81)
    assert provider_smoke_test.main()==81
    import llm_smoke_test
    monkeypatch.setenv('LLM_PROVIDER','meta');monkeypatch.setattr(llm_smoke_test,'main',lambda:82)
    assert provider_smoke_test.main()==82

def test_old_raw_smoke_is_explicit_only_and_does_not_write_fixtures(monkeypatch):
    monkeypatch.setattr('sys.argv',['codex_smoke_test.py'])
    assert codex_smoke_test.main()==2
    source=Path(codex_smoke_test.__file__).read_text()
    assert 'events.jsonl'not in source and 'provenance.json'not in source


def test_failed_guarded_attempt_keeps_missing_usage_unknown(host,monkeypatch):
    policy=install(host);processes(host,monkeypatch,provider_error=True)
    with pytest.raises(codex.ProviderError)as caught:asyncio.run(guarded_codex_smoke.smoke(policy,host['run']))
    assert caught.value.kind=='authentication'
    traces=list(host['run'].glob('guarded-smoke-*/trace.jsonl'));assert len(traces)==1
    rows=[json.loads(x)for x in traces[0].read_text().splitlines()]
    attempts=[r['payload']for r in rows if r['type']=='llm_call'and r['payload'].get('phase')=='attempt_finished']
    assert len(attempts)==1 and attempts[0]['kind']=='authentication'and attempts[0]['usage']is None
    assert rows[-1]['payload']['status']=='failed'


def test_bad_declared_sandbox_identity_never_completes_installation(host):
    host['value']['sandbox_exec_sha256']='0'*64;host['save']()
    with pytest.raises(host_policy.HostSetupError):install(host)
    assert not (host['generation']/'installation.json').exists()


def test_raw_git_parent_alias_matches_canonical_inventory_but_keeps_raw_hash(host):
    alias=host['source'].parent.parent/'raw-tmp-alias';alias.symlink_to(host['project'],target_is_directory=True)
    host['actual'][:]=[str(alias)]
    policy=install(host)
    records=json.loads(policy.with_name('installation.json').read_text())['collector_receipts']
    raw=b'worktree '+str(alias).encode()+b'\0HEAD synthetic\0\0'
    assert records[0]['registered_roots']==[str(host['project'])]
    assert records[0]['commands'][0]['stdout_sha256']==hashlib.sha256(raw).hexdigest()

@pytest.mark.parametrize('mutation',['format_only','semantics'])
def test_constructor_second_read_must_bind_to_admitted_policy_record(host,monkeypatch,mutation):
    if mutation=='semantics':
        retained=host['source'].parent.parent/'retained-private';retained.mkdir(mode=0o700)
        host['value']['explicit_private_roots']=[str(retained)];host['value']['retained_private_roots']=[str(retained)];host['save']()
    policy=install(host);original=host_policy.CodexLaunchPolicy.from_file
    def changed(path,*,run_work_dir):
        data=json.loads(Path(path).read_text())
        if mutation=='semantics':data['additional_archive_roots']=[]
        Path(path).write_text(json.dumps(data,indent=2))
        return original(path,run_work_dir=run_work_dir)
    monkeypatch.setattr(host_policy.CodexLaunchPolicy,'from_file',changed)
    with pytest.raises(host_policy.HostSetupError):host_policy.admit_installed(policy,host['run'])


def test_direct_guarded_smoke_rejects_meta_before_factory(host,monkeypatch):
    calls=[]
    def forbidden(**kwargs):calls.append(kwargs);raise AssertionError('No Meta or Codex factory call allowed')
    monkeypatch.setenv('LLM_PROVIDER','meta');monkeypatch.setattr(guarded_codex_smoke,'create_llm',forbidden)
    with pytest.raises(ValueError,match='selected Codex provider'):
        asyncio.run(guarded_codex_smoke.smoke('/unneeded/policy',host['run']))
    assert calls==[] and list(host['run'].iterdir())==[]


def test_usage_bearing_retry_is_not_reported_as_final_response_only_totals(host,monkeypatch):
    policy=install(host);launches=processes(host,monkeypatch,usage_retry=True)
    actual_factory=guarded_codex_smoke.create_llm
    def configured(**kwargs):
        client=actual_factory(**kwargs)
        async def no_sleep(delay):pass
        client.sleep=no_sleep;client.jitter=lambda:0
        return client
    monkeypatch.setattr(guarded_codex_smoke,'create_llm',configured)
    result=asyncio.run(guarded_codex_smoke.smoke(policy,host['run']))
    assert len(launches)==4 and result['calls']==2
    assert result['response_usage_scope']=='last_returned_response_only'
    assert (result['reported_input_tokens'],result['reported_output_tokens'],result['reported_cached_input_tokens'])==(7,5,2)
    assert (result['all_reported_attempt_input_tokens'],result['all_reported_attempt_output_tokens'])==(14,10)
    assert result['unreported_attempt_consumption']=='unknown'and result['cost_usd']is None
