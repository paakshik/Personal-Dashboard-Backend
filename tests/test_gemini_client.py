from app.utils.gemini_helper import create_gemini_client, stream_gemini_response
from unittest.mock import AsyncMock, patch


def test_gemini_client_requests_v1beta(monkeypatch):
    monkeypatch.setattr("app.utils.gemini_helper.GEMINI_API_KEY", "test-key")
    client = create_gemini_client()
    assert client._api_client._http_options.api_version == "v1beta"


def test_empty_gemini_stream_reports_error():
    class EmptyStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            return EmptyStream()

    class FakeClient:
        class Aio:
            models = FakeModels()
        aio = Aio()

    class FakeSocket:
        send_json = AsyncMock()

    socket = FakeSocket()
    with patch("app.utils.gemini_helper.create_gemini_client", return_value=FakeClient()):
        import asyncio
        result = asyncio.run(stream_gemini_response(socket, "model", ["hi"], None))
    assert result == ""
    assert socket.send_json.await_args.args[0]["type"] == "error"
