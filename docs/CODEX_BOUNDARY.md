# Codex live host setup

The guarded host path retained the full dev result 87/90 with unchanged grades; all 69 reported hardware builds passed independent tests. Actual OS controls and a neutral OAuth request passed before measurement. The read-boundary limits below remain explicit.

Recorded `make demo` playback stays key-free and makes no model/EDA calls. Codex live builds use macOS `sandbox-exec` and an admitted external policy. Meta keeps its existing credential and transport setup. The pinned Codex CLI login and real EDA prerequisites in README still apply; the saved OAuth login stays with the host CLI.

Prepare a host-reviewed inventory JSON before the five commands below. Its original project, every registered Git worktree and every known retained private copy must use canonical absolute paths. Include the shared Git object store and retained-private scopes. A clean single clone may explicitly list one registered root and no retained copies. `retained_inventory_complete=true` records the host operator's reviewed inventory; setup does not discover arbitrary copies. Use the installed sandbox binary's verified SHA256. The inventory and generation must be outside every protected project/archive root, under an owner-only directory.

Inventory structure (replace placeholders; this example deliberately remains unadmitted):

```json
{
  "schema_version": 1,
  "original_project_root": "/absolute/project",
  "registered_roots": ["/absolute/project"],
  "explicit_private_roots": [],
  "git_object_roots": ["/absolute/project/.git/objects"],
  "retained_private_roots": [],
  "retained_inventory_complete": false,
  "max_entries": 100000,
  "max_depth": 64,
  "sandbox_exec_sha256": "REPLACE_WITH_VERIFIED_BINARY_SHA256"
}
```

From the repository, using a new external directory and a completed reviewed inventory:

```sh
mkdir -m 700 /absolute/private-codex-host
install -m 600 /absolute/reviewed-inventory.json /absolute/private-codex-host/inventory.json
PYTHONPATH=backend uv run --python 3.12.13 --with-requirements backend/requirements.txt python scripts/setup_codex_boundary.py --inventory /absolute/private-codex-host/inventory.json --generation /absolute/private-codex-host/generation001
make llm-smoke CODEX_POLICY=/absolute/private-codex-host/generation001/policy.json
make demo CODEX_POLICY=/absolute/private-codex-host/generation001/policy.json
```

The smoke makes a real neutral provider request. The final command restarts this repository's owned host worker with the explicit locator. When the API is already running and the owned worker is stopped, the fifth command can instead be `python3 scripts/manage_worker.py start --codex-policy /absolute/private-codex-host/generation001/policy.json`.

Setup copies no OAuth/auth material and writes no global CLI configuration or HOME setting. The locator is forwarded to the worker process; it is not stored in `.env`. Normal `make setup` retains its existing server-worker-token role. Missing or stale Codex policy fails locally rather than launching an unwrapped client.

The installed policy wraps client preflights and inference from process launch, with empty private working directories and closed unrelated descriptors. Same-user CLI containment depends on the OS policy; owner-only directory modes cover other-user access. Metadata admission checks named private inputs and the registered roster at installation/client-creation points. Reinstall and restart after roots change. Known preexisting hardlink aliases outside the denied roots can bypass a path deny; trusted input admission must reject linked inputs and inventory known copies. Single links cannot prove that arbitrary copied content is absent. There is no continuous or whole-filesystem isolation claim. macOS's deprecated sandbox facility requires version-specific qualification; other platforms are not qualified for this Codex path. OAuth USD remains unknown when the provider reports no price. Existing token-budget defaults are unchanged.

For evaluation and self-hosted CI, supply `SILICON_CODEX_BOUNDARY_CONFIG` in the process environment with the installed policy path. The `CODEX_POLICY` Make option forwards the locator to live-worker and smoke commands. Evaluation retains its explicit budgets even when the app token default is unlimited.
