"""Network-free tests for NVIDIA streaming, tools, and provider selection."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from app.utils import nvidia_client, nvidia_agent, ai_tools


class Socket:
    def __init__(self):
        self.events = []

    async def send_json(self, event):
        self.events.append(event)


def test_only_nvidia_key_is_needed():
    # A fresh process verifies configuration without inheriting imported constants.
    import os
    import subprocess
    import sys
    env = dict(os.environ, NVIDIA_API_KEY="test-nvidia", SENTRY_DSN="")
    script = "from app.config import NVIDIA_API_KEY, NVIDIA_MODEL; assert NVIDIA_API_KEY; print(NVIDIA_MODEL)"
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "nvidia/nemotron-3-ultra-550b-a55b"


def test_stream_parser_and_payload(monkeypatch):
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, text=(
            ': keepalive\n\ndata: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        ))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(nvidia_client, "NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(nvidia_client.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handle)))
    async def run():
        return [item async for item in nvidia_client.stream_chat([{"role": "user", "content": "hi"}], [])]
    events = asyncio.run(run())
    assert events[0]["choices"][0]["delta"]["content"] == "Hello"
    assert captured[0]["stream"] is True
    assert captured[0]["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert "tools" not in captured[0]


def test_aborted_stream_is_rejected(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(nvidia_client, "NVIDIA_API_KEY", "test-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text='data: {"choices":[]}\n\n'))
    monkeypatch.setattr(nvidia_client.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport))
    async def run():
        return [item async for item in nvidia_client.stream_chat([], [])]
    with pytest.raises(RuntimeError, match="completion marker"):
        asyncio.run(run())


def test_fragmented_tool_call_preserves_user_and_result(monkeypatch):
    seen = []
    user = {"id": "user-a"}
    def execute(current_user, name):
        seen.append((current_user, name))
        return {"ok": True, "name": name}
    monkeypatch.setattr(ai_tools, "TOOLS", {"lookup": {
        "function": execute, "properties": {"name": {"type": "STRING"}},
        "required": ["name"], "description": "Lookup", "mutation": "read", "scope": "projects",
    }})
    rounds = []
    async def stream(messages, tools):
        rounds.append(json.loads(json.dumps(messages)))
        assert tools[0]["function"]["parameters"]["properties"]["name"]["type"] == "string"
        if len(rounds) == 1:
            yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-a", "function": {"name": "lookup", "arguments": '{"name":'}}]}}]}
            yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"example"}'}}]}, "finish_reason": "tool_calls"}]}
        else:
            assert messages[-1]["role"] == "tool"
            assert messages[-1]["tool_call_id"] == "call-a"
            yield {"choices": [{"delta": {"content": "Found it"}, "finish_reason": "stop"}]}
    monkeypatch.setattr(nvidia_client, "stream_chat", stream)
    socket = Socket()
    assert asyncio.run(nvidia_agent.run_nvidia_turn(socket, "lookup", "context", user)) == "Found it"
    assert seen == [(user, "example")]


@pytest.mark.parametrize("approved", [False, True])
def test_mutations_require_approval(monkeypatch, approved):
    executed = []
    def execute(user):
        executed.append(user["id"])
        return {"ok": True}
    monkeypatch.setattr(ai_tools, "TOOLS", {"delete_item": {
        "function": execute, "properties": {}, "required": [], "description": "Delete",
        "mutation": "change", "scope": "projects",
    }})
    approval = AsyncMock(return_value=approved)
    monkeypatch.setattr(ai_tools, "_ask_approval", approval)
    rounds = []
    async def stream(messages, tools):
        rounds.append(1)
        if len(rounds) == 1:
            yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "delete_item", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"content": "Done"}, "finish_reason": "stop"}]}
    monkeypatch.setattr(nvidia_client, "stream_chat", stream)
    socket = Socket()
    asyncio.run(nvidia_agent.run_nvidia_turn(socket, "delete", "context", {"id": "a"}))
    approval.assert_awaited_once()
    assert executed == (["a"] if approved else [])
    assert any(event["type"] == "data_changed" for event in socket.events) is approved


def test_incomplete_tool_call_never_executes(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(ai_tools, "_ask_approval", execute)
    async def stream(messages, tools):
        yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c", "function": {"name": "delete_project", "arguments": "{}"}}]}, "finish_reason": "length"}]}
    monkeypatch.setattr(nvidia_client, "stream_chat", stream)
    socket = Socket()
    asyncio.run(nvidia_agent.run_nvidia_turn(socket, "delete", "", {"id": "a"}))
    execute.assert_not_awaited()
    assert socket.events[-1]["type"] == "error"


def test_briefing_uses_nvidia(monkeypatch):
    from app.api import gemini
    monkeypatch.setattr(nvidia_client, "NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(gemini, "gather_user_context", AsyncMock(return_value="calendar context"))
    generate = AsyncMock(return_value="Your briefing")
    monkeypatch.setattr(nvidia_client, "generate_text", generate)
    result = asyncio.run(gemini.generate_briefing({"id": "a", "email": "test@example.com"}))
    assert result["briefing"] == "Your briefing"
    assert "calendar context" in generate.await_args.args[0]


def test_quota_message_does_not_expose_provider_body():
    request = httpx.Request("POST", nvidia_client.URL)
    response = httpx.Response(429, request=request, text="secret-provider-response")
    error = httpx.HTTPStatusError("secret", request=request, response=response)
    assert "quota" in nvidia_client.describe_nvidia_error(error)
    assert "secret" not in nvidia_client.describe_nvidia_error(error)


def test_websocket_routes_to_nvidia_and_persists(monkeypatch):
    from app.websockets import ai_stream
    from fastapi import WebSocketDisconnect
    class ChatSocket(Socket):
        async def accept(self):
            pass

        async def receive_json(self):
            if hasattr(self, "received"):
                raise WebSocketDisconnect()
            self.received = True
            return {"prompt": "Hello"}

    monkeypatch.setattr(ai_stream, "NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(ai_stream, "gather_user_context", AsyncMock(return_value="test context"))
    monkeypatch.setattr(ai_stream, "persist_conversation_message", lambda *args: True)
    generate = AsyncMock(return_value="Hello back")
    monkeypatch.setattr(ai_stream, "run_nvidia_turn", generate)
    socket = ChatSocket()
    asyncio.run(ai_stream.websocket_ai_stream(socket, {"id": "a", "email": "test@example.com"}))
    generate.assert_awaited_once()
    assert [event["type"] for event in socket.events] == ["start", "done"]


def test_upload_rejected_for_text_only_provider(monkeypatch):
    from app.api import gemini
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        gemini.upload_to_ai(file=None, current_user={"id": "a"})
    assert error.value.status_code == 400
    assert "text only" in error.value.detail
