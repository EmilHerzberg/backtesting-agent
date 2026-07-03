"""ATS-1761/1762/1763 — Agent tool interface with whitelist + audit logging.

The sole API surface for LLM agents. Only registered tools can be called.
Unknown calls are denied and logged. All calls logged with latency.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class ToolCallRecord:
    """Audit record for every tool call."""

    call_id: str
    agent: str
    context_id: str
    tool: str
    arguments: dict[str, Any]
    allowed: bool
    denial_reason: str | None = None
    result: Any = None
    prompt_blob_ref: str = ""
    response_blob_ref: str = ""
    latency_ms: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AgentToolInterface:
    """Constrained tool dispatcher for LLM agents.

    Only whitelisted tools can be called. All calls are logged.
    """

    # Tools that are ABSENT BY DESIGN — agents cannot call these.
    FORBIDDEN_TOOLS = frozenset({
        "read_raw_data",
        "read_oos_data",
        "read_oos_metrics",
        "execute_code",
        "modify_gate",
        "modify_threshold",
        "write_registry_directly",
        "approve_promotion",
        "render_numeric_report",
        "alter_budget",
        "delete_trial",
    })

    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._log: list[ToolCallRecord] = []
        self._frozen = False

    def register(self, name: str, fn: Callable) -> None:
        """Register a whitelisted tool. Fails after freeze()."""
        if self._frozen:
            raise RuntimeError("Tool interface is frozen — no new registrations allowed")
        if name in self.FORBIDDEN_TOOLS:
            raise ValueError(f"Cannot register forbidden tool: {name}")
        self._tools[name] = fn

    def freeze(self) -> None:
        """Lock the tool registry. No further registrations allowed."""
        self._frozen = True

    def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        agent: str = "unknown",
        context_id: str = "",
        prompt_text: str = "",
        response_text: str = "",
    ) -> Any:
        """Call a tool by name. Denied if not whitelisted.

        Returns the tool result, or raises if denied.
        """
        call_id = f"call_{uuid.uuid4().hex[:12]}"
        start = time.monotonic()

        if tool_name not in self._tools:
            record = ToolCallRecord(
                call_id=call_id,
                agent=agent,
                context_id=context_id,
                tool=tool_name,
                arguments=arguments,
                allowed=False,
                denial_reason=f"tool '{tool_name}' not in whitelist",
                prompt_blob_ref=_sha256(prompt_text) if prompt_text else "",
                response_blob_ref=_sha256(response_text) if response_text else "",
                latency_ms=0,
            )
            self._log.append(record)
            raise PermissionError(f"Tool '{tool_name}' is not whitelisted for agents")

        try:
            result = self._tools[tool_name](**arguments)
            latency = int((time.monotonic() - start) * 1000)

            record = ToolCallRecord(
                call_id=call_id,
                agent=agent,
                context_id=context_id,
                tool=tool_name,
                arguments=arguments,
                allowed=True,
                result=result,
                prompt_blob_ref=_sha256(prompt_text) if prompt_text else "",
                response_blob_ref=_sha256(response_text) if response_text else "",
                latency_ms=latency,
            )
            self._log.append(record)
            return result

        except Exception as exc:
            latency = int((time.monotonic() - start) * 1000)
            record = ToolCallRecord(
                call_id=call_id,
                agent=agent,
                context_id=context_id,
                tool=tool_name,
                arguments=arguments,
                allowed=True,
                denial_reason=f"execution error: {exc}",
                latency_ms=latency,
            )
            self._log.append(record)
            raise

    @property
    def audit_log(self) -> list[ToolCallRecord]:
        return list(self._log)

    @property
    def registered_tools(self) -> list[str]:
        return sorted(self._tools.keys())
