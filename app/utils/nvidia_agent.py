"""Adapt the existing user-scoped tool registry to NVIDIA chat tool calls."""
import asyncio
import json
from app.config import logger
from app.utils import nvidia_client
from app.utils.ai_context import _safe_send


def _schema(value):
    if isinstance(value, list):
        return [_schema(item) for item in value]
    if isinstance(value, dict):
        return {key: item.lower() if key == "type" and isinstance(item, str)
                else _schema(item) for key, item in value.items()}
    return value


def tool_definitions(registry):
    return [{"type": "function", "function": {
        "name": name, "description": spec["description"],
        "parameters": {"type": "object", "properties": _schema(spec["properties"]),
                       "required": list(spec["required"])},
    }} for name, spec in registry.items()]


async def run_nvidia_turn(websocket, prompt, instruction, user):
    # Lazy import keeps the registry independent of provider initialization.
    from app.utils.ai_tools import TOOLS, RULES, MAX_TOOL_ROUNDS, _ask_approval, _run_tool, fail
    messages = [{"role": "system", "content": f"{instruction}\n\n{RULES}\n"
                 "Live web search and file attachments are unavailable. Do not claim to have searched the web."},
                {"role": "user", "content": prompt}]
    full_text = ""
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            calls, turn_text, finish = {}, "", None
            async for event in nvidia_client.stream_chat(messages, tool_definitions(TOOLS)):
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish = choice.get("finish_reason") or finish
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    if not await _safe_send(websocket, {"type": "chunk", "text": text}):
                        return full_text
                    full_text += text
                    turn_text += text
                for fragment in delta.get("tool_calls") or []:
                    index = fragment["index"]
                    if not isinstance(index, int) or not 0 <= index < 32:
                        raise ValueError("Invalid tool call index")
                    call = calls.setdefault(index, {"id": "", "type": "function",
                                                   "function": {"name": "", "arguments": ""}})
                    call["id"] += fragment.get("id") or ""
                    for key in ("name", "arguments"):
                        call["function"][key] += (fragment.get("function") or {}).get(key) or ""
                    if len(call["function"]["arguments"]) > 65536:
                        raise ValueError("Tool arguments too large")
            if finish not in ("stop", "tool_calls"):
                raise RuntimeError("NVIDIA response was truncated or incomplete")
            if not calls:
                if not turn_text.strip():
                    raise RuntimeError("NVIDIA returned no answer")
                return full_text
            # Validate every call before executing any of them.
            ordered = [calls[index] for index in sorted(calls)]
            parsed, ids = [], set()
            for call in ordered:
                if not call["id"] or call["id"] in ids:
                    raise ValueError("Missing or duplicate tool call identifier")
                ids.add(call["id"])
                args = json.loads(call["function"]["arguments"] or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be an object")
                parsed.append(args)
            messages.append({"role": "assistant", "content": turn_text or None, "tool_calls": ordered})
            for call, args in zip(ordered, parsed):
                name = call["function"]["name"]
                spec = TOOLS.get(name)
                if spec is None:
                    result = fail(f"Unknown tool: {name}")
                elif spec["mutation"] == "change" and not await _ask_approval(
                    websocket, call["id"], name, user, args
                ):
                    result = fail("User declined or approval timed out. No change was made.")
                else:
                    result = await asyncio.to_thread(_run_tool, spec, user, args)
                    if spec["mutation"] != "read":
                        if result.get("ok"):
                            await _safe_send(websocket, {"type": "data_changed", "scope": spec["scope"]})
                        else:
                            await _safe_send(websocket, {"type": "error", "message": result.get("error", "Tool failed.")})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)})
        await _safe_send(websocket, {"type": "error", "message": "Stopped after too many tool steps. Try a simpler request."})
    except Exception as exc:
        # Never log provider response bodies, prompts, credentials or tool arguments.
        logger.error("NVIDIA turn failed (%s)", type(exc).__name__)
        await _safe_send(websocket, {"type": "error", "message": nvidia_client.describe_nvidia_error(exc)})
    return full_text
