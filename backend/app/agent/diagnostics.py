"""Retain a diagnostic before log compaction; do not infer whether an RTL or a
test expectation is wrong from a simulator assertion alone.
"""

from collections.abc import Mapping
import json
import math
import re

from pydantic import JsonValue


def prefix(text: str, byte_limit: int) -> str:
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= byte_limit:
        return raw.decode("utf-8")
    suffix = " [truncated]"
    if byte_limit < len(suffix):
        return raw[:max(0, byte_limit)].decode("utf-8", errors="ignore")
    return raw[:max(0, byte_limit - len(suffix))].decode("utf-8", errors="ignore") + suffix


def _item(value: object, kind: str) -> dict[str, JsonValue] | None:
    if isinstance(value, str) and value.strip():
        return {"kind": kind, "message": prefix(value.strip(), 1400)}
    if not isinstance(value, Mapping):
        return None
    message = value.get("message") or value.get("error")
    if not isinstance(message, str) or not message.strip():
        return None
    found: dict[str, JsonValue] = {"kind": kind, "message": prefix(message.strip(), 1400)}
    for key in ("test", "phase", "signal"):
        if isinstance(value.get(key), str):
            found[key] = prefix(value[key], 200)
    for key in ("cycle", "expected", "actual"):
        entry = value.get(key)
        if type(entry) is int:
            # Values are still bounded if a malformed producer returns a giant int.
            found[key] = entry if entry.bit_length() <= 1024 else f"<integer with {entry.bit_length()} bits>"
        elif isinstance(entry, str):
            found[key] = prefix(entry, 350)
    return found


def _fatal_log_diagnostic(result: Mapping[str, object]) -> dict[str, JsonValue] | None:
    if result.get("ok") is not False or not isinstance(result.get("log_tail"), str):
        return None
    for line in result["log_tail"].splitlines():
        if re.search(r"\[(?:WARN|WARNING)(?:\s|\])", line, re.I):
            continue
        # Bare codes are supported only by the two captured real error.log files.
        # An arbitrary bracketed code can be a warning (notably GPL-0302).
        if (re.search(r"\[ERROR\s+[A-Z][A-Z0-9_]*-\d+\]", line)
                or re.search(r"\[(?:DPL-0036|GPL-0301)\]", line)
                or re.match(r"\s*%Error(?:-[A-Z0-9_]+)?:", line)
                or re.match(r"\s*ERROR:\s*\S", line)
                or re.match(r"\s*(?:AssertionError|ValueError|TypeError|ImportError|ModuleNotFoundError|"
                            r"SyntaxError|RuntimeError|NameError|AttributeError|KeyError|IndexError):(?:\s|$)", line)):
            return _item(line, "tool_error")
    return None


def _generic_exit(message: object) -> bool:
    return isinstance(message, str) and re.fullmatch(
        r"(?:Tool|Flow|Process|Command|Simulator) exited with code -?\d+\.?", message.strip()) is not None


def first_diagnostic(result: Mapping[str, object]) -> dict[str, JsonValue] | None:
    for key in ("first_diagnostic", "diagnostic"):
        structured = result.get(key)
        if isinstance(structured, Mapping):
            kind = structured.get("kind")
            if isinstance(kind, str) and kind in {"functional_assertion", "harness_error", "infrastructure_error", "test_failure", "tool_error"}:
                found = _item(structured, kind)
                if found:
                    return found
    cases = result.get("cases")
    if isinstance(cases, list):
        for case in cases:
            if isinstance(case, Mapping) and case.get("ok") is False:
                found = _item(case, "test_failure")
                if found:
                    return found
    for key, kind in (("failures", "test_failure"), ("errors", "tool_error")):
        values = result.get(key)
        if isinstance(values, list):
            for value in values[:100]:
                found = _item(value, kind)
                if found:
                    return found
    fatal = _fatal_log_diagnostic(result)
    for key in ("first_error", "error"):
        found = _item(result.get(key), "tool_error")
        if found:
            return fatal if fatal is not None and _generic_exit(found["message"]) else found
    if fatal is not None:
        return fatal
    if result.get("ok") is not False:
        return None
    tail = result.get("log_tail")
    if isinstance(tail, str) and tail.strip():
        lines = [line for line in tail.splitlines()
                 if not re.search(r"\[(?:WARN|WARNING)(?:\s|\])", line, re.I)]
        return _item("\n".join(lines)[-1400:], "tool_error")
    return None


def diagnostic_text(diagnostic: Mapping[str, object]) -> str:
    message = diagnostic.get("message")
    if not isinstance(message, str):
        return ""
    test = diagnostic.get("test")
    return prefix((f"{test}: " if isinstance(test, str) and test else "") + message, 1800)


