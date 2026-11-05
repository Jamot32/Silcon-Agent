"""Pure plan/config capacity controls; no native execution."""
import asyncio
import pytest
from app.llm import read_boundary
from app.llm.codex import CodexCLIClient, ProviderError
from app.llm.types import Message


def plan(tmp_path, count):
    roots=[]
    for index in range(count):
        root=tmp_path/str(index);root.mkdir();roots.append(str(root))
    cwd=tmp_path/'private';cwd.mkdir(mode=0o700)
    return read_boundary.build_launch(['/synthetic/codex'],original_project_root=roots[0],worktree_roots=roots[1:],cwd=str(cwd),platform='darwin')


def test_complete_nine_root_inventory_is_representable(tmp_path):
    assert read_boundary.MAX_ROOTS == 16
    assert len(plan(tmp_path,9).protected_roots)==9


def test_raw_seventeen_root_inventory_is_rejected(tmp_path):
    with pytest.raises(read_boundary.PlanError) as caught:plan(tmp_path,17)
    assert caught.value.code=='host_root_roster'


def test_default_client_still_fails_closed_without_host_policy():
    client=CodexCLIClient(executable='/synthetic/codex')
    with pytest.raises(ProviderError) as caught:asyncio.run(client.complete([Message(role='user',content='neutral')],[]))
    assert caught.value.kind=='boundary_policy' and client.budget.calls==0


def test_opt_in_fixture_keeps_explicit_none_unconfigured(configured_codex_transport):
    client=CodexCLIClient(executable='/synthetic/codex',launch_policy=None)
    with pytest.raises(ProviderError) as caught:asyncio.run(client.complete([],[]))
    assert caught.value.kind=='boundary_policy' and client.budget.calls==0
