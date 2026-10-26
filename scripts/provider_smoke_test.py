#!/usr/bin/env python3
"""Run the explicitly selected provider smoke without silent fallbacks."""

import os
import sys


def main() -> int:
    provider = os.getenv("LLM_PROVIDER", "codex")
    if provider == "codex":
        from guarded_codex_smoke import main as smoke
    elif provider == "meta":
        from llm_smoke_test import main as smoke
    else:
        print("ERROR: LLM_PROVIDER must be codex or meta.", file=sys.stderr)
        return 2
    return smoke()


if __name__ == "__main__":
    raise SystemExit(main())