def bounded_result(result: dict[str, JsonValue], limit: int = 8192) -> dict[str, JsonValue]:
    """Keep the first failure/counts before spending space on log excerpts."""
    def size(value: object) -> int:
        try:
            return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError, OverflowError, UnicodeError):
            return limit + 1

    diagnostic = first_diagnostic(result)
    enriched = dict(result)
    if diagnostic is not None:
        enriched["first_diagnostic"] = diagnostic
        enriched["first_error"] = prefix(diagnostic_text(diagnostic), 700)
    if size(enriched) <= limit:
        return enriched
    keys = (
        "ok", "bytes", "passed", "failed", "skipped", "cell_count", "area_estimate",
        "run_tag", "drc_ok", "lvs_ok", "image_url", "best_run_tag", "metrics",
        "log_path", "results_path", "stats_path", "evidence_path", "proof_path",
        "harness_evidence_valid", "quality_gate_passed", "mode", "helper_sha256",
        "context_sha256", "error_kind", "gls_ok", "gate_level", "signoff_checks", "drv_ok",
        "tool_evidence", "planned_config_overrides", "physical_flow_started", "physical_plan",
        "sizing_plan", "suggested_action", "footprint_policy", "mapping_cache_key", "mapping_reused",
    )
    compact = {key: enriched[key] for key in keys if key in enriched}
    compact["summary"] = "Output truncated; full artifacts remain on disk."
    if diagnostic is not None:
        compact["first_diagnostic"] = diagnostic
        compact["first_error"] = prefix(diagnostic_text(diagnostic), 700)
    if isinstance(result.get("error"), str):
        compact["error"] = prefix(result["error"], 600)
    # Unexpected metadata must fail closed without replacing genuine numbers.
    if size(compact) > limit:
        reserved = (
            "passed", "failed", "skipped", "cell_count", "run_tag", "drc_ok", "lvs_ok",
            "log_path", "results_path", "stats_path", "evidence_path", "proof_path",
            "harness_evidence_valid", "quality_gate_passed", "mode", "helper_sha256",
            "context_sha256", "error_kind", "gls_ok", "drv_ok",
        )
        compact = {}
        omitted = []
        for key in reserved:
            if key not in enriched:
                continue
            value = enriched[key]
            valid = value is None or type(value) is bool
            valid = valid or (type(value) is int and value.bit_length() <= 1024)
            valid = valid or (type(value) is float and math.isfinite(value))
            if isinstance(value, str):
                try:
                    valid = len(value.encode("utf-8")) <= 1024
                except UnicodeError:
                    valid = False
            if valid:
                compact[key] = value
            else:
                omitted.append(key)
        if omitted:
            compact["metadata_omitted"] = omitted
        compact.update(ok=False, summary="Structured metadata exceeded output cap; full artifacts remain on disk.")
        if diagnostic is not None:
            compact["first_diagnostic"] = diagnostic
            compact["first_error"] = prefix(diagnostic_text(diagnostic), 700)
        if size(compact) > limit:
            # A caller-selected tiny limit is unsupported, never silently exceeded.
            raise ValueError("Output cap is too small to preserve the failure envelope")
        return compact
    cases = result.get("cases")
    if isinstance(cases, list):
        kept: list[JsonValue] = []
        candidate = {**compact, "cases": kept, "cases_omitted": len(cases)}
        if size(candidate) > limit:
            return compact
        compact = candidate
        for value in cases[:100]:
            if not isinstance(value, dict):
                break
            case: dict[str, JsonValue] = {"test": prefix(str(value.get("test", "unknown")), 200),
                                         "ok": value.get("ok")}
            if isinstance(value.get("message"), str):
                case["message"] = prefix(value["message"], 250)
            kept.append(case)
            compact["cases_omitted"] = len(cases) - len(kept)
            if size(compact) > limit:
                kept.pop()
                compact["cases_omitted"] = len(cases) - len(kept)
                break
    # Add one useful bulk field, allocating the envelope first. Binary search
    # accounts for JSON escapes rather than assuming a character costs one byte.
    for key in ("content", "diff", "text", "log_tail"):
        value = result.get(key)
        if not isinstance(value, str):
            continue
        raw = value.encode("utf-8", errors="replace")
        low, high = 0, min(len(raw), limit)
        while low < high:
            middle = (low + high + 1) // 2
            excerpt = raw[-middle:].decode("utf-8", errors="ignore") if middle else ""
            compact[key] = excerpt
            if size(compact) <= limit:
                low = middle
            else:
                high = middle - 1
        compact[key] = raw[-low:].decode("utf-8", errors="ignore") if low else ""
        if size(compact) > limit:
            compact.pop(key)
        break
    return compact
