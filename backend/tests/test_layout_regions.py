"""Offline raster evidence checks; no model, GDS parser or EDA process runs."""
import base64
import hashlib
from io import BytesIO
import os
import struct
import zlib

from PIL import Image, PngImagePlugin
import pytest
from pydantic import ValidationError
from sqlmodel import Session, select

from app import layout_regions
from app.layout_region_types import LayoutRegionInput
from app.layout_regions import prepare_layout_region
from app.models import Artifact
from app.storage import RunStore


@pytest.fixture
def database(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run("Inspect recorded layout pixels offline.")
    return store, run


def selection(tag="flow_one", **bounds):
    return LayoutRegionInput(run_tag=tag, bounds={"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75, **bounds})


def register(database, tag="flow_one", size=(8, 4)):
    store, run = database
    path = store.work_dir(run.id) / f"{tag}.png"
    # Unique raster coordinates make y inversion and off-by-one errors observable.
    image = Image.new("RGB", size)
    image.putdata([(x % 256, y % 256, 73) for y in range(size[1]) for x in range(size[0])])
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "Private metadata must not be sent to the model")
    image.save(path, pnginfo=metadata)
    store.register_artifact(run.id, "layout", path, tag)
    return path


def png(prepared, index):
    return Image.open(BytesIO(base64.b64decode(prepared.images[index].data, validate=True)))


def test_region_binds_exact_source_and_crop_pixels_without_metadata(database):
    path = register(database)
    original = path.read_bytes()
    prepared = prepare_layout_region(*database, selection())
    context = prepared.region
    assert context.source_run_id == database[1].id and context.run_tag == "flow_one"
    assert context.coordinate_space == "image_normalized_top_left"
    assert context.image_sha256 == hashlib.sha256(original).hexdigest()
    assert (context.image_width, context.image_height) == (8, 4)
    assert context.pixel_bounds.model_dump() == {"x0": 2, "y0": 1, "x1": 6, "y1": 3}
    assert [image.label for image in prepared.images] == ["full_layout", "selected_region"]
    full, crop = png(prepared, 0), png(prepared, 1)
    assert full.size == (8, 4) and crop.size == (4, 2)
    assert crop.getpixel((0, 0)) == (2, 1, 73)
    assert crop.getpixel((3, 1)) == (5, 2, 73)
    assert full.getpixel((7, 3)) == (7, 3, 73)
    assert not full.info and not crop.info
    assert path.read_bytes() == original
    assert str(path) not in prepared.model_dump_json()
    assert "Private metadata" not in prepared.model_dump_json()


def test_fractional_edges_enclose_pixels_and_full_bounds_preserve_orientation(database):
    register(database)
    tiny = prepare_layout_region(*database, selection(x0=0.999, x1=1.0, y0=0.999, y1=1.0))
    assert png(tiny, 1).size == (1, 1)
    assert png(tiny, 1).getpixel((0, 0)) == (7, 3, 73)
    whole = prepare_layout_region(*database, selection(x0=0, y0=0, x1=1, y1=1))
    assert png(whole, 0).tobytes() == png(whole, 1).tobytes()


@pytest.mark.parametrize("bounds", [
    {"x0": -0.1}, {"x1": 1.1}, {"x0": 0.75}, {"x0": 0.9},
    {"y0": 0.75}, {"x0": float("nan")}, {"x1": float("inf")},
    {"x0": True}, {"y0": "0.1"}, {"width": 0.5},
])
def test_invalid_bounds_are_rejected(bounds):
    with pytest.raises(ValidationError):
        selection(**bounds)


@pytest.mark.parametrize("tag", ["../x", ".", "..", "a/b", "a\\b", "", "x" * 97, "x\n"])
def test_invalid_tags_are_rejected(tag):
    with pytest.raises(ValidationError):
        selection(tag)


def test_unknown_variant_never_falls_back_to_registered_layout(database):
    register(database)
    with pytest.raises(KeyError):
        prepare_layout_region(*database, selection("flow_other"))
    database[0].fail(database[1].id, "Fixture completed")
    other = database[0].create_run("A different run")
    with pytest.raises(KeyError):
        prepare_layout_region(database[0], other, selection())


def test_digest_pin_rejects_changed_artifact(database):
    path = register(database)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    request = selection().model_copy(update={"expected_image_sha256": digest})
    assert prepare_layout_region(*database, request).region.image_sha256 == digest
    Image.new("RGB", (8, 4), "red").save(path)
    with pytest.raises(ValueError, match="changed"):
        prepare_layout_region(*database, request)


@pytest.mark.parametrize("contents", [b"not PNG", b"\x89PNG\r\n\x1a\n", b"<svg/>off-path-reference"])
def test_corrupt_or_non_png_is_rejected(database, contents):
    register(database).write_bytes(contents)
    with pytest.raises(ValueError):
        prepare_layout_region(*database, selection())


def test_png_crc_corruption_is_rejected(database):
    path = register(database)
    contents = bytearray(path.read_bytes())
    offset = contents.index(b"IDAT")
    contents[offset + 5] ^= 0xFF
    path.write_bytes(contents)
    with pytest.raises(ValueError):
        prepare_layout_region(*database, selection())


@pytest.mark.parametrize("size", [(4001, 4000), (16385, 1)])
def test_decode_bounds_are_checked_before_pixel_allocation(database, size):
    path = register(database)
    contents = bytearray(path.read_bytes())
    contents[16:24] = struct.pack(">II", *size)
    contents[29:33] = struct.pack(">I", zlib.crc32(contents[12:29]))
    path.write_bytes(contents)
    with pytest.raises(ValueError, match="dimensions"):
        prepare_layout_region(*database, selection())


def test_animated_png_is_rejected(database):
    path = register(database)
    Image.new("RGB", (8, 4), "red").save(path, save_all=True, append_images=[Image.new("RGB", (8, 4), "blue")])
    with pytest.raises(ValueError, match="Animated"):
        prepare_layout_region(*database, selection())


def test_source_file_size_is_bounded(database):
    path = register(database)
    with path.open("r+b") as file:
        file.truncate(layout_regions.MAX_LAYOUT_BYTES + 1)
    with pytest.raises(ValueError, match="bounded"):
        prepare_layout_region(*database, selection())


@pytest.mark.parametrize("alias", ["symlink", "hardlink", "directory", "fifo"])
def test_registered_path_cannot_be_replaced_by_alias_or_special_file(database, alias):
    path = register(database)
    moved = path.with_suffix(".source")
    path.rename(moved)
    if alias == "symlink":
        path.symlink_to(moved)
    elif alias == "hardlink":
        os.link(moved, path)
    elif alias == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(ValueError):
        prepare_layout_region(*database, selection())


@pytest.mark.parametrize("path", ["../outside.png", "/tmp/outside.png", "work//flow_one.png", "work/../flow_one.png"])
def test_unsafe_database_paths_are_not_resolved(database, path):
    register(database)
    store, run = database
    with Session(store.engine) as session:
        artifact = session.exec(select(Artifact).where(Artifact.run_id == run.id)).one()
        artifact.path = path
        session.add(artifact)
        session.commit()
    with pytest.raises(ValueError, match="Invalid layout"):
        prepare_layout_region(*database, selection())


def test_intermediate_directory_symlink_is_rejected(database):
    path = register(database)
    moved = path.parent.with_name("moved-work")
    path.parent.rename(moved)
    path.parent.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_layout_region(*database, selection())


def test_changing_file_during_read_is_rejected(database, monkeypatch):
    path = register(database)
    read = os.read
    changed = False

    def changing_read(descriptor, count):
        nonlocal changed
        contents = read(descriptor, count)
        if not changed:
            changed = True
            with path.open("ab") as file:
                file.write(b"changed")
        return contents

    monkeypatch.setattr(layout_regions.os, "read", changing_read)
    with pytest.raises(ValueError, match="changed while reading"):
        prepare_layout_region(*database, selection())


def test_vision_payload_size_and_dimensions_are_bounded(database, monkeypatch):
    path = register(database)
    # Deterministic high-entropy pixels exercise size-based downsampling.
    raw = b"".join(hashlib.sha256(str(index).encode()).digest() for index in range(6144))
    Image.frombytes("RGB", (256, 256), raw).save(path)
    monkeypatch.setattr(layout_regions, "MAX_VISION_IMAGE_BYTES", 10_000)
    monkeypatch.setattr(layout_regions, "MAX_VISION_SIDE", 200)
    prepared = prepare_layout_region(*database, selection(x0=0, y0=0, x1=1, y1=1))
    assert prepared.region.image_width == 256
    for index, image in enumerate(prepared.images):
        assert len(base64.b64decode(image.data)) <= 10_000
        assert 0 < image.width <= 200 and 0 < image.height <= 200
        assert png(prepared, index).size == (image.width, image.height)


def test_transparent_source_preserves_visible_pixels(database):
    path = register(database)
    Image.new("RGBA", (8, 4), (10, 20, 30, 40)).save(path)
    prepared = prepare_layout_region(*database, selection())
    assert png(prepared, 1).getpixel((0, 0)) == (10, 20, 30, 40)
