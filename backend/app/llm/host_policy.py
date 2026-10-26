#!/usr/bin/env python3
"""Trusted host policy installation. No private input contents are opened."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from app.llm.read_boundary import CodexLaunchPolicy, ReadBoundaryError, _config_bytes, canonical_directory
from app.llm import boundary_metadata as admission

class HostSetupError(ValueError):
    def __init__(self): super().__init__('Codex host inventory or policy is unavailable or unadmitted.')

def encode(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def digest(raw): return hashlib.sha256(raw).hexdigest()

def read_private(path):
    raw = _config_bytes(Path(path))
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise HostSetupError()
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda value: (_ for _ in ()).throw(HostSetupError()))

def inventory(value):
    fields={'schema_version','original_project_root','registered_roots','explicit_private_roots',
            'git_object_roots','retained_private_roots','retained_inventory_complete',
            'max_entries','max_depth','sandbox_exec_sha256'}
    if type(value)is not dict or set(value)!=fields: raise HostSetupError()
    if type(value['registered_roots'])is not list or not value['registered_roots'] or type(value['explicit_private_roots'])is not list: raise HostSetupError()
    roots=value['registered_roots']+value['explicit_private_roots']
    config={k:value[k] for k in ('schema_version','original_project_root','git_object_roots',
            'retained_private_roots','retained_inventory_complete','max_entries','max_depth')}
    config['roots']=roots
    admission.configuration(config)
    if value['original_project_root'] not in value['registered_roots']: raise HostSetupError()
    h=value['sandbox_exec_sha256']
    if type(h)is not str or len(h)!=64 or any(c not in '0123456789abcdef'for c in h): raise HostSetupError()
    return config

def collect_registry(value, receipts):
    project=value['original_project_root']
    # Fixed local Git metadata commands only; no shell, network or file bodies.
    records=[]
    def git(*args):
        argv=['git','--no-optional-locks','-c','core.fsmonitor=false','-C',project,*args]
        result=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,check=False,timeout=10)
        if type(result.returncode)is not int or result.returncode!=0 or len(result.stdout)>65536: raise HostSetupError()
        records.append({'argv':argv,'exit_code':result.returncode,'stdout_sha256':digest(result.stdout)})
        return result.stdout
    raw=git('worktree','list','--porcelain','-z')
    registered=sorted(canonical_directory(field[len(b'worktree '):].decode('utf-8'))for field in raw.split(b'\0')if field.startswith(b'worktree '))
    if registered!=sorted(value['registered_roots']) or len(set(registered))!=len(registered): raise HostSetupError()
    common=git('rev-parse','--path-format=absolute','--git-common-dir').decode('utf-8').strip()
    actual_objects=str(Path(canonical_directory(common))/'objects')
    if actual_objects not in value['git_object_roots']: raise HostSetupError()
    receipt={'commands':records,'registered_roots':registered}
    receipts.append(receipt)
    return {'schema_version':1,'registered_roots':registered,
        'explicit_private_roots':value['explicit_private_roots'],
        'git_registry_receipt_sha256':digest(encode(receipt))}

def admit_inventory(value):
    config=inventory(value);receipts=[]
    report=admission.admit(config,lambda: collect_registry(value,receipts))
    if report['passed']is not True or len(receipts)!=2: raise HostSetupError()
    return report,receipts

def policy_data(value,parent):
    project=value['original_project_root']
    return {'schema_version':1,'original_project_root':project,
        'worktree_roots':[p for p in value['registered_roots']if p!=project],
        'additional_archive_roots':value['explicit_private_roots'],
        'private_cwd_parent':str(parent),'sandbox_exec_sha256':value['sandbox_exec_sha256']}

def write_new(path,value):
    raw=encode(value)
    if len(raw)>16384: raise HostSetupError()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        if os.fstat(fd).st_nlink!=1 or os.write(fd,raw)!=len(raw): raise HostSetupError()
        os.fsync(fd)
    finally: os.close(fd)

def install(inventory_path,generation):
    try:
        value=read_private(inventory_path);config=inventory(value)
        source=Path(inventory_path).resolve(strict=True)
        if any(source.is_relative_to(Path(root))for root in config['roots']): raise HostSetupError()
        report,receipts=admit_inventory(value)
        target=Path(generation)
        if not target.is_absolute() or target.parent.resolve(strict=True)!=target.parent or target.exists() or target.is_symlink(): raise HostSetupError()
        if any(target.is_relative_to(Path(root))for root in config['roots']): raise HostSetupError()
        target.mkdir(mode=0o700)
        private=target/'empty-cwd';private.mkdir(mode=0o700)
        write_new(target/'inventory.json',value)
        data=policy_data(value,private);write_new(target/'policy.json',data)
        checked=CodexLaunchPolicy.from_file(str(target/'policy.json'),run_work_dir=value['original_project_root'])
        # Validate the pinned sandbox binary/cwd composition without starting it.
        with checked.open_boundary():pass
        record={'schema_version':1,'inventory_sha256':digest(encode(value)),
            'policy_sha256':digest(encode(data)),'metadata_helper_sha256':digest(Path(admission.__file__).read_bytes()),
            'admission_sha256':digest(encode(report)),'collector_receipts':receipts}
        # Completion record is written last; an interrupted generation cannot be used.
        write_new(target/'installation.json',record)
        descriptor=os.open(target,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        return target/'policy.json'
    except (OSError,RuntimeError,TypeError,ValueError,UnicodeError,subprocess.SubprocessError):
        raise HostSetupError()from None

def admit_installed(policy_path,run_work_dir):
    try:
        location=Path(policy_path)
        value=read_private(location.with_name('inventory.json'))
        policy=read_private(location);record=read_private(location.with_name('installation.json'))
        fields={'schema_version','inventory_sha256','policy_sha256','metadata_helper_sha256','admission_sha256','collector_receipts'}
        if type(record)is not dict or set(record)!=fields or type(record['schema_version'])is not int or record['schema_version']!=1: raise HostSetupError()
        if (record['inventory_sha256']!=digest(encode(value)) or record['policy_sha256']!=digest(encode(policy)) or
            record['metadata_helper_sha256']!=digest(Path(admission.__file__).read_bytes()) or
            policy!=policy_data(value,location.resolve(strict=True).parent/'empty-cwd')): raise HostSetupError()
        admitted=CodexLaunchPolicy.from_file(str(location),run_work_dir=run_work_dir)
        actual={'schema_version':1,'original_project_root':admitted.original_project_root,
            'worktree_roots':list(admitted.worktree_roots),
            'additional_archive_roots':list(admitted.additional_archive_roots),
            'private_cwd_parent':admitted.private_cwd_parent,'sandbox_exec_sha256':admitted.sandbox_exec_sha256}
        if (admitted._config_sha256!=record['policy_sha256'] or actual!=policy or
            Path(admitted._config_path)!=location.resolve(strict=True)): raise HostSetupError()
        report,_=admit_inventory(value)  # Fresh registry + metadata points at host start.
        return admitted,report
    except (OSError,RuntimeError,TypeError,ValueError,UnicodeError,subprocess.SubprocessError):
        raise HostSetupError()from None

