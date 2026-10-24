"""Publish a verified sealed DEV cohort as immutable, aggregate-only JSON."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.reliability.public import VerifierSpec, export, load_admin
from app.reliability.safeio import canonical
from scripts.reliability_host import PINNED_SEALERS, verify_executor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort")
    parser.add_argument("--sealer", choices=tuple(PINNED_SEALERS), default="base")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--public-root", type=Path, default=ROOT / "runs/reliability-public")
    args = parser.parse_args(argv)
    try:
        args.public_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        spec = VerifierSpec(args.sealer, PINNED_SEALERS[args.sealer], PINNED_SEALERS["base"])
        row = export(args.repo_root, args.public_root, args.cohort, spec, verify_executor)
        result = load_admin(args.public_root, enabled=True)
        print(canonical({"export": row, "state": result["state"], "cohorts": len(result["cohorts"])}).decode())
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print("Reliability export rejected; inspect the private sealed cohort and publisher configuration.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
