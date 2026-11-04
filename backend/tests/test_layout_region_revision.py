"""Queue and context integration for frozen layout focus; no worker/model jobs."""
import base64
import hashlib
from io import BytesIO
import json

from PIL import Image
import pytest
from sqlmodel import Session

from app import main
from app.layout_region_types import PreparedLayoutRegion
from app.models import Run
from app.schemas import DesignSpec

from test_orchestrator import build_run, spec_data
from test_storage_api import client  # Shared isolated API fixture; no live worker.


def parent(client, *, tag="focus_variant", color="red"):
    store = main.app.state.store
    response = client.post("/api/runs", json={"spec_text": "Build a counter with enable and load"})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    image = store.work_dir(run_id) / f"{tag}.png"
    Image.new("RGB", (20, 12), color).save(image)
    store.register_artifact(run_id, "layout", image, tag)
    store.emit(run_id, "stage_changed", {"stage": "RTL", "design_spec": spec_data()})
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
    return run_id, image


def body(parent_id, *, tag="focus_variant", **extra):
    return {"spec_text": "Build a counter with enable and load", "parent_run_id": parent_id,
            "follow_up": "Investigate the requested layout concern while preserving behavior.",
            "revision_intent": "fix",
            "layout_region": {"run_tag": tag, "bounds": {"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75}},
            **extra}


def pixel(image):
    with Image.open(BytesIO(base64.b64decode(image.data, validate=True))) as decoded:
        return decoded.size, decoded.getpixel((0, 0))


def test_queue_freezes_exact_parent_variant_pixels_and_public_only_exposes_region(client):
    parent_id, path = parent(client)
    store = main.app.state.store
    other = path.with_name("selected_variant.png")
    Image.new("RGB", (20, 12), "blue").save(other)
    store.register_artifact(parent_id, "layout", other, "selected_variant")
    with Session(store.engine) as session:
        run = session.get(Run, parent_id)
        run.best_run_tag = "selected_variant"
        session.add(run)
        session.commit()
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    request = body(parent_id)
    request["layout_region"]["expected_image_sha256"] = original_hash
    response = client.post("/api/runs", json=request)
    assert response.status_code == 202, response.text
    child_id = response.json()["run_id"]
    carried = json.loads(store.get_run(child_id).carry_over_json)
    focus = PreparedLayoutRegion.model_validate(carried["layout_focus"])
    assert focus.region.source_run_id == parent_id and focus.region.run_tag == "focus_variant"
    assert focus.region.image_sha256 == original_hash
    assert focus.region.pixel_bounds.model_dump() == {"x0": 5, "y0": 3, "x1": 15, "y1": 9}
    assert pixel(focus.images[0]) == ((20, 12), (255, 0, 0))
    assert pixel(focus.images[1]) == ((10, 6), (255, 0, 0))
    assert carried["parent_context"]["best_run_tag"] == "selected_variant"

    # Later artifact edits cannot change the queued model's actual input pixels.
    Image.new("RGB", (20, 12), "green").save(path)
    frozen = PreparedLayoutRegion.model_validate(json.loads(store.claim_pending().carry_over_json)["layout_focus"])
    assert frozen == focus
    public = client.get(f"/api/runs/{child_id}")
    assert public.status_code == 200, public.text
    assert public.json()["layout_region"] == focus.region.model_dump(mode="json")
    listing = client.get("/api/runs?include_all=true")
    assert listing.status_code == 200
    for response in (public, listing):
        assert "carry_over_json" not in response.text and "layout_focus" not in response.text
        assert "images" not in response.text and "data:image" not in response.text
        for image in focus.images:
            assert image.data not in response.text


@pytest.mark.parametrize("change", [{"parent_run_id": None}, {"execution_mode": "manual"}])
def test_layout_focus_requires_an_agent_revision(client, change):
    parent_id, _ = parent(client)
    request = body(parent_id, **change)
    if change.get("parent_run_id", "present") is None:
        request.pop("follow_up")
        request.pop("revision_intent")
    response = client.post("/api/runs", json=request)
    assert response.status_code == 422, response.text
    assert "layout region requires an agent revision" in response.text
    assert len(main.app.state.store.list_runs()) == 1


def test_stale_image_hash_rejects_revision_before_queueing(client):
    parent_id, path = parent(client)
    request = body(parent_id)
    request["layout_region"]["expected_image_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    Image.new("RGB", (20, 12), "blue").save(path)
    response = client.post("/api/runs", json=request)
    assert response.status_code == 422 and "unavailable or has changed" in response.text
    assert len(main.app.state.store.list_runs()) == 1


def test_tag_registered_only_to_another_parent_is_rejected(client):
    parent_id, _ = parent(client, tag="first_parent")
    second_id, _ = parent(client, tag="second_parent", color="blue")
    assert parent_id != second_id
    response = client.post("/api/runs", json=body(parent_id, tag="second_parent"))
    assert response.status_code == 422 and "unavailable or has changed" in response.text
    assert len(main.app.state.store.list_runs()) == 2


def test_region_pixels_reach_design_contexts_but_never_independent_verification(client, tmp_path):
    parent_id, path = parent(client, tag="focus_only_variant")
    response = client.post("/api/runs", json=body(parent_id, tag="focus_only_variant"))
    assert response.status_code == 202, response.text
    queued = main.app.state.store.get_run(response.json()["run_id"])
    carry_over = json.loads(queued.carry_over_json)
    focus = PreparedLayoutRegion.model_validate(carry_over["layout_focus"])
    # An absent parent file after queueing must not require any later artifact read.
    path.unlink()
    orchestrator, llm, eda, events = build_run(tmp_path / "context", script=[], carry_over=carry_over)
    orchestrator.design_spec = DesignSpec.model_validate(spec_data())
    for stage in ("SPEC", "RTL", "OPTIMIZE"):
        messages = orchestrator._context(stage)
        image_messages = [message for message in messages if message.images]
        assert len(image_messages) == 1
        message = image_messages[0]
        context = json.loads(message.content)
        assert context["selected_layout_region"] == focus.region.model_dump(mode="json")
        assert [image.data for image in message.images] == [image.data for image in focus.images]
        assert [image.label for image in message.images] == ["full_layout", "selected_region"]
        assert "not a cell/net/layer or physical-coordinate mapping" in context["instruction"]
        assert "fresh evidence" in context["instruction"]
        assert "may differ from the inspected flow variant" in context["instruction"]

    verification = orchestrator._context("VERIFY")
    assert all(not message.images for message in verification)
    serialized = json.dumps([message.model_dump(mode="json") for message in verification])
    for private in ("selected_layout_region", "focus_only_variant", focus.region.image_sha256, "layout_focus"):
        assert private not in serialized
    assert not llm.requests and eda.flow_calls == 0 and not events
