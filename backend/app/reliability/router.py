"""Read-only aggregate route. No evaluator, verifier or model work runs here."""
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from .public import NotFound, PublicExportError, load_admin

router = APIRouter()


@router.get("/api/admin/reliability")
def reliability(response: Response) -> dict:
    # Check the server-owned flag before even constructing/opening the export root.
    if os.getenv("SILICON_DEV_RELIABILITY_ADMIN", "0") != "1":
        raise HTTPException(404, "Not found")
    root = Path(os.getenv("RUNS_DIR", "runs")) / "reliability-public"
    try:
        result = load_admin(root, enabled=True)
    except NotFound:
        raise HTTPException(404, "Not found") from None
    except PublicExportError:
        raise HTTPException(503, "Reliability reports are unavailable") from None
    response.headers["Cache-Control"] = "no-store"
    return result
