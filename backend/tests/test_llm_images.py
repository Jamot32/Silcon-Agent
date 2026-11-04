"""Transport-only tests: no real model requests or CLI execution."""
import asyncio
import base64
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from openai.types.chat import ChatCompletion
from PIL import Image
import pytest
from pydantic import ValidationError

from app.llm.client import MetaLLM
from app.llm.codex import CodexCLIClient, wrapped_prompt
from app.llm.types import Budget, ImageInput, Message


def pixels(label="full_layout"):
    stream = BytesIO()
    Image.new("RGB", (16, 8), "blue").save(stream, format="PNG")
    return ImageInput(label=label, data=base64.b64encode(stream.getvalue()).decode())


@pytest.mark.parametrize("value", ["not base64!", base64.b64encode(b"not a png").decode(), "a" * 2_796_205])
def test_image_input_rejects_invalid_and_oversized_payload(value):
    with pytest.raises(ValidationError):
        ImageInput(label="full_layout", data=value)


def test_only_user_messages_have_bounded_images_and_trace_digests():
    item = pixels()
    with pytest.raises(ValidationError): Message(role="system", content="test", images=[item])
    with pytest.raises(ValidationError): Message(role="user", content="test", images=[item] * 3)
    message = Message(role="user", content="Look at these actual pixels", images=[item])
    plain = message.trace_dump()
    assert plain["images"] == [item.metadata()]
    assert item.data not in json.dumps(plain)
    assert "data" not in repr(item)
    assert item.data not in wrapped_prompt([message], [])[1]


def test_meta_sends_actual_base64_pixels_as_image_parts_without_tools(monkeypatch):
    monkeypatch.setenv("META_MODEL", "muse-spark-1.3")
    monkeypatch.setenv("META_REASONING_EFFORT", "medium")
    sdk = MagicMock()
    sdk.chat.completions.create = AsyncMock(return_value=ChatCompletion.model_validate({
        "id": "offline", "object": "chat.completion", "created": 0, "model": "muse-spark-1.3",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Blue region"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}))
    images = [pixels(), pixels("selected_region")]
    budget = Budget(max_calls=1, max_tokens=1000)
    result = asyncio.run(MetaLLM(client=sdk, budget=budget).complete([Message(role="user", content="Inspect region", images=images)], []))
    request = sdk.chat.completions.create.call_args.kwargs
    assert request["messages"][0]["content"] == [{"type": "text", "text": "Inspect region"}, *[
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image.data}"}} for image in images]]
    assert "tools" not in request
    assert budget.calls == 1 and result.content == "Blue region"


@pytest.mark.usefixtures("configured_codex_transport")
def test_codex_attaches_private_png_files_without_changing_read_boundary(monkeypatch):
    images = [pixels(), pixels("selected_region")]
    paths = []
    client = CodexCLIClient(executable="/test/codex", budget=Budget(max_calls=1))
    async def checked(*args): pass
    async def request(args, prompt, env, incoming, boundary):
        assert boundary.command(args).cwd == boundary.private_cwd
        assert list(Path(boundary.private_cwd).iterdir()) == []
        assert "view_image" in args and "--sandbox" in args and "read-only" in args
        image_paths = [Path(args[index + 1]) for index, value in enumerate(args) if value == "--image"]
        assert len(image_paths) == 2  # Identical full/crop pixels still retain both image roles.
        for image, path in zip(images, image_paths):
            assert path.read_bytes() == base64.b64decode(image.data)
            assert path.stat().st_mode & 0o777 == 0o600
            assert path.parent == Path(args[args.index("--cd") + 1])
            assert not path.is_relative_to(Path(boundary.original_project_root))
            assert image.data not in prompt
        paths.extend(image_paths)
        incoming({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"content": "Blue pixels", "tool_calls": []})}})
        incoming({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 20}})
    monkeypatch.setattr(client, "_check_cli", checked)
    monkeypatch.setattr(client, "_request", request)
    result = asyncio.run(client.complete([Message(role="user", content="Inspect actual pixels", images=images)], []))
    assert result.content == "Blue pixels"
    assert len(paths) == 2 and not any(path.exists() for path in paths)
