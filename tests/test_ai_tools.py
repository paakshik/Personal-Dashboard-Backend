from app.utils import ai_tools


def test_saved_command_tool_never_executes_text(monkeypatch):
    created = {}
    monkeypatch.setattr(ai_tools, "save_command", lambda user_id, payload, command_id=None: created.update(payload) or {"id": "c1", **payload})
    result = ai_tools.create_command_tool({"id": "u1"}, "backup", "echo hello")
    assert result["ok"] is True
    assert created["command"] == "echo hello"
    rejected = ai_tools.create_command_tool({"id": "u1"}, "bad", "echo hello; whoami")
    assert rejected["ok"] is False


def test_resolve_ambiguous_names_requires_clarification():
    items = [{"id": "1", "name": "Planning"}, {"id": "2", "name": "Planning"}]
    item, error = ai_tools.resolve_by_ref(items, "planning")
    assert item is None
    assert "Several items matched" in error
