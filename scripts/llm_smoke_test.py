#!/usr/bin/env python3
"""Verify one non-streaming Muse Spark tool call without exposing credentials.

Docs checked: https://dev.meta.ai/docs/tool-calling (2026-10-23).
Install: python -m pip install -r scripts/requirements-smoke.txt
Run: python scripts/llm_smoke_test.py (uses Settings or META_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Literal, cast

# The same helper is available at backend/app on the host and /app/app in the API image.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" if (ROOT / "backend/app").is_dir() else ROOT / "app"))
from app.provider_credentials import effective_key

ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]


def parse_add_call(name: str, arguments: str) -> dict[str, int]:
    if name != "add":
        raise ValueError("Expected an add tool call.")
    parsed = json.loads(arguments)
    if not isinstance(parsed, dict) or set(parsed) != {"a", "b"}:
        raise ValueError("Expected exactly the arguments a and b.")
    if any(type(parsed[key]) is not int for key in ("a", "b")):
        raise ValueError("Tool arguments must be integers.")
    if parsed != {"a": 2, "b": 3}:
        raise ValueError("Expected add(a=2, b=3).")
    return parsed


def self_test() -> None:
    assert parse_add_call("add", '{"a":2,"b":3}') == {"a": 2, "b": 3}
    for name, arguments in (
        ("subtract", '{"a":2,"b":3}'),
        ("add", '{"a":true,"b":3}'),
        ("add", '{"a":2}'),
        ("add", '{"a":2,"b":3,"extra":1}'),
        ("add", '{"a":2,"b":4}'),
        ("add", "not-json"),
    ):
        try:
            parse_add_call(name, arguments)
        except ValueError:
            continue
        raise AssertionError("Invalid tool call was accepted.")
    print("PASS: add tool-call parser self-check (no API request).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Check parsing offline.")
    if parser.parse_args().self_test:
        self_test()
        return 0

    try:
        api_key = effective_key(Path(os.getenv("RUNS_DIR", str(ROOT / "runs"))), "meta")
    except OSError:
        print("BLOCKED: Meta key storage is unavailable; no API request made.", file=sys.stderr)
        return 2
    if not api_key:
        print("BLOCKED: Add a Meta key in Settings or set META_API_KEY; no API request made.", file=sys.stderr)
        return 2
    effort = os.getenv("META_REASONING_EFFORT", "medium")
    if effort not in ("minimal", "low", "medium", "high", "xhigh"):
        print("ERROR: Invalid META_REASONING_EFFORT.", file=sys.stderr)
        return 2

    try:
        from openai import APIError, APIStatusError, OpenAI
    except ImportError:
        print("ERROR: Install scripts/requirements-smoke.txt first.", file=sys.stderr)
        return 2

    try:
        with OpenAI(
            api_key=api_key,
            base_url=os.getenv("META_BASE_URL", "https://api.meta.ai/v1"),
            timeout=60.0,
            max_retries=0,
        ) as client:
            completion = client.chat.completions.create(
                model=os.getenv("META_MODEL", "muse-spark-1.3"),
                messages=[{"role": "user", "content": "Call add with a=2 and b=3."}],
                tools=[{
                    "type": "function",
                    "function": {
                        "name": "add",
                        "description": "Add two integers.",
                        "strict": True,
                        "parameters": {
                            "type": "object",
                            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                            "required": ["a", "b"],
                            "additionalProperties": False,
                        },
                    },
                }],
                # Meta currently supports only auto; required/named choices return 400.
                tool_choice="auto",
                parallel_tool_calls=False,
                reasoning_effort=cast(ReasoningEffort, effort),
                max_completion_tokens=1024,
            )
        if not completion.choices:
            raise ValueError("The API returned no choices.")
        calls = completion.choices[0].message.tool_calls or []
        if len(calls) != 1 or calls[0].type != "function":
            raise ValueError("Expected one function tool call; the API returned another response.")
        arguments = parse_add_call(calls[0].function.name, calls[0].function.arguments)
        print(json.dumps({
            "model": completion.model,
            "tool_call": {"name": "add", "arguments": arguments},
            "result": arguments["a"] + arguments["b"],
            "usage": completion.usage.model_dump() if completion.usage else None,
        }, indent=2))
    except APIStatusError as error:
        print(f"FAIL: Meta API returned HTTP {error.status_code}.", file=sys.stderr)
        return 1
    except APIError as error:
        print(f"FAIL: Meta API request failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
