#!/usr/bin/env python3
"""Provision a local worker credential without printing or replacing user keys."""

from pathlib import Path
import secrets

def ensure_worker_token(path: Path) -> None:
    lines = path.read_text().splitlines()
    found = False
    for index, line in enumerate(lines):
        if line.startswith("WORKER_TOKEN="):
            found = True
            if len(line.split("=", 1)[1].strip().strip("\"'")) < 32:
                lines[index] = "WORKER_TOKEN=" + secrets.token_hex(32)
            break
    if not found:
        lines.append("WORKER_TOKEN=" + secrets.token_hex(32))
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


if __name__ == "__main__":
    ensure_worker_token(Path(__file__).resolve().parents[1] / ".env")
