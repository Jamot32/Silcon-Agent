"""Inspect closed neutral artifacts only; no simulator or network invocation."""
import json
import clock_proof
from test_clock_proof import EVIDENCE, REPORT, identity

out = EVIDENCE / "recorded-proof-check.json"
positive = None
mutants = {}
for name in ("good", "missing_reset", "late_update"):
    receipt = REPORT["scenarios"][name]["simulation"]
    try:
        captured = clock_proof.capture(EVIDENCE / name, receipt, identity(name))
    except (OSError, ValueError) as error:
        if name == "good":
            raise
        mutants[name] = {"accepted": False, "reason": str(error)}
    else:
        if name != "good":
            raise RuntimeError("A failed mutant was accepted")
        if not clock_proof.validate(captured, EVIDENCE / name, receipt, identity(name)):
            raise RuntimeError("Positive proof could not be validated")
        positive = captured
report = {"positive": positive, "mutants": mutants, "simulation_rerun": False,
          "scope": "retained neutral execution and input identity; no behavioral correctness claim"}
with out.open("x") as stream:
    json.dump(report, stream, indent=2, allow_nan=False)
    stream.write("\n")
print(json.dumps({"positive_passed": True, "mutants_rejected": len(mutants), "path": str(out)}))
