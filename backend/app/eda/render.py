from pathlib import Path
import struct

from pydantic import JsonValue

from app.eda.sandbox import safe_artifact


def render_layout(output_dir: Path, run_tag: str, top: str, run_id: str) -> dict[str, JsonValue]:
    # Classic runs KLayout.Render on its real GDS; expose that recorded render.
    path = safe_artifact(output_dir, output_dir / "runs" / run_tag / "final/render" / f"{top}.png")
    if not path.is_file():
        return {"ok": False, "error": "KLayout render not available"}
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return {"ok": False, "error": "KLayout render is not a PNG"}
    width, height = struct.unpack(">II", header[16:24])
    if not width or not height:
        return {"ok": False, "error": "KLayout render is empty"}
    return {"ok": True, "image_url": f"/api/runs/{run_id}/layout/{run_tag}.png", "path": str(path), "width": width, "height": height}
