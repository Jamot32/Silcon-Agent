"""Bounded, read-only raster evidence from an exact registered layout variant.

This module does not run EDA tools or infer physical coordinates, cells or nets.
The image hash identifies original artifact bytes; provider images are decoded,
stripped of metadata, and fitted to a bounded size while retaining their content.
"""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import math
import os
from pathlib import PurePosixPath
import re
import stat
import zlib

from PIL import Image, UnidentifiedImageError
from sqlmodel import Session, select

from app.layout_region_types import (
    LayoutPixelBounds, LayoutRegionContext, LayoutRegionImage, LayoutRegionInput,
    PreparedLayoutRegion,
)
from app.models import Artifact, Run
from app.storage import RunStore

MAX_LAYOUT_BYTES = 16 * 1024 * 1024
MAX_LAYOUT_PIXELS = 16_000_000
MAX_LAYOUT_SIDE = 16_384
MAX_VISION_SIDE = 2048
MAX_VISION_IMAGE_BYTES = 2 * 1024 * 1024


def _read_layout(database: RunStore, run: Run, tag: str) -> bytes:
    # Select the exact variant, with no fallback to the newest or selected one.
    with Session(database.engine) as session:
        artifact = session.exec(select(Artifact).where(
            Artifact.run_id == run.id, Artifact.kind == "layout", Artifact.run_tag == tag,
        )).first()
        if artifact is None:
            raise KeyError("Layout variant not found")
        relative = artifact.path
    if (not re.fullmatch(r"[0-9a-f]{32}", run.id)
            or not relative or len(relative.encode()) > 1024
            or relative.startswith("/") or "\\" in relative or "\0" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise ValueError("Invalid layout artifact")
    descriptor = os.open(database.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in (run.id, *PurePosixPath(relative).parts[:-1]):
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        file_descriptor = os.open(PurePosixPath(relative).name,
                                  os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    try:
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_LAYOUT_BYTES:
            raise ValueError("Layout must be a bounded regular image file")
        chunks, size = [], 0
        while chunk := os.read(file_descriptor, 65536):
            size += len(chunk)
            if size > MAX_LAYOUT_BYTES:
                raise ValueError("Layout image exceeds the size limit")
            chunks.append(chunk)
        after = os.fstat(file_descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Layout image changed while reading")
        return b"".join(chunks)
    finally:
        os.close(file_descriptor)


def _decode(contents: bytes) -> Image.Image:
    if not contents.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Layout artifact is not a PNG image")
    with Image.open(BytesIO(contents), formats=("PNG",)) as image:
        width, height = image.size
        if (min(width, height) < 1 or max(width, height) > MAX_LAYOUT_SIDE
                or width * height > MAX_LAYOUT_PIXELS):
            raise ValueError("Layout image dimensions exceed the inspection limit")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Animated layouts are not supported")
        image.verify()
    with Image.open(BytesIO(contents), formats=("PNG",)) as image:
        image.load()
        # Preserve transparency and strip text, ICC profiles and other metadata.
        return image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")


def _vision_image(image: Image.Image, label: str) -> LayoutRegionImage:
    bounded = image.copy()
    bounded.thumbnail((MAX_VISION_SIDE, MAX_VISION_SIDE), Image.Resampling.LANCZOS)
    for _ in range(10):
        # A fresh image prevents source metadata being reattached by the encoder.
        clean = Image.new(bounded.mode, bounded.size)
        clean.paste(bounded)
        output = BytesIO()
        clean.save(output, format="PNG")
        contents = output.getvalue()
        if len(contents) <= MAX_VISION_IMAGE_BYTES:
            return LayoutRegionImage(data=base64.b64encode(contents).decode("ascii"), label=label,
                                     width=clean.width, height=clean.height)
        bounded = bounded.resize((max(1, bounded.width * 3 // 4), max(1, bounded.height * 3 // 4)),
                                 Image.Resampling.LANCZOS)
    raise ValueError("Prepared layout image exceeds the vision size limit")


def prepare_layout_region(database: RunStore, run: Run, selection: LayoutRegionInput) -> PreparedLayoutRegion:
    """Return full-layout and crop PNG pixels plus immutable source identity.

    KeyError means the run/tag has no registered layout. ValueError means a
    malformed, stale, missing or oversized image/selection. No source is changed.
    Pixel bounds enclose the selected fractional rectangle; at least one pixel
    is retained on either axis. Image dimensions never imply physical dimensions.
    """
    # Revalidate even a model constructed through trusted code without validation.
    selection = LayoutRegionInput.model_validate(selection.model_dump())
    try:
        contents = _read_layout(database, run, selection.run_tag)
        digest = hashlib.sha256(contents).hexdigest()
        if selection.expected_image_sha256 is not None and selection.expected_image_sha256 != digest:
            raise ValueError("The layout image changed; select the region again")
        image = _decode(contents)
        bounds = selection.bounds
        pixels = LayoutPixelBounds(
            x0=math.floor(bounds.x0 * image.width), y0=math.floor(bounds.y0 * image.height),
            x1=min(image.width, math.ceil(bounds.x1 * image.width)),
            y1=min(image.height, math.ceil(bounds.y1 * image.height)),
        )
        region = LayoutRegionContext(source_run_id=run.id, run_tag=selection.run_tag, bounds=bounds,
            image_sha256=digest, image_width=image.width, image_height=image.height, pixel_bounds=pixels)
        crop = image.crop((pixels.x0, pixels.y0, pixels.x1, pixels.y1))
        return PreparedLayoutRegion(region=region,
            images=[_vision_image(image, "full_layout"), _vision_image(crop, "selected_region")])
    except (OSError, EOFError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError, zlib.error) as error:
        raise ValueError("Layout image could not be read safely") from error
