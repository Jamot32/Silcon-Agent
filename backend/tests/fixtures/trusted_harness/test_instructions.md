# Reproduce the selected tests

The trusted helper, frozen contract, actual XML/evidence and host proof in trusted/ belong to this selected flow. They are independent of later working-file edits.

With the pinned EDA image already available locally, extract the bundle and run these commands from its directory (paths must not contain commas):

```sh
bundle_dir="$(pwd)"
output_dir="$(mktemp -d)"
mkdir -p "$output_dir/home" "$output_dir/tmp" "$output_dir/cache"
docker run --rm --init --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --cpus 4 --memory 6g --pids-limit 512 \
  --user "$(id -u):$(id -g)" -e HOME=/output/home -e TMPDIR=/output/tmp \
  -e XDG_CACHE_HOME=/output/cache -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/opt/silicon-python -v "$bundle_dir:/input:ro" -v "$output_dir:/output" \
  --mount "type=bind,source=$bundle_dir/trusted/sa_tb.py,target=/opt/silicon-python/sa_tb.py,readonly" \
  -w /output sha256:9b62eb4f8e873591f6925c3aaf1f7cf459e848e867809a9068d48d49025f3cc8 \
  python3 /opt/silicon-agent/runtime.py sim --top proof_counter --test-module test_proof_counter > "$output_dir/tool.log" 2>&1
cat "$output_dir/result.json"
```

Outputs are tool.log, test_results.xml, sa_tb_evidence.json and result.json. The bundle's selected test results do not claim that a newly modified design passes.
