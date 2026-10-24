"""Allowlisted public request configuration. Never inspect credentials or env."""
import hashlib
from pathlib import Path

from app.observability.trace import canonical


def public_configuration(llm, provider: str) -> dict:
    if provider not in {"codex", "meta", "fake"}:
        raise ValueError("Explicit configured provider required")
    root = Path(__file__).resolve().parents[1]
    paths = ("llm/types.py", "llm/policy.py", "agent/prompts.py", "agent/scope_prompts.py", "schemas.py",
             "observability/observer.py", "observability/trace.py",
             "llm/client.py" if provider == "meta" else "llm/codex.py")
    sources = {}
    for name in paths:
        raw = (root / name).read_bytes()
        if len(raw) > 1024 * 1024:
            raise ValueError("Public configuration source exceeds bounded size")
        sources[name] = hashlib.sha256(raw).hexdigest()
    budget = getattr(llm, "budget", None)
    result = {"schema_version": 1, "provider": provider, "sources": sources,
              "limits": {name: getattr(budget, name, None) for name in ("max_calls", "max_tokens", "max_usd")}}
    canonical(result)  # Strict finite public primitives only, no object repr.
    return result
