#!/usr/bin/env python3
"""Queue an explicitly supplied faulty UART for real independent tests and model repair."""

import argparse
import json
from pathlib import Path
import sys
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.agent.starters import load_starter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    starter = load_starter("uart_off_by_one")
    payload = {"spec_text": starter.spec_text, "preset_id": "uart", "starter_id": starter.id,
               "targets": {"clock_mhz": 50}}
    request = urllib.request.Request(args.api.rstrip("/") + "/api/runs", method="POST",
                                     data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    marker = REPO / "runs/m10-repair-run.json"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(json.dumps(result, indent=2) + "\n")
    print("Queued real supplied-starter repair: " + result["run_id"])
    print("Initial RTL is explicitly supplied with a known timing defect; it is not a model-generated first attempt.")
    print("Open http://localhost:3000/runs/" + result["run_id"])


if __name__ == "__main__":
    main()
