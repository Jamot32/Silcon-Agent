"""Host-only CLI probes; persist only an enum, never CLI output or account tokens."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
from time import time
from typing import Literal

from pydantic import BaseModel, ConfigDict

Status = Literal["connected", "signed_out", "api_key", "unavailable", "unknown"]


class SubscriptionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codex: Status = "unknown"
    claude: Status = "unknown"
    checked_at: float = 0


def probe_subscription(provider: Literal["codex", "claude"]) -> Status:
    command = ["codex", "login", "status"] if provider == "codex" else ["claude", "auth", "status"]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, check=False)
    except FileNotFoundError:
        return "unavailable"
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return "unknown"
    if provider == "codex":
        # Codex's status command writes its fixed status message to stderr.
        output = (result.stdout + result.stderr).strip().lower()
        if result.returncode == 0 and "logged in using chatgpt" in output:
            return "connected"
        if result.returncode == 0 and "api key" in output:
            return "api_key"
        return "signed_out" if "not logged in" in output else "unknown"
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            return "unknown"
        if value.get("loggedIn") is False:
            return "signed_out"
        if result.returncode == 0 and value.get("loggedIn") is True:
            if value.get("authMethod") == "claude.ai":
                return "connected"
            if value.get("authMethod") in {"api_key", "api_key_helper"}:
                return "api_key"
    except ValueError:
        pass
    return "unknown"


def refresh_subscriptions(root: Path) -> None:
    status = SubscriptionStatus(codex=probe_subscription("codex"), claude=probe_subscription("claude"), checked_at=time())
    descriptor, temporary = tempfile.mkstemp(dir=root)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(status.model_dump_json())
        os.replace(temporary, root / ".subscription-status.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_subscriptions(root: Path) -> SubscriptionStatus:
    try:
        status = SubscriptionStatus.model_validate_json((root / ".subscription-status.json").read_text())
        if 0 <= time() - status.checked_at < 90:
            return status
    except (OSError, ValueError):
        pass
    return SubscriptionStatus()
