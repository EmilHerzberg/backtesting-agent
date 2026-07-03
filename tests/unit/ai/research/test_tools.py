"""Tests for ATS-1761/1762/1763 — Agent tool interface."""

import pytest

from src.backend.ai.research.tools import AgentToolInterface


@pytest.fixture
def tool_iface():
    iface = AgentToolInterface()
    iface.register("list_templates", lambda: ["sma", "rsi", "macd"])
    iface.register("validate_spec", lambda spec: {"valid": True})
    return iface


class TestAgentToolInterface:
    def test_whitelisted_tool_allowed(self, tool_iface):
        result = tool_iface.call("list_templates", {}, agent="test")
        assert result == ["sma", "rsi", "macd"]

    def test_unknown_tool_denied(self, tool_iface):
        with pytest.raises(PermissionError, match="not whitelisted"):
            tool_iface.call("execute_code", {"code": "rm -rf /"}, agent="test")

    def test_forbidden_tool_cannot_register(self):
        iface = AgentToolInterface()
        with pytest.raises(ValueError, match="forbidden"):
            iface.register("execute_code", lambda: None)

    def test_denial_logged(self, tool_iface):
        with pytest.raises(PermissionError):
            tool_iface.call("read_raw_data", {}, agent="bad_agent")
        log = tool_iface.audit_log
        assert len(log) == 1
        assert log[0].allowed is False
        assert "not in whitelist" in log[0].denial_reason

    def test_all_calls_logged(self, tool_iface):
        tool_iface.call("list_templates", {}, agent="test")
        tool_iface.call("validate_spec", {"spec": {}}, agent="test")
        assert len(tool_iface.audit_log) == 2
        assert all(r.allowed for r in tool_iface.audit_log)

    def test_log_includes_latency(self, tool_iface):
        tool_iface.call("list_templates", {}, agent="test")
        assert tool_iface.audit_log[0].latency_ms >= 0

    def test_blob_refs_are_sha256(self, tool_iface):
        tool_iface.call(
            "list_templates", {},
            agent="test", prompt_text="hello", response_text="world",
        )
        record = tool_iface.audit_log[0]
        assert len(record.prompt_blob_ref) == 64
        assert len(record.response_blob_ref) == 64

    def test_registered_tools_list(self, tool_iface):
        tools = tool_iface.registered_tools
        assert "list_templates" in tools
        assert "validate_spec" in tools
        assert "execute_code" not in tools

    def test_call_with_arguments(self, tool_iface):
        result = tool_iface.call("validate_spec", {"spec": {"template": "sma"}}, agent="test")
        assert result == {"valid": True}
