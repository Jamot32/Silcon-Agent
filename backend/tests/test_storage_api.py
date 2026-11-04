import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app import main
from app.api_schemas import PublicRun
from app.models import Run
from app.storage import BusyRunError, RunStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}))
    monkeypatch.setenv("PRESETS_PATH", str(Path(__file__).parents[2] / "designs/presets.json") if (Path(__file__).parents[2] / "designs/presets.json").exists() else "/designs/presets.json")
    with TestClient(main.app, base_url="http://localhost", headers={"X-Silicon-Request": "1"}) as client:
        yield client


def test_run_queue_rate_limit_cancel_and_resume(client):
    created = client.post("/api/runs", json={"spec_text": "Build an eight bit counter", "targets": {"clock_mhz": 50}})
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    assert client.post("/api/runs", json={"spec_text": "Build another counter"}).status_code == 409
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["cost_usd"] is None and run["status"] == "pending"
    main.app.state.store.emit(run_id, "note", {"text": "A multiline\nobservation"})
    cancelled = client.post(f"/api/runs/{run_id}/cancel").json()
    assert cancelled["status"] == "cancelled"
    stream = client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "1"})
    assert stream.status_code == 200
    assert "id: 1\n" not in stream.text
    assert "event: note" in stream.text and "A multiline\\nobservation" in stream.text
    assert "event: run_finished" in stream.text
    assert client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "-2"}).status_code == 400
    assert client.post("/api/runs", json={"spec_text": "Build another counter"}).status_code == 202


