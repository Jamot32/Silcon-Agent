"""Exercise the actual macOS policy compiler and kernel read-deny rules."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.llm.read_boundary import CodexReadBoundary, SANDBOX_EXEC


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "darwin", reason="Requires real macOS sandbox-exec")
def test_real_sandbox_denies_protected_env_and_allows_unprotected_file(tmp_path):
    protected = tmp_path / "project"
    protected.mkdir()
    secret = protected / ".env"
    secret.write_text("SYNTHETIC_SECRET=must-stay-private\n")
    allowed = tmp_path / "public.txt"
    allowed.write_text("Readable outside protected roots\n")
    private_cwd = tmp_path / "empty"
    private_cwd.mkdir(mode=0o700)
    boundary = CodexReadBoundary(str(protected), (), str(private_cwd),
        hashlib.sha256(Path(SANDBOX_EXEC).read_bytes()).hexdigest())

    def cat(path):
        plan = boundary.command(("/bin/cat", str(path)))
        return subprocess.run(plan.argv, cwd=plan.cwd, capture_output=True,
            env={**os.environ, "LC_ALL": "C"}, close_fds=plan.close_fds,
            start_new_session=plan.start_new_session, timeout=10)

    denied = cat(secret)
    assert denied.returncode != 0
    assert denied.stdout == b""
    assert b"Operation not permitted" in denied.stderr  # EPERM, not a missing path.
    permitted = cat(allowed)
    assert permitted.returncode == 0, permitted.stderr
    assert permitted.stdout == allowed.read_bytes()
