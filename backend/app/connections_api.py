"""Local settings API. Responses contain credential presence only, never keys."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.provider_credentials import PROVIDER_ENV, effective_key, remove_key, save_key, saved_key
from app.request_guard import app_request
from app.subscription_status import read_subscriptions


router = APIRouter(prefix="/api/settings/connections", dependencies=[Depends(app_request)])


def connection(request: Request, provider: str) -> dict:
    if provider not in PROVIDER_ENV:
        raise HTTPException(404, "Unknown provider")
    root = request.app.state.store.root
    try:
        source = "saved" if saved_key(root, provider) else "environment" if effective_key(root, provider) else "none"
    except OSError:
        raise HTTPException(503, "Provider key storage is unavailable") from None
    return {"provider": provider, "source": source, "configured": source != "none", "build_supported": provider == "meta"}


@router.get("")
def connections(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"keys": [connection(request, provider) for provider in PROVIDER_ENV],
            "subscriptions": read_subscriptions(request.app.state.store.root).model_dump()}


@router.put("/{provider}")
async def put_connection(provider: str, request: Request, response: Response) -> dict:
    connection(request, provider)
    # Do not use FastAPI's default validation errors: those echo submitted input.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise HTTPException(422, "API key request is too large")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Expected an API key") from None
    key = value.get("api_key") if isinstance(value, dict) and set(value) == {"api_key"} else None
    if not isinstance(key, str) or not 8 <= len(key.strip()) <= 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key.strip()):
        raise HTTPException(422, "Enter a valid API key (8–4096 characters, without spaces)")
    try:
        save_key(request.app.state.store.root, provider, key.strip())
    except OSError:
        raise HTTPException(503, "Provider key could not be saved") from None
    response.headers["Cache-Control"] = "no-store"
    return connection(request, provider)


@router.delete("/{provider}")
def delete_connection(provider: str, request: Request, response: Response) -> dict:
    connection(request, provider)
    try:
        remove_key(request.app.state.store.root, provider)
    except OSError:
        raise HTTPException(503, "Provider key could not be removed") from None
    response.headers["Cache-Control"] = "no-store"
    return connection(request, provider)