def test_settings_report_provider_configuration_without_secrets(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "meta")
    monkeypatch.setenv("META_API_KEY", "sk-secret-value")
    monkeypatch.setenv("META_MODEL", "muse-spark-1.3-contributor")
    monkeypatch.setenv("LLM_MAX_TOKENS", "")
    monkeypatch.setenv("RUN_BUDGET_USD", "2")
    monkeypatch.delenv("META_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("LLM_MAX_CALLS", "12")
    response = client.get("/api/settings")
    assert response.json() == {"provider": "meta", "model": "muse-spark-1.3-contributor", "reasoning_effort": "medium",
                               "max_calls": 12, "max_tokens": None, "budget_usd": 2.0}
    assert "sk-secret-value" not in response.text
    # Codex ignores META_MODEL and has no reasoning-effort setting here.
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    assert client.get("/api/settings").json()["model"] == "gpt-6.1-sol"
    monkeypatch.setenv("LLM_MAX_CALLS", "many")
    assert client.get("/api/settings").status_code == 500


def test_request_validation_and_unknown_artifacts(client):
    assert client.post("/api/runs", json={"spec_text": " " * 20}).status_code == 422
    assert client.post("/api/runs", json={"spec_text": "Make a counter", "targets": {"clock_mhz": -1}}).status_code == 422
    assert client.post("/api/runs", json={"spec_text": "Make a counter", "preset_id": "missing"}).status_code == 422
    assert client.get("/api/runs/no-such-run").status_code == 404
    run_id = client.post("/api/runs", json={"spec_text": "Build a counter"}).json()["run_id"]
    assert client.get(f"/api/runs/{run_id}/bundle.zip").status_code == 404
    assert client.get(f"/api/runs/{run_id}/layout/unknown.png").status_code == 404


def test_untrusted_host_and_missing_app_header_are_rejected(client):
    spec = {"spec_text": "Build an eight bit counter"}
    # DNS rebinding: a page on an attacker's name resolving to loopback sends that name as Host.
    for host in ("evil.example", "evil.example:8000", "localhost.evil.example"):
        assert client.get("/api/runs", headers={"Host": host}).status_code == 400
        assert client.post("/api/runs", headers={"Host": host}, json=spec).status_code == 400
    for host in ("localhost:8000", "127.0.0.1:8000", "api:8000"):
        assert client.get("/api/runs", headers={"Host": host}).status_code == 200
    del client.headers["X-Silicon-Request"]
    run_id = "0" * 32
    review = {"design_spec": REVIEW_SPEC, "build": {}}
    for path, body in (("/api/runs", spec), (f"/api/runs/{run_id}/cancel", None), (f"/api/runs/{run_id}/review", review),
                       ("/api/replays", {"recording_id": "missing", "speed": 4})):
        assert client.post(path, json=body).status_code == 403
        assert client.post(path, headers={"X-Silicon-Request": "1", "Sec-Fetch-Site": "cross-site"}, json=body).status_code == 403
    assert client.get("/api/runs").json() == []
    assert client.post("/api/runs", headers={"X-Silicon-Request": "1", "Sec-Fetch-Site": "same-origin"}, json=spec).status_code == 202


def finished_parent(client, *, source=None):
    store = main.app.state.store
    parent_id = client.post("/api/runs", json={"spec_text": "Build an eight bit counter", "targets": {"clock_mhz": 50}}).json()["run_id"]
    if source is not None:
        (store.work_dir(parent_id) / "src").mkdir()
        (store.work_dir(parent_id) / "src/counter.v").write_text(source)
        (store.work_dir(parent_id) / "test").mkdir()
        (store.work_dir(parent_id) / "test/test_counter.py").write_text("import cocotb\n")
    store.emit(parent_id, "stage_changed", {"stage": "RTL", "design_spec": {"top_module": "counter"}})
    assert client.post(f"/api/runs/{parent_id}/cancel").json()["status"] == "cancelled"
    return store, parent_id


def test_revision_links_its_parent_and_carries_only_the_parent_rtl(client):
    store, parent_id = finished_parent(client, source="module counter; endmodule\n")
    revise = lambda **body: client.post("/api/runs", json={"spec_text": "Build an eight bit counter that wraps at nine", **body})
    assert revise(reuse_design=True).status_code == 422
    assert revise(parent_run_id=parent_id, reuse_design=True, starter_id="uart_off_by_one").status_code == 422
    assert revise(parent_run_id="0" * 32).status_code == 422
    assert revise(parent_run_id="not-a-run").status_code == 422
    created = revise(parent_run_id=parent_id, reuse_design=True)
    assert created.status_code == 202
    child = client.get(f"/api/runs/{created.json()['run_id']}").json()
    assert child["parent_run_id"] == parent_id and child["carried_files"] == ["src/counter.v"]
    assert "carry_over_json" not in child and "module counter" not in json.dumps(child)
    # The worker claims the full row, including what the orchestrator needs to start from.
    assert json.loads(store.claim_pending().carry_over_json) == {
        "parent_run_id": parent_id, "origin": "last source state", "spec_text": "Build an eight bit counter",
        "design_spec": {"top_module": "counter"}, "files": {"src/counter.v": "module counter; endmodule\n"},
    }
    client.post(f"/api/runs/{child['id']}/cancel")
    store.fail(child["id"], "Unit run stopped", status="cancelled")
    lineage = revise(parent_run_id=parent_id).json()["run_id"]
    assert client.get(f"/api/runs/{lineage}").json()["carried_files"] == []
    assert store.get_run(lineage).carry_over_json is None


def test_revision_of_a_finished_run_starts_from_its_selected_snapshot(client):
    store, parent_id = finished_parent(client, source="module counter; // losing RTL edit\nendmodule\n")
    bundle = store.root / parent_id / "bundle.zip"
    with ZipFile(bundle, "w") as archive:
        archive.writestr("src/counter.v", "module counter; // selected\nendmodule\n")
        archive.writestr("test/test_counter.py", "import cocotb\n")
        archive.writestr("../src/escape.v", "module escape; endmodule\n")
    store.register_artifact(parent_id, "bundle", bundle)
    revise = lambda: client.post("/api/runs", json={"spec_text": "Build a smaller eight bit counter", "parent_run_id": parent_id, "reuse_design": True})
    # A run that did not finish carries its last source state even when a bundle exists (e.g. a cancelled replay).
    run_id = revise().json()["run_id"]
    assert json.loads(store.get_run(run_id).carry_over_json)["origin"] == "last source state"
    store.fail(run_id, "Unit run stopped", status="cancelled")
    with Session(store.engine) as session:
        session.get(Run, parent_id).status = "done"
        session.commit()
    run_id = revise().json()["run_id"]
    carried = json.loads(store.get_run(run_id).carry_over_json)
    assert carried["origin"] == "selected flow snapshot"
    assert carried["files"] == {"src/counter.v": "module counter; // selected\nendmodule\n"}
    store.fail(run_id, "Unit run stopped", status="cancelled")
    # A corrupt deflate stream is a request error, not a server crash.
    with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("src/counter.v", "module counter;\n" + "// filler\n" * 400 + "endmodule\n")
    raw = bytearray(bundle.read_bytes())
    raw[60:80] = b"\xff" * 20
    bundle.write_bytes(bytes(raw))
    assert revise().status_code == 422


def test_revision_without_parent_rtl_is_rejected(client):
    _, parent_id = finished_parent(client)
    created = client.post("/api/runs", json={"spec_text": "Build an eight bit counter", "parent_run_id": parent_id, "reuse_design": True})
    assert created.status_code == 422 and "no RTL" in created.json()["detail"]


REVIEW_SPEC = {
    "top_module": "counter", "summary": "8-bit counter", "purely_combinational": False,
    "ports": [{"name": "clk", "direction": "input", "width": 1, "description": "Clock"},
              {"name": "rst_n", "direction": "input", "width": 1, "description": "Active-low reset"},
              {"name": "count", "direction": "output", "width": 8, "description": "Count"}],
    "behavior": ["Counts up each enabled clock"], "test_plan": ["Reset", "Count", "Wrap", "Hold"],
    "targets": {"clock_mhz": 50, "max_area_um2": None, "fit": None},
}


def test_expert_review_is_accepted_once_and_only_while_the_run_waits(client):
    store = main.app.state.store
    run_id = client.post("/api/runs", json={"spec_text": "Build an eight bit counter", "review": True}).json()["run_id"]
    created = client.get(f"/api/runs/{run_id}").json()
    assert (created["review_requested"], created["review_submitted"]) == (True, False)
    answer = {"design_spec": REVIEW_SPEC, "build": {"optimize": False, "max_flow_runs": 2, "max_repair_loops": 1,
                                                     "initial_flow": {"SYNTH_STRATEGY": "DELAY 1", "FP_CORE_UTIL": 30}}}
    review = lambda body: client.post(f"/api/runs/{run_id}/review", json=body)
    assert review(answer).status_code == 409  # still pending, not at REVIEW
    store.claim_pending()
    store.emit(run_id, "stage_changed", {"stage": "REVIEW", "design_spec": REVIEW_SPEC})
    sequential_without_clock = {**REVIEW_SPEC, "ports": REVIEW_SPEC["ports"][1:]}
    for invalid in ({**answer, "design_spec": sequential_without_clock},
                    {**answer, "build": {**answer["build"], "max_flow_runs": 7}},
                    # The clock comes from the clock target, never from a raw flow override.
                    {**answer, "build": {**answer["build"], "initial_flow": {"CLOCK_PERIOD": 5}}},
                    {**answer, "build": {**answer["build"], "initial_flow": {"SYNTH_STRATEGY": "FAST 9"}}}):
        assert review(invalid).status_code == 422
    accepted = review(answer)
    assert accepted.status_code == 200 and accepted.json()["review_submitted"] is True
    assert "review_json" not in accepted.json()
    assert json.loads(store.get_run(run_id).review_json) == answer
    # Reviewed targets replace the request (nulls dropped) so result pages and Revise follow what was built.
    assert accepted.json()["targets"] == {"clock_mhz": 50}
    assert review(answer).status_code == 409


def test_review_window_closes_on_the_server(client, monkeypatch):
    store = main.app.state.store
    run_id = client.post("/api/runs", json={"spec_text": "Build an eight bit counter", "review": True}).json()["run_id"]
    store.claim_pending()
    store.emit(run_id, "stage_changed", {"stage": "REVIEW"})
    monkeypatch.setattr("app.storage.REVIEW_TIMEOUT_SECONDS", -1)
    closed = client.post(f"/api/runs/{run_id}/review", json={"design_spec": REVIEW_SPEC, "build": {}})
    assert closed.status_code == 409 and "review window has closed" in closed.json()["detail"]
    assert store.get_run(run_id).review_json is None


def test_review_keeps_a_supplied_starter_interface(client):
    store = main.app.state.store
    run_id = client.post("/api/runs", json={"spec_text": "Repair the supplied UART", "starter_id": "uart_off_by_one", "review": True}).json()["run_id"]
    store.claim_pending()
    store.emit(run_id, "stage_changed", {"stage": "REVIEW"})
    response = client.post(f"/api/runs/{run_id}/review", json={"design_spec": REVIEW_SPEC, "build": {}})
    assert response.status_code == 422 and "uart_tx" in response.json()["detail"]
    assert store.get_run(run_id).review_json is None


@pytest.mark.parametrize("targets", [{"fit": None}, {"clock_mhz": 25.0},
                                     {"clock_mhz": 25.0, "fit": None}, {}])
def test_explicit_target_null_survives_api_without_inventing_omitted_fields(client, targets):
    created = client.post("/api/runs", json={"spec_text": "Build a small digital counter", "targets": targets})
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    assert client.get(f"/api/runs/{run_id}").json()["targets"] == targets
    assert json.loads(main.app.state.store.get_run(run_id).targets_json) == targets
    claimed = main.app.state.store.claim_pending()
    assert claimed.id == run_id and json.loads(claimed.targets_json) == targets


def test_atomic_claim_and_global_active_limit(tmp_path):
    store = RunStore(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(store.create_run, "A counter spec") for _ in range(2)]
    results = []
    for future in futures:
        try:
            results.append(future.result())
        except BusyRunError:
            results.append(None)
    assert sum(value is not None for value in results) == 1
    with ThreadPoolExecutor(2) as pool:
        claimed = list(pool.map(lambda _: store.claim_pending(), range(2)))
    assert sum(value is not None for value in claimed) == 1
    run = next(value for value in results if value is not None)
    store.request_cancel(run.id)
    assert store.cancel_requested(run.id)
    store.recover_interrupted()
    assert store.get_run(run.id).status == "failed"


def test_concurrent_first_start_initializes_once(tmp_path):
    with ThreadPoolExecutor(2) as pool:
        stores = list(pool.map(lambda _: RunStore(tmp_path), range(2)))
    assert stores[0].list_runs() == stores[1].list_runs() == []


def test_unknown_cost_and_real_fixture_metric_persist(tmp_path):
    store = RunStore(tmp_path)
    run = store.create_run("A counter spec")
    store.claim_pending()
    store.emit(run.id, "stage_changed", {"stage": "FLOW"})
    store.emit(run.id, "cost_update", {"cost_usd": None, "input_tokens": 12, "output_tokens": 5, "calls": 1})
    assert PublicRun.from_run(store.get_run(run.id)).cost_usd is None
    assert store.get_run(run.id).call_count == 1
    from app.eda.parsers import parse_librelane_metrics

    fixture = Path(__file__).parent / "fixtures/golden_counter"
    metric = parse_librelane_metrics(fixture / "metrics.json", fixture / "resolved.json", run_id=run.id, iteration_id="ignored", run_tag="real_fixture")
    # The test stores a real recorded point; it never enters a runnable demo.
    store.emit(run.id, "metric_recorded", {"run_tag": metric.run_tag, "flow_index": 3, "metrics": metric.model_dump(mode="json")})
    row = store.metrics(run.id)[0]
    assert row.flow_index == 3 and row.area_um2 == metric.area_um2
    store.fail(run.id, "Test ended")
    assert store.events(run.id)[-1].type == "run_finished"


def test_artifact_variant_identity_and_symlink_escape(client, tmp_path):
    run_id = client.post("/api/runs", json={"spec_text": "Build a counter"}).json()["run_id"]
    store = main.app.state.store
    root = tmp_path / run_id
    image = root / "one.png"
    image.write_bytes(b"first-variant")
    store.register_artifact(run_id, "layout", image, "flow_one")
    assert client.get(f"/api/runs/{run_id}/layout/flow_one.png").content == b"first-variant"
    assert client.get(f"/api/runs/{run_id}/layout/flow_two.png").status_code == 404
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    image.unlink()
    image.symlink_to(outside)
    assert client.get(f"/api/runs/{run_id}/layout/flow_one.png").status_code == 404
    with pytest.raises(ValueError):
        store.register_artifact(run_id, "bundle", outside)
    source = store.work_dir(run_id) / "src"
    source.symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / "private.v").write_text("private")
    assert client.get(f"/api/runs/{run_id}/files").json() == {}


