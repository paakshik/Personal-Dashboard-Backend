"""NVIDIA's hosted, OpenAI-compatible chat API. No automatic request replay."""
import json
import httpx
from app.config import NVIDIA_API_KEY, NVIDIA_MODEL

URL = "https://integrate.api.nvidia.com/v1/chat/completions"
TIMEOUT = httpx.Timeout(180.0, connect=15.0)


def require_nvidia_key():
    if not NVIDIA_API_KEY:
        raise RuntimeError("Set NVIDIA_API_KEY on the backend to use Nemotron.")


def describe_nvidia_error(exc):
    if isinstance(exc, RuntimeError) and not NVIDIA_API_KEY:
        return "Nemotron is not configured. Set NVIDIA_API_KEY on the backend and restart."
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "NVIDIA rejected the API key or model access. Check the backend NVIDIA configuration."
        if code == 429:
            return "NVIDIA API quota or rate limit reached. Check your NVIDIA account and retry later."
        if code == 404:
            return "NVIDIA model not found. Check NVIDIA_MODEL and your account's model access."
    if isinstance(exc, httpx.TimeoutException):
        return "Nemotron took too long to respond. Please retry."
    return "Nemotron could not complete the response. Please retry or check the backend logs."


def _payload(messages, stream, tools=None):
    payload = {
        "model": NVIDIA_MODEL,
        "messages": messages,
        "stream": stream,
        "max_tokens": 4096,
        "temperature": 0.2,
        # Only final answers should reach the chat UI, not reasoning traces.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tools:
        payload.update(tools=tools, tool_choice="auto")
    return payload


async def stream_chat(messages, tools):
    """Yield complete SSE JSON events, including tool-call argument fragments."""
    require_nvidia_key()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream(
            "POST", URL,
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Accept": "text/event-stream"},
            json=_payload(messages, True, tools),
        ) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError("NVIDIA did not return a completed streaming response")
            data = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    event = "\n".join(data)
                    data = []
                    if event == "[DONE]":
                        return
                    value = json.loads(event)
                    if "error" in value:
                        raise RuntimeError("NVIDIA reported a stream error")
                    yield value
            # Never execute tools from an incomplete/aborted stream.
            raise RuntimeError("NVIDIA stream ended without a completion marker")


async def generate_text(instruction):
    require_nvidia_key()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            URL,
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}"},
            json=_payload([{"role": "user", "content": instruction}], False),
        )
        response.raise_for_status()
        if response.status_code != 200:
            raise RuntimeError("NVIDIA response is pending")
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise RuntimeError("NVIDIA briefing did not finish")
        text = choice["message"].get("content") or ""
        if not text.strip():
            raise RuntimeError("NVIDIA returned an empty briefing")
        return text
