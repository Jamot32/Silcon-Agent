"""Opt-in typed synthetic host configuration; no sandbox/process is executed."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.llm import codex, read_boundary, host_policy

def install_neutral_policy(monkeypatch, project, owner, generation, binary):
    """Real installed generation + metadata scans; only fixed Git stdout is mocked."""
    objects=project/'.git'/'objects';objects.mkdir(parents=True,mode=0o700)
    inventory=owner/'inventory.json'
    inventory.write_text(json.dumps({'schema_version':1,'original_project_root':str(project),
        'registered_roots':[str(project)],'explicit_private_roots':[],
        'git_object_roots':[str(objects)],'retained_private_roots':[],
        'retained_inventory_complete':True,'max_entries':1000,'max_depth':16,
        'sandbox_exec_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}))
    inventory.chmod(0o600);calls=[]
    def git(args, **kwargs):
        assert args[:6]==['git','--no-optional-locks','-c','core.fsmonitor=false','-C',str(project)]
        assert kwargs=={'stdin':-3,'stdout':-1,'stderr':-3,'check':False,'timeout':10}
        calls.append(args)
        if args[6:]==['worktree','list','--porcelain','-z']:
            raw=b'worktree '+str(project).encode()+b'\0HEAD synthetic\0\0'
        else:
            assert args[6:]==['rev-parse','--path-format=absolute','--git-common-dir']
            raw=str(objects.parent).encode()+b'\n'
        return SimpleNamespace(returncode=0,stdout=raw)
    monkeypatch.setattr(host_policy.subprocess,'run',git)
    monkeypatch.setattr(read_boundary.sys,'platform','darwin')
    monkeypatch.setattr(read_boundary,'SANDBOX_EXEC',str(binary))
    config=host_policy.install(inventory,generation)
    policy=read_boundary.CodexLaunchPolicy.from_file(str(config),run_work_dir=project)
    return {'policy':policy,'config':config,'private':generation/'empty-cwd','git_calls':calls}

@pytest.fixture
def codex_host_policy(monkeypatch, tmp_path):
    project = tmp_path / 'protected-project'; project.mkdir()
    run = project / 'run'; run.mkdir()
    owner = tmp_path / 'host-config'; owner.mkdir(mode=0o700)
    binary = tmp_path / 'synthetic-sandbox'; binary.write_bytes(b'never executed synthetic sandbox identity'); binary.chmod(0o755)
    installed=install_neutral_policy(monkeypatch,project,owner,tmp_path/'installed-generation',binary)
    monkeypatch.setenv('SILICON_CODEX_BOUNDARY_CONFIG',str(installed['config']))
    yield {**installed,'run':run,'binary':binary}
    assert list(installed['private'].iterdir()) == []

@pytest.fixture
def configured_codex_transport(monkeypatch, codex_host_policy):
    """Opt-in only: omitted policy gets a real validated fixture, explicit None stays None."""
    original = codex.CodexCLIClient.__init__
    def configured(self, *args, **kwargs):
        kwargs.setdefault('launch_policy', codex_host_policy['policy'])
        original(self, *args, **kwargs)
    monkeypatch.setattr(codex.CodexCLIClient, '__init__', configured)
    return codex_host_policy

async def checked_client(client, env, executable):
    with client.launch_policy.open_boundary() as boundary:
        return await client._check_cli(env, executable, boundary)

async def request_client(client, args, prompt, env, incoming):
    with client.launch_policy.open_boundary() as boundary:
        return await client._request(args, prompt, env, incoming, boundary)

def assert_wrapped_launch(args, kwargs):
    assert args[0] == read_boundary.SANDBOX_EXEC and args[1] == '-p'
    assert kwargs['close_fds'] is True and kwargs['start_new_session'] is True
    assert not {'pass_fds', 'shell', 'preexec_fn'} & kwargs.keys()
    assert Path(kwargs['cwd']).stat().st_mode & 0o777 == 0o700
    assert list(Path(kwargs['cwd']).iterdir()) == []
    return tuple(args[args.index('--') + 1:])
