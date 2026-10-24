"""Public aggregate/HTTP controls. The fixture contains sealed aggregates only."""
from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.reliability.public import NotFound, PublicExportError, load_admin
from app.reliability.router import router
from app.reliability.safeio import Files, canonical, decode, sha

FIXTURE = Path(__file__).parent / "fixtures/reliability/public-response.actual.json"


def publish_fixture(root: Path):
    response = json.loads(FIXTURE.read_text())
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in response["cohorts"]:
        raw = canonical(item) + b"\n"
        name = item["cohort_id"] + ".json"
        (root / name).write_bytes(raw)
        rows.append({"cohort_id": item["cohort_id"], "path": name, "sha256": sha(raw),
                     **{key: item["binding"][key] for key in ("summary_sha256", "seal_sha256")}})
    (root / "index.json").write_bytes(canonical({"schema_version": 1, "exports": rows}))
    return response


def test_loader_preserves_actual_sealed_aggregates_and_unknown_usd(tmp_path):
    expected = publish_fixture(tmp_path)
    actual = load_admin(tmp_path, enabled=True)
    assert actual == expected
    assert len(actual["cohorts"]) == 3
    for cohort in actual["cohorts"]:
        assert cohort["report"]["cost"]["total_usd"] is None
        assert cohort["report"]["unknown_cost_trials"] == 90
    assert "eval/results" not in json.dumps(actual)


def test_disabled_loader_does_not_open_anything():
    with patch.object(Files, "read", side_effect=AssertionError("must not open")):
        with pytest.raises(NotFound):
            load_admin("/unavailable", enabled=False)


@pytest.mark.parametrize("change", [
    lambda i: i["exports"].append(deepcopy(i["exports"][0])),
    lambda i: i["exports"][0].update(path="../private.json"),
    lambda i: i["exports"][0].update(sha256="0" * 64),
    lambda i: i.update(private="never copied"),
    lambda i: i.update(schema_version=True),
])
def test_invalid_index_is_unavailable_not_empty(tmp_path, change):
    publish_fixture(tmp_path)
    index = decode((tmp_path / "index.json").read_bytes())
    change(index)
    (tmp_path / "index.json").write_bytes(canonical(index))
    with pytest.raises(PublicExportError):
        load_admin(tmp_path, enabled=True)


@pytest.mark.parametrize("raw", [b'{"schema_version":1,"schema_version":1}', b'{"value":NaN}', b'{"value":1e400}'])
def test_duplicate_and_nonfinite_json_rejected(raw):
    with pytest.raises(ValueError):
        decode(raw)


@pytest.mark.parametrize("mode", ["symlink", "hardlink"])
def test_export_alias_rejected(tmp_path, mode):
    publish_fixture(tmp_path)
    row = decode((tmp_path / "index.json").read_bytes())["exports"][0]
    target = tmp_path / row["path"]
    other = tmp_path / "outside"
    target.rename(other)
    if mode == "symlink":
        target.symlink_to(other)
    else:
        os.link(other, target)
    with pytest.raises(PublicExportError):
        load_admin(tmp_path, enabled=True)


def test_nested_private_field_rejected_even_with_matching_file_hash(tmp_path):
    publish_fixture(tmp_path)
    index = decode((tmp_path / "index.json").read_bytes())
    row = index["exports"][0]
    item = decode((tmp_path / row["path"]).read_bytes())
    item["report"]["cost"]["private_log"] = "PRIVATE_SENTINEL"
    raw = canonical(item)
    (tmp_path / row["path"]).write_bytes(raw)
    row["sha256"] = sha(raw)
    (tmp_path / "index.json").write_bytes(canonical(index))
    with pytest.raises(PublicExportError):
        load_admin(tmp_path, enabled=True)


def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_http_default_disabled_before_filesystem_access(monkeypatch):
    monkeypatch.delenv("SILICON_DEV_RELIABILITY_ADMIN", raising=False)
    with patch.object(Files, "read", side_effect=AssertionError("must not open")):
        response = client().get("/api/admin/reliability")
    assert response.status_code == 404


def test_http_enabled_empty_loaded_and_corrupt_states(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("SILICON_DEV_RELIABILITY_ADMIN", "1")
    with client() as browser:
        empty = browser.get("/api/admin/reliability")
        assert empty.status_code == 200 and empty.json()["state"] == "empty"
        expected = publish_fixture(tmp_path / "reliability-public")
        loaded = browser.get("/api/admin/reliability?path=/private&enabled=false")
        assert loaded.status_code == 200 and loaded.json() == expected
        assert loaded.headers["cache-control"] == "no-store"
        (tmp_path / "reliability-public/index.json").write_text('{"private":"PRIVATE_SENTINEL"}')
        corrupt = browser.get("/api/admin/reliability")
        assert corrupt.status_code == 503
        assert "PRIVATE_SENTINEL" not in corrupt.text
        assert browser.post("/api/admin/reliability").status_code == 405
