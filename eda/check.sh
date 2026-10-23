#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/eda/versions.env"
docker image inspect "$EDA_IMAGE" >/dev/null 2>&1 || { printf 'Run make eda-setup first.\n' >&2; exit 1; }
pdk_dir="$repo_root/runs/pdk/ciel/sky130/versions/$SKY130_REVISION"
test -d "$pdk_dir/sky130A" || { printf 'sky130 PDK missing; run make eda-setup.\n' >&2; exit 1; }
check_id="$(date -u +%Y%m%dT%H%M%SZ)"
work_dir="$repo_root/runs/eda-check/$check_id"
mkdir -p "$work_dir/tmp" "$work_dir/home" "$work_dir/cache"
cp -R "$repo_root/designs/golden/counter/." "$work_dir/"
docker run --rm --init --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --cpus 4 --memory 6g --pids-limit 512 \
  -e TMPDIR=/work/tmp -e HOME=/work/home -e XDG_CACHE_HOME=/work/cache \
  -v "$work_dir:/work" -v "$pdk_dir:/pdk:ro" -v "$repo_root/eda:/harness:ro" \
  "$EDA_IMAGE" python3 /harness/check.py
python3 - "$work_dir" "$SKY130_REVISION" "$EDA_IMAGE" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

work = Path(sys.argv[1])
result = json.loads((work / "check_result.json").read_text())
result.update(run_dir=work.name, pdk_revision=sys.argv[2], eda_image=sys.argv[3], checked_at=datetime.now(timezone.utc).isoformat())
result["artifacts"] = {kind: f"{work.name}/{path}" for kind, path in result["artifacts"].items()}
temporary = work.parent / "complete.json.tmp"
temporary.write_text(json.dumps(result, indent=2) + "\n")
temporary.replace(work.parent / "complete.json")
PY
printf 'Golden check output: %s\n' "$work_dir"
