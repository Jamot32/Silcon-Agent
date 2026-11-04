"""Detached editing and source provenance, using temporary data and offline fixtures."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
from threading import Barrier
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app import main
from app.agent.evidence import ToolEvidence
from app.eda.sandbox import CommandObservation, CommandResult
from app.models import Run
from app.schemas import DesignSpec
from app.storage import BusyRunError, RunStore

SPEC = {"top_module": "counter", "summary": "8-bit counter", "purely_combinational": False,
        "ports": [{"name": "clk", "direction": "input", "width": 1, "description": "Clock"},
                  {"name": "rst_n", "direction": "input", "width": 1, "description": "Active-low reset"},
                  {"name": "count", "direction": "output", "width": 8, "description": "Count"}],
        "behavior": ["Counts up each enabled clock"], "test_plan": ["Reset", "Count", "Wrap", "Hold"],
        "targets": {"clock_mhz": 50, "max_area_um2": None, "fit": None}}
FILES = {"src/counter.v": "module counter; endmodule\n", "test/test_counter.py": "# Isolated test source; never executed.\n"}
RECORDINGS = Path(__file__).resolve().parents[2] / "demo_recordings"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}))
    with TestClient(main.app, base_url="http://localhost", headers={"X-Silicon-Request": "1"}) as client:
        yield client


def parent_run(*, terminal=True, spec=True):
    store = main.app.state.store
    run = store.create_run("Build an eight-bit counter", targets={"clock_mhz": 75})
    if spec:
        store.emit(run.id, "stage_changed", {"stage": "RTL", "design_spec": SPEC})
    for name, content in FILES.items():
        path = store.work_dir(run.id) / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content)
    if terminal:
        store.fail(run.id, "Isolated fixture stopped")
    return run.id


def save(client, run_id, files=FILES, revision=0, **extra):
    return client.put(f"/api/runs/{run_id}/workspace", json={"files": files, "expected_revision": revision, **extra})


def test_workspace_is_durable_and_does_not_modify_evidence_or_working_files(client):
    run_id = parent_run(terminal=False)
    store = main.app.state.store
    public_before = client.get(f"/api/runs/{run_id}").json()
    events_before = [(event.id, event.payload_json) for event in store.events(run_id)]
    assert client.get(f"/api/runs/{run_id}/workspace").json() == {"files": None, "updated_at": None, "revision": 0, "base_source": None}
    draft = {**FILES, "src/counter.v": "module counter; // My draft\nendmodule\n"}
    response = save(client, run_id, draft, base_source={"kind": "working"})
    assert response.status_code == 200
    saved = response.json()
    assert saved["files"] == draft and saved["revision"] == 1 and saved["updated_at"]
    assert saved["base_source"] == {"kind": "working", "run_tag": None, "event_id": None}
    assert client.get(f"/api/runs/{run_id}").json() == public_before
    assert [(event.id, event.payload_json) for event in store.events(run_id)] == events_before
    assert client.get(f"/api/runs/{run_id}/files").json() == FILES
    assert "workspace" not in (store.root / run_id / "run.json").read_text()
    restarted = RunStore(store.root, engine=store.engine)
    assert restarted.workspace(run_id).model_dump(mode="json") == saved


def test_save_and_discard_use_monotonic_revisions_and_keep_newer_edits(client):
    run_id = parent_run()
    assert save(client, run_id).status_code == 200
    assert save(client, run_id, {"src/new.v": "new text"}, revision=0).status_code == 409
    assert client.delete(f"/api/runs/{run_id}/workspace?expected_revision=0").status_code == 409
    assert client.get(f"/api/runs/{run_id}/workspace").json()["files"] == FILES
    assert client.delete(f"/api/runs/{run_id}/workspace?expected_revision=1").status_code == 204
    empty = client.get(f"/api/runs/{run_id}/workspace").json()
    assert empty == {"files": None, "updated_at": None, "revision": 2, "base_source": None}
    assert save(client, run_id, revision=1).status_code == 409
    assert save(client, run_id, {}, revision=2).json()["files"] == {}


@pytest.mark.parametrize("files", [
    {"../outside.v": "x"}, {"src/sub/file.v": "x"}, {"/src/file.v": "x"},
    {"src/file-name.v": "x"}, {"src/file.sv": "x"}, {"config.json": "{}"},
    {"test/file.py": "\0"}, {"src/file.v": "é" * (64 * 1024 + 1)},
    {f"src/file{i}.v": "x" for i in range(65)},
    {f"src/file{i}.v": "x" * (128 * 1024) for i in range(17)},
])
def test_workspace_rejects_unsafe_paths_binary_and_oversized_input(client, files):
    run_id = parent_run()
    assert save(client, run_id, files).status_code == 422
    assert main.app.state.store.get_run(run_id).workspace_json is None


@pytest.mark.parametrize("body", [
    {"files": FILES}, {"files": FILES, "expected_revision": -1},
    {"files": FILES, "expected_revision": "0"},
    {"files": FILES, "expected_revision": 0, "base_source": {"kind": "working", "run_tag": "flow_one"}},
    {"files": FILES, "expected_revision": 0, "base_source": {"kind": "flow"}},
    {"files": FILES, "expected_revision": 0, "base_source": {"kind": "flow", "run_tag": "flow_one", "event_id": 1}},
])
def test_workspace_request_schema_is_explicit(client, body):
    run_id = parent_run()
    assert client.put(f"/api/runs/{run_id}/workspace", json=body).status_code == 422


def test_workspace_mutations_have_request_guards_and_run_deletion_removes_draft(client):
    run_id = parent_run()
    assert save(client, run_id).status_code == 200
    del client.headers["X-Silicon-Request"]
    assert save(client, run_id, revision=1).status_code == 403
    assert client.delete(f"/api/runs/{run_id}/workspace?expected_revision=1").status_code == 403
    client.headers["X-Silicon-Request"] = "1"
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}/workspace").status_code == 404
    assert save(client, run_id, revision=1).status_code == 404


def test_concurrent_draft_saves_have_one_winner(client):
    run_id = parent_run()
    store = main.app.state.store
    barrier = Barrier(2)

    def write(name):
        barrier.wait()
        try:
            return store.save_workspace(run_id, {"files": {"src/counter.v": name}, "expected_revision": 0}).files
        except BusyRunError:
            return None

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(write, ["first", "second"]))
    assert sum(value is not None for value in outcomes) == 1
    assert store.workspace(run_id).files in outcomes


def manual_body(parent, **extra):
    return {"spec_text": "Client text is not the authoritative manual contract", "parent_run_id": parent,
            "execution_mode": "manual", "manual_files": FILES, **extra}


def test_manual_build_creates_a_new_child_with_exact_files_and_inherited_contract(client):
    parent = parent_run()
    store = main.app.state.store
    assert save(client, parent, {**FILES, "src/counter.v": "An unrelated newer draft"}).status_code == 200
    response = client.post("/api/runs", json=manual_body(parent, build={"initial_flow": {"FP_CORE_UTIL": 30}}))
    assert response.status_code == 202, response.text
    child = response.json()["run_id"]
    assert child != parent
    public = client.get(f"/api/runs/{child}").json()
    assert public["execution_mode"] == "manual" and public["llm_provider"] == "manual"
    assert public["has_manual_edits"] is True
    assert public["spec_text"] == store.get_run(parent).spec_text
    assert public["design_spec"] == DesignSpec.model_validate(SPEC).model_dump()
    assert public["targets"] == SPEC["targets"]  # The original 75 MHz request cannot replace accepted 50 MHz.
    assert public["requested_build"] == {"optimize": False, "max_flow_runs": 1, "max_repair_loops": 0, "initial_flow": {"FP_CORE_UTIL": 30}}
    carried = json.loads(store.get_run(child).carry_over_json)
    assert carried["files"] == FILES and carried["origin"] == "manual edits"
    assert carried["design_spec"] == public["design_spec"]
    assert public["input_tokens"] == public["output_tokens"] == public["call_count"] == 0
    assert "workspace_json" not in public and "workspace_revision" not in public
    assert client.get(f"/api/runs/{parent}/files").json() == FILES
    assert store.workspace(parent).files["src/counter.v"] == "An unrelated newer draft"


@pytest.mark.parametrize("extra", [
    {"manual_files": None}, {"manual_files": {"src/counter.v": "RTL only"}},
    {"manual_files": {**FILES, "test/test_other.py": "# another module"}},
    {"reuse_design": True}, {"review": True}, {"targets": {"clock_mhz": 25}},
    {"follow_up": "Change the requirements", "revision_intent": "feature"},
    {"parent_run_id": None},
])
def test_manual_build_rejects_ambiguous_or_unsupported_requests(client, extra):
    parent = parent_run()
    assert client.post("/api/runs", json=manual_body(parent, **extra)).status_code == 422
    assert len(main.app.state.store.list_runs()) == 1


@pytest.mark.parametrize("terminal,spec,status", [(False, True, 409), (True, False, 422)])
def test_manual_build_requires_terminal_parent_and_accepted_spec(client, terminal, spec, status):
    parent = parent_run(terminal=terminal, spec=spec)
    assert client.post("/api/runs", json=manual_body(parent)).status_code == status


@pytest.mark.parametrize("tests", [{}, {"test/test_one.py": "first test", "test/test_two.py": "second test"}])
def test_agent_workspace_build_is_default_and_retains_test_edits_as_submitted_context(client, monkeypatch, tests):
    parent = parent_run()
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    files = {"src/counter.v": "module counter; // User edit\nendmodule", **tests}
    response = client.post("/api/runs", json={"spec_text": "Client text should not change the accepted contract",
        "parent_run_id": parent, "manual_files": files})
    assert response.status_code == 202, response.text
    run = main.app.state.store.get_run(response.json()["run_id"])
    carried = json.loads(run.carry_over_json)
    assert run.execution_mode == "agent" and run.llm_provider == "codex"
    assert carried["origin"] == "workspace edits" and carried["files"] == files
    assert json.loads(run.design_spec_json) == DesignSpec.model_validate(SPEC).model_dump()
    assert json.loads(run.build_json)["optimize"] is True
    assert json.loads(run.targets_json) == SPEC["targets"]
    assert client.get(f"/api/runs/{run.id}").json()["has_manual_edits"] is True


def test_agent_build_from_manual_parent_restores_repair_and_optimization_defaults(client):
    parent = parent_run()
    manual = client.post("/api/runs", json=manual_body(parent, build={"initial_flow": {"FP_CORE_UTIL": 30}})).json()["run_id"]
    store = main.app.state.store
    store.fail(manual, "Isolated fixture stopped")
    response = client.post("/api/runs", json={"spec_text": "Build from my edited counter", "parent_run_id": manual,
                                            "manual_files": {"src/counter.v": FILES["src/counter.v"]}})
    assert response.status_code == 202
    build = client.get(f"/api/runs/{response.json()['run_id']}").json()["requested_build"]
    assert build == {"optimize": True, "max_flow_runs": 6, "max_repair_loops": 5, "initial_flow": {"FP_CORE_UTIL": 30}}


@pytest.mark.parametrize("mode", ["agent", "manual"])
def test_cancelled_unaccepted_review_cannot_be_bypassed_by_building_edited_files(client, mode):
    parent = parent_run()
    store = main.app.state.store
    with Session(store.engine) as session:
        run = session.get(Run, parent)
        run.review_requested = True
        run.review_json = None
        run.status = "cancelled"
        session.add(run)
        session.commit()
    response = client.post("/api/runs", json=manual_body(parent, execution_mode=mode))
    assert response.status_code == 422 and "review was not accepted" in response.json()["detail"]
    assert save(client, parent).status_code == 200


def attempt(run_id, source_text, *, call="same-call-label"):
    """Synthetic host receipt for path/identity tests; no command is executed."""
    store = main.app.state.store
    run = store.get_run(run_id)
    work = store.work_dir(run_id)
    base = work / ".eda" / ("flow_" + uuid4().hex)
    source, output = base / "input", base / "output"
    (source / "src").mkdir(parents=True)
    (source / "test").mkdir()
    (source / "src/counter.v").write_text(source_text)
    (source / "test/test_counter.py").write_text(FILES["test/test_counter.py"])
    output.mkdir()
    log = output / "tool.log"
    log.write_text("Synthetic boundary fixture; no process ran")
    tag = "flow_" + uuid4().hex[:16]
    store.emit(run_id, "tool_started", {"tool": "run_flow", "tool_call_id": call})
    started = store.events(run_id, limit=1000)[-1].id
    host = ToolEvidence(work, "sha256:" + "5" * 64)
    source_hash = hashlib.sha256(b"counter.v\0" + source_text.encode() + b"\0").hexdigest()
    context = host.begin(call, "run_flow", source_hash, "2" * 64)
    host.observe(CommandObservation(("python3", "/opt/silicon-agent/runtime.py", "flow", "--top", "counter", "--run-tag", tag),
        source, output, CommandResult(1, False, log, "Synthetic boundary fixture"), 0.1, True))
    result = {"ok": False, "run_tag": tag, "physical_flow_started": True}
    result.update(host.finish(context, result))
    store.emit(run_id, "tool_finished", {"tool": "run_flow", "tool_call_id": call, "result": result})
    finished = store.events(run_id, limit=1000)[-1].id
    return {"tag": tag, "started": started, "finished": finished, "source": source, "result": result}


def test_flow_sources_use_exact_attempt_even_with_repeated_tool_labels(client):
    run_id = parent_run(terminal=False)
    first = attempt(run_id, "// first exact snapshot")
    second = attempt(run_id, "// second exact snapshot")
    for selector in ({"event_id": first["started"]}, {"event_id": first["finished"]}, {"run_tag": first["tag"]}):
        response = client.get(f"/api/runs/{run_id}/sources", params=selector)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["available"] and data["provenance"] == "flow_snapshot"
        assert data["event_id"] == first["finished"] and data["run_tag"] == first["tag"]
        assert data["files"]["src/counter.v"] == "// first exact snapshot"
        assert "checksum" in data["reason"]
    second_data = client.get(f"/api/runs/{run_id}/sources", params={"run_tag": second["tag"]}).json()
    assert second_data["files"]["src/counter.v"] == "// second exact snapshot"
    assert client.get(f"/api/runs/{run_id}/files").json() == FILES


def test_manual_flow_test_snapshot_must_match_the_exact_submitted_files(client):
    run_id = parent_run(terminal=False)
    flow = attempt(run_id, FILES["src/counter.v"])
    store = main.app.state.store
    with Session(store.engine) as session:
        run = session.get(Run, run_id)
        run.execution_mode = "manual"
        run.carry_over_json = json.dumps({"origin": "manual edits", "files": FILES, "design_spec": SPEC})
        session.add(run)
        session.commit()
    good = client.get(f"/api/runs/{run_id}/sources", params={"run_tag": flow["tag"]}).json()
    assert good["available"] and good["files"] == FILES and good["reason"] is None
    (flow["source"] / "test/test_counter.py").write_text("# Changed after manual submission")
    changed = client.get(f"/api/runs/{run_id}/sources", params={"run_tag": flow["tag"]}).json()
    assert not changed["available"] and changed["files"] == {}


@pytest.mark.parametrize("damage", ["missing", "changed", "source_symlink", "test_symlink"])
def test_missing_or_invalid_flow_source_never_falls_back_to_latest_working_files(client, damage, tmp_path):
    run_id = parent_run(terminal=False)
    flow = attempt(run_id, "// exact physical snapshot")
    path = flow["source"] / ("test/test_counter.py" if damage == "test_symlink" else "src/counter.v")
    if damage == "missing":
        shutil.rmtree(flow["source"])
    elif damage == "changed":
        path.write_text("// changed after receipt")
    else:
        path.unlink()
        outside = tmp_path / "never-read.txt"
        outside.write_text("PRIVATE OUTSIDE DATA")
        path.symlink_to(outside)
    result = client.get(f"/api/runs/{run_id}/sources", params={"run_tag": flow["tag"]})
    assert result.status_code == 200
    assert not result.json()["available"] and result.json()["files"] == {}
    assert "PRIVATE" not in result.text


def selected_bundle(run_id, transform=None):
    store = main.app.state.store
    original = RECORDINGS / "uart-optimization" / "bundle.zip"
    with ZipFile(original) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    if transform:
        transform(members)
    target = store.root / run_id / "selected.zip"
    with ZipFile(target, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    tag = json.loads(members["metrics.json"])["run_tag"]
    store.register_artifact(run_id, "bundle", target)
    with Session(store.engine) as session:
        run = session.get(Run, run_id)
        run.best_run_tag = tag
        run.status = "done"
        run.is_replay = True
        session.add(run)
        session.commit()
    return tag, members


def test_selected_recording_bundle_supplies_only_its_exact_checked_source(client):
    run_id = parent_run()
    tag, members = selected_bundle(run_id)
    result = client.get(f"/api/runs/{run_id}/sources", params={"run_tag": tag})
    assert result.status_code == 200
    data = result.json()
    assert data["available"] and data["provenance"] == "selected_bundle"
    assert data["files"] == {name: content.decode() for name, content in members.items() if name.startswith(("src/", "test/"))}
    assert client.get(f"/api/runs/{run_id}/sources", params={"run_tag": "other_flow"}).status_code == 404


def test_bundle_test_file_checksum_is_checked_before_exposure(client):
    run_id = parent_run()

    def damage(members):
        name = next(name for name in members if name.startswith("test/"))
        members[name] += b"# Changed after manifest\n"

    tag, _ = selected_bundle(run_id, damage)
    result = client.get(f"/api/runs/{run_id}/sources", params={"run_tag": tag}).json()
    assert not result["available"] and result["files"] == {}


@pytest.mark.parametrize("selector", [{}, {"event_id": 0}, {"run_tag": "../outside"}, {"run_tag": "flow", "event_id": 1}])
def test_source_selector_is_bounded_and_unambiguous(client, selector):
    run_id = parent_run()
    assert client.get(f"/api/runs/{run_id}/sources", params=selector).status_code == 422