def test_bootstrap_migration_preserves_existing_run(tmp_path):
    import sqlite3

    db = tmp_path / "silicon-agent.db"
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE run (id VARCHAR PRIMARY KEY, spec_text VARCHAR NOT NULL, design_spec_json VARCHAR, status VARCHAR NOT NULL, stage VARCHAR NOT NULL, created_at DATETIME NOT NULL, cost_usd FLOAT NOT NULL, is_replay BOOLEAN NOT NULL)')
        connection.execute("INSERT INTO run VALUES ('existing', 'old spec', NULL, 'done', 'DONE', '2026-10-23 00:00:00', 0, 0)")
    store = RunStore(tmp_path)
    assert store.get_run("existing").spec_text == "old spec"
    assert store.get_run("existing").cost_known is False


def test_failed_verification_iteration_stays_failed(tmp_path):
    from sqlmodel import Session, select
    from app.models import Iteration

    store = RunStore(tmp_path)
    run = store.create_run("A counter spec")
    store.emit(run.id, "stage_changed", {"stage": "VERIFY"})
    store.emit(run.id, "stage_changed", {"stage": "RTL"})
    with Session(store.engine) as session:
        verification = session.exec(select(Iteration).where(Iteration.stage == "VERIFY")).one()
        assert verification.ok is False and verification.ended_at is not None
