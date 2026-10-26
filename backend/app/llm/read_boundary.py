"""Unqualified external launch-plan builder; this module never starts a process.

Host configuration supplies roots, never request/spec text. Preserve the actual
Codex argv (including its inner read-only/native-disable settings) verbatim.
The adapter must use close_fds=True and only host-owned stdin/stdout/stderr pipes.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import stat
import sys

SANDBOX_EXEC = '/usr/bin/sandbox-exec'
MAX_ROOTS = 16
MAX_PATH_BYTES = 4096

class PlanError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__('Outer read-deny plan rejected: '+code)

def canonical_directory(value):
    if (type(value) is not str or not value.startswith('/') or
        any(ord(char)<32 or ord(char)==127 for char in value) or
        any(part in ('.','..') for part in value.split('/'))):
        raise PlanError('absolute_directory')
    try:
        if len(value.encode('utf-8'))>MAX_PATH_BYTES:raise PlanError('path_size')
        path=Path(value).resolve(strict=True)
        info=path.stat()
    except (OSError,RuntimeError,UnicodeError) as error:
        raise PlanError('directory_resolution') from error
    if not stat.S_ISDIR(info.st_mode):raise PlanError('directory_type')
    # Reject broad bootstrap/auth/system roots; caller still owns project identity.
    if path in {Path('/'),Path('/Users'),Path.home(),Path('/System'),Path('/Library'),
                Path('/Applications'),Path('/usr'),Path('/bin'),Path('/sbin'),
                Path('/dev'),Path('/private'),Path('/private/tmp')}:
        raise PlanError('overbroad_root')
    return str(path)

@dataclass(frozen=True)
class LaunchPlan:
    argv: tuple
    cwd: str
    protected_roots: tuple
    policy: str
    close_fds: bool = True
    start_new_session: bool = True

    def metadata(self):
        """No auth/env/CLI payload values are emitted by this metadata method."""
        return {'schema_version':1,'kind':'unqualified_outer_Codex_read_deny_launch_plan',
                'protected_roots':list(self.protected_roots),
                'policy_sha256':hashlib.sha256(self.policy.encode()).hexdigest(),
                'argv_sha256':hashlib.sha256(json.dumps(self.argv,separators=(',',':')).encode()).hexdigest(),
                'close_fds':True,'start_new_session':True,
                'actual_sandbox_or_CLI_executed':False,'whole_harness_read_isolation_qualified':False}

def build_launch(cli_argv, *, original_project_root, worktree_roots, cwd,
                 additional_archive_roots=(), platform=None):
    """Build only; required project/worktree roots cannot be inferred from archive.

    Future use: subprocess.Popen(plan.argv, cwd=plan.cwd, env=unchanged_env,
      stdin=PIPE, stdout=PIPE, stderr=PIPE, close_fds=True, start_new_session=True).
    Do not pass corpus FDs, pass_fds, preexec_fn, shell=True or inherited file stdio.
    Run existing owned-group cancellation/reap logic unchanged around that Popen.
    """
    if (sys.platform if platform is None else platform)!='darwin':
        raise PlanError('unsupported_platform')
    if (type(cli_argv) not in (list,tuple) or not 1<=len(cli_argv)<=256 or
        any(type(arg) is not str or '\x00' in arg for arg in cli_argv) or
        not Path(cli_argv[0]).is_absolute()):raise PlanError('cli_argv')
    if (type(worktree_roots) not in (list,tuple) or
        type(additional_archive_roots) not in (list,tuple) or
        1+len(worktree_roots)+len(additional_archive_roots)>MAX_ROOTS):
        raise PlanError('host_root_roster')
    # Resolve directory metadata only. No traversal or content reads occur.
    project=canonical_directory(original_project_root)
    worktrees=tuple(canonical_directory(value) for value in worktree_roots)
    roots=tuple(dict.fromkeys((project,*worktrees,*(canonical_directory(value)
                for value in additional_archive_roots))))
    current=canonical_directory(cwd)
    if any(Path(current).is_relative_to(Path(root)) for root in roots):
        raise PlanError('cwd_inside_protected_root')
    # The policy contains fixed tokens only. Paths are separate argv parameters,
    # so quotes, backslashes, Unicode and Scheme-looking names cannot inject SBPL.
    policy='(version 1)\n(allow default)\n'+''.join(
        '(deny file-read* file-write* (subpath (param "SA_PROTECTED_'+str(index)+'")))\n'
        for index in range(len(roots)))
    definitions=tuple('-DSA_PROTECTED_'+str(index)+'='+root for index,root in enumerate(roots))
    # Prevent moving an ancestor and reopening the formerly denied subtree under
    # a new name. These are literal directory-unlink guards, not ancestor reads.
    ancestors=tuple(sorted({str(parent) for root in roots for parent in Path(root).parents}))
    if len(ancestors)>128:raise PlanError('ancestor_count')
    policy+=''.join('(deny file-write-unlink (require-all (vnode-type DIRECTORY) '
                    '(literal (param "SA_ANCESTOR_'+str(index)+'"))))\n'
                    for index in range(len(ancestors)))
    definitions+=tuple('-DSA_ANCESTOR_'+str(index)+'='+root for index,root in enumerate(ancestors))
    argv=(SANDBOX_EXEC,'-p',policy,*definitions,'--',*cli_argv)
    return LaunchPlan(argv,current,roots,policy)


# Production-shaped composition draft; earlier OS/probe evidence is separate.
from dataclasses import field
import os

class ReadBoundaryError(ValueError):
    def __init__(self):
        self.code = "invalid_read_boundary"
        super().__init__("Codex protected-root configuration is unavailable or invalid.")


def _directory_identity(path):
    info = Path(path).stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ReadBoundaryError()
    return (info.st_dev, info.st_ino)


@dataclass(frozen=True)
class CodexReadBoundary:
    original_project_root: str
    worktree_roots: tuple
    private_cwd: str
    sandbox_exec_sha256: str
    additional_archive_roots: tuple = ()
    _root_identities: tuple = field(init=False, repr=False)
    _cwd_identity: tuple = field(init=False, repr=False)
    _policy_sha256: str = field(init=False, repr=False)

    def __post_init__(self):
        try:
            plan = build_launch(("/usr/bin/true",),
                original_project_root=self.original_project_root,
                worktree_roots=self.worktree_roots,
                additional_archive_roots=self.additional_archive_roots,
                cwd=self.private_cwd)
            if (type(self.sandbox_exec_sha256) is not str or
                len(self.sandbox_exec_sha256) != 64 or
                any(c not in "0123456789abcdef" for c in self.sandbox_exec_sha256)):
                raise ReadBoundaryError()
            object.__setattr__(self, "original_project_root", plan.protected_roots[0])
            object.__setattr__(self, "worktree_roots", tuple(canonical_directory(p) for p in self.worktree_roots))
            object.__setattr__(self, "additional_archive_roots", tuple(canonical_directory(p) for p in self.additional_archive_roots))
            object.__setattr__(self, "private_cwd", plan.cwd)
            object.__setattr__(self, "_root_identities", tuple(_directory_identity(p) for p in plan.protected_roots))
            object.__setattr__(self, "_cwd_identity", _directory_identity(plan.cwd))
            object.__setattr__(self, "_policy_sha256", hashlib.sha256(plan.policy.encode()).hexdigest())
            self.command(("/usr/bin/true",))
        except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
            raise ReadBoundaryError() from None

    def command(self, cli_argv):
        try:
            plan = build_launch(cli_argv,
                original_project_root=self.original_project_root,
                worktree_roots=self.worktree_roots,
                additional_archive_roots=self.additional_archive_roots,
                cwd=self.private_cwd)
            if (tuple(_directory_identity(p) for p in plan.protected_roots) != self._root_identities or
                _directory_identity(plan.cwd) != self._cwd_identity or
                hashlib.sha256(plan.policy.encode()).hexdigest() != self._policy_sha256):
                raise ReadBoundaryError()
            cwd = Path(plan.cwd)
            info = cwd.stat()
            if (stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid() or
                any(cwd.iterdir())):
                raise ReadBoundaryError()
            binary = Path(SANDBOX_EXEC)
            before = binary.lstat()
            if (not stat.S_ISREG(before.st_mode) or not before.st_mode & 0o111 or
                before.st_mode & 0o022 or not 0 < before.st_size <= 32 * 1024 * 1024):
                raise ReadBoundaryError()
            raw = binary.read_bytes()
            after = binary.lstat()
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode", "st_nlink")
            if (any(getattr(before, p) != getattr(after, p) for p in fields) or
                len(raw) != before.st_size or hashlib.sha256(raw).hexdigest() != self.sandbox_exec_sha256):
                raise ReadBoundaryError()
            return plan
        except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
            raise ReadBoundaryError() from None

    def metadata(self, cli_argv):
        plan = self.command(cli_argv)
        encode = lambda value: json.dumps(value, separators=(",", ":")).encode()
        return {"kind": "unqualified_production_Codex_read_boundary",
            "root_count": len(plan.protected_roots),
            "roster_sha256": hashlib.sha256(encode(plan.protected_roots)).hexdigest(),
            "policy_sha256": self._policy_sha256,
            "sandbox_exec_sha256": self.sandbox_exec_sha256,
            "inner_argv_sha256": hashlib.sha256(encode(tuple(cli_argv))).hexdigest(),
            "wrapped_argv_sha256": hashlib.sha256(encode(plan.argv)).hexdigest(),
            "close_fds": True, "start_new_session": True,
            "whole_production_read_isolation_qualified": False}


from contextlib import contextmanager
import shutil
import tempfile


def _owned_directory(path):
    info = path.stat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or
        info.st_uid != os.getuid()):
        raise ReadBoundaryError()
    return (info.st_dev, info.st_ino)


def _config_bytes(path):
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
        stat.S_IMODE(before.st_mode) != 0o600 or before.st_uid != os.getuid() or
        not 0 < before.st_size <= 16384):
        raise ReadBoundaryError()
    _owned_directory(path.parent)
    raw = path.read_bytes()
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode", "st_nlink", "st_uid")
    if len(raw) != before.st_size or any(getattr(before,p) != getattr(after,p) for p in fields):
        raise ReadBoundaryError()
    return raw


@dataclass(frozen=True)
class CodexLaunchPolicy:
    original_project_root: str
    worktree_roots: tuple
    additional_archive_roots: tuple
    private_cwd_parent: str
    sandbox_exec_sha256: str
    _config_path: str
    _config_sha256: str
    _parent_identity: tuple
    _root_identities: tuple

    @classmethod
    def from_file(cls, path, *, run_work_dir):
        try:
            if type(path) is not str or not Path(path).is_absolute():
                raise ReadBoundaryError()
            location = Path(path)
            raw = _config_bytes(location)
            location = location.resolve(strict=True)
            def unique(pairs):
                result = {}
                for key,value in pairs:
                    if key in result:
                        raise ReadBoundaryError()
                    result[key] = value
                return result
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                parse_constant=lambda value: (_ for _ in ()).throw(ReadBoundaryError()))
            fields = {"schema_version", "original_project_root", "worktree_roots",
                "additional_archive_roots", "private_cwd_parent", "sandbox_exec_sha256"}
            if type(data) is not dict or set(data) != fields or type(data["schema_version"]) is not int or data["schema_version"] != 1:
                raise ReadBoundaryError()
            plan = build_launch(("/usr/bin/true",), original_project_root=data["original_project_root"],
                worktree_roots=data["worktree_roots"], additional_archive_roots=data["additional_archive_roots"],
                cwd=data["private_cwd_parent"])
            run = Path(canonical_directory(str(run_work_dir)))
            parent = Path(plan.cwd)
            roots = tuple(Path(p) for p in plan.protected_roots)
            if (not any(run.is_relative_to(p) for p in roots) or
                any(location.is_relative_to(p) for p in roots) or
                location.is_relative_to(run) or parent.is_relative_to(run)):
                raise ReadBoundaryError()
            digest = data["sandbox_exec_sha256"]
            if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ReadBoundaryError()
            return cls(plan.protected_roots[0], tuple(canonical_directory(p) for p in data["worktree_roots"]),
                tuple(canonical_directory(p) for p in data["additional_archive_roots"]), plan.cwd, digest,
                str(location), hashlib.sha256(raw).hexdigest(), _owned_directory(parent),
                tuple(_directory_identity(p) for p in roots))
        except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
            raise ReadBoundaryError() from None

    @contextmanager
    def open_boundary(self):
        owned = None
        identity = None
        primary = None
        try:
            try:
                if hashlib.sha256(_config_bytes(Path(self._config_path))).hexdigest() != self._config_sha256:
                    raise ReadBoundaryError()
                if _owned_directory(Path(self.private_cwd_parent)) != self._parent_identity:
                    raise ReadBoundaryError()
                plan = build_launch(("/usr/bin/true",), original_project_root=self.original_project_root,
                    worktree_roots=self.worktree_roots, additional_archive_roots=self.additional_archive_roots,
                    cwd=self.private_cwd_parent)
                if tuple(_directory_identity(p) for p in plan.protected_roots) != self._root_identities:
                    raise ReadBoundaryError()
                owned = Path(tempfile.mkdtemp(prefix="codex-empty-", dir=self.private_cwd_parent))
                identity = _owned_directory(owned)
                active = CodexReadBoundary(self.original_project_root, self.worktree_roots, str(owned),
                    self.sandbox_exec_sha256, self.additional_archive_roots)
            except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
                raise ReadBoundaryError() from None
            yield active
        except BaseException as error:
            primary = error
            raise
        finally:
            if owned is not None:
                try:
                    if owned.is_symlink() or _owned_directory(owned) != identity:
                        raise ReadBoundaryError()
                    shutil.rmtree(owned)
                except BaseException as error:
                    if primary is None:
                        raise ReadBoundaryError() from None
                    try:
                        primary.add_note("Codex private-cwd cleanup incomplete: " + type(error).__name__)
                    except BaseException:
                        pass
