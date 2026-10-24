"""Bounded private trace writer. Payloads contain projected metadata, never bodies."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from threading import Lock
from datetime import datetime,timezone

MAX_RECORD_BYTES=16*1024
MAX_TRACE_BYTES=16*1024*1024
KINDS={'state_transition','llm_call','tool_call','command_finished','run_finished'}
STAGE=re.compile(r'[A-Z][A-Z_]{0,31}\Z')
RUN_ID=re.compile(r'[a-f0-9]{32}\Z')


def canonical(value):
    def valid(item):
        if item is None or type(item) in (str,bool,int):return
        if type(item) is float and math.isfinite(item):return
        if type(item) is list:
            for child in item:valid(child)
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():valid(child)
            return
        raise ValueError('Trace payload must contain finite JSON values')
    valid(value)
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def prompt_hash(messages,tools):
    return hashlib.sha256(canonical({'messages':messages,'tools':tools})).hexdigest()


def tool_arguments(name,args):
    # Exact source bytes already have a retained file/diff artifact. A hash keeps
    # repeated code from dominating the append-only trace; never log env/auth.
    normalized=json.loads(canonical(args))
    if name=='write_file' and isinstance(normalized,dict) and type(normalized.get('content')) is str:
        raw=normalized.pop('content').encode()
        normalized['content_artifact']={'path':normalized.get('path'),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    return normalized


def usage_delta(before,after):
    names=('calls','input_tokens','output_tokens')
    if any(type(x.get(k)) is not int or x[k]<0 for x in (before,after) for k in names):
        raise ValueError('Usage counters must be nonnegative integers')
    delta={k:after[k]-before[k] for k in names}
    if any(v<0 for v in delta.values()):raise ValueError('Usage counters cannot go backwards')
    a,b=before.get('cost_usd'),after.get('cost_usd')
    if a is None or b is None:delta['cost_usd']=None
    else:
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in (a,b)) or b<a:
            raise ValueError('Known cost counters must be finite and monotone')
        delta['cost_usd']=b-a
    return delta


class TraceWriter:
    """One per run, new files only; lifecycle/terminal recovery is caller-owned.

    directory is an already-authorized host-owned work directory. The model
    cannot select this path. Opens reject symlink work dirs/files and use dir_fd.
    No contents, credentials or environment are discovered by this module.
    """
    def __init__(self,directory:Path,run_id:str,*,now=None):
        if type(run_id) is not str or not RUN_ID.fullmatch(run_id):raise ValueError('Invalid run ID')
        self._fd=None;self._seq=0;self._bytes=0;self._lock=Lock();self._run_id=run_id
        self._now=now or (lambda:datetime.now(timezone.utc))
        parent=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            descriptor=os.open('trace.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_APPEND|os.O_NOFOLLOW,0o600,dir_fd=parent)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode) or os.fstat(descriptor).st_nlink!=1:
                os.close(descriptor);raise ValueError('Trace must be a regular file')
            try:
                os.fchmod(descriptor,0o600)
                os.fsync(descriptor)
                os.fsync(parent)
                self._fd=descriptor
            except BaseException:
                os.close(descriptor);raise
        finally:os.close(parent)

    def append(self,kind,stage,payload):
        if kind not in KINDS or type(stage) is not str or not STAGE.fullmatch(stage):
            raise ValueError('Invalid trace type or stage')
        if type(payload) is not dict:raise ValueError('Trace payload must be an object')
        with self._lock:
            if self._fd is None:raise ValueError('Trace is closed')
            instant=self._now()
            if not isinstance(instant,datetime) or instant.utcoffset() is None:raise ValueError('Trace clock must be timezone-aware')
            record={'schema_version':1,'run_id':self._run_id,'sequence':self._seq+1,
                    'ts':instant.astimezone(timezone.utc).isoformat(),'type':kind,'stage':stage,'payload':payload}
            raw=canonical(record)+b'\n'
            if len(raw)>MAX_RECORD_BYTES:raise ValueError('Trace record exceeds bounded size')
            if self._bytes+len(raw)>MAX_TRACE_BYTES:raise ValueError('Trace exceeds run size bound')
            # Poison the writer on uncertain writes; never append a success
            # record after a partial line or failed durability acknowledgement.
            try:
                if os.write(self._fd,raw)!=len(raw):raise OSError('Incomplete trace write')
                os.fsync(self._fd)
            except BaseException as primary:
                descriptor,self._fd=self._fd,None  # Poison before fallible cleanup.
                try:os.close(descriptor)
                except BaseException:
                    primary.add_note('Trace cleanup also failed after uncertain write')
                raise
            self._seq+=1
            self._bytes+=len(raw)
            return record

    def close(self):
        with self._lock:
            if self._fd is not None:
                descriptor,self._fd=self._fd,None
                os.close(descriptor)

    def __enter__(self):return self
    def __exit__(self,kind,primary,traceback):
        try:self.close()
        except BaseException:
            if primary is None:raise
            primary.add_note('Trace close failed during primary exception')
