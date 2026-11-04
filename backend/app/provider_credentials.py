"""Server-only BYOK storage. OAuth is owned by the host CLIs, never this store."""

import os
from pathlib import Path
import tempfile

PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY", "meta": "META_API_KEY", "kimi": "MOONSHOT_API_KEY",
    "qwen": "DASHSCOPE_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "xai": "XAI_API_KEY",
    "mistral": "MISTRAL_API_KEY", "zai": "ZAI_API_KEY", "minimax": "MINIMAX_API_KEY",
}


def key_path(root: Path, provider: str) -> Path:
    if provider not in PROVIDER_ENV:
        raise ValueError("Unknown provider")
    return root / ".provider-keys" / f"{provider}.key"


def saved_key(root: Path, provider: str) -> str:
    try:
        return key_path(root, provider).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except UnicodeError:
        # Corrupt storage must fail closed through the same sanitized path as an unreadable file.
        raise OSError("Provider key file is not valid text") from None


def effective_key(root: Path, provider: str) -> str:
    return saved_key(root, provider) or os.getenv(PROVIDER_ENV[provider], "").strip()


def save_key(root: Path, provider: str, key: str) -> None:
    path = key_path(root, provider)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(key)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def remove_key(root: Path, provider: str) -> None:
    key_path(root, provider).unlink(missing_ok=True)
