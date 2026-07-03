"""Pydantic models for the AI API Manager."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    """Information about an available AI model."""
    model_id: str
    display_name: str
    provider: str
    description: str = ""
    context_window: int = 0
    input_price_per_m: Decimal | None = None  # per 1M tokens
    output_price_per_m: Decimal | None = None
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = True
    supports_reasoning: bool = False
    # Account-settings: per-model data-leakage state (grounded in the research, see
    # LEAKAGE-CLASSIFICATION-GROUNDED.md): "mechanism_only" | "risk" | "unvalidated".
    leakage: str = "unvalidated"


# ------------------------------------------------------------------ #
# Tool / Function Calling (ATS-101)
# ------------------------------------------------------------------ #


class ToolParameter(BaseModel):
    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolFunction(BaseModel):
    name: str
    description: str = ""
    parameters: ToolParameter = Field(default_factory=ToolParameter)


class ToolDefinition(BaseModel):
    type: str = "function"
    function: ToolFunction


class ToolCall(BaseModel):
    """A tool call returned by the model."""
    id: str
    type: str = "function"
    function_name: str
    function_args: str  # JSON string


class ToolResult(BaseModel):
    """Result of a tool execution to feed back to the model."""
    tool_call_id: str
    content: str


# ------------------------------------------------------------------ #
# Messages
# ------------------------------------------------------------------ #


class ChatMessage(BaseModel):
    role: str  # system, user, assistant, tool
    content: str | None = None
    image_url: str | None = None  # ATS-104: Vision
    tool_calls: list[ToolCall] | None = None  # ATS-101: outbound tool calls
    tool_call_id: str | None = None  # ATS-101: tool result reference
    file_id: str | None = None  # ATS-105: attached file


# ------------------------------------------------------------------ #
# Request / Response
# ------------------------------------------------------------------ #


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=65536)
    top_p: float = Field(default=0.95, ge=0, le=1)
    stream: bool = False
    # ATS-101: Tool Calling
    tools: list[ToolDefinition] | None = None
    tool_choice: str | None = None  # auto, required, none
    # ATS-102: JSON Mode
    json_mode: bool = False
    # ATS-106: Reasoning
    reasoning: bool = False


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    model: str
    provider: str
    content: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    # ATS-101: Tool calls from model
    tool_calls: list[ToolCall] | None = None
    # ATS-106: Reasoning trace
    reasoning_content: str | None = None


# ------------------------------------------------------------------ #
# TTS (ATS-103)
# ------------------------------------------------------------------ #


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    voice_id: str = "male-qn-qingse"
    model: str = "speech-2.8-hd"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class TTSVoice(BaseModel):
    voice_id: str
    name: str
    gender: str
    language: str


# ------------------------------------------------------------------ #
# File Upload (ATS-105)
# ------------------------------------------------------------------ #


class FileUploadResponse(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    purpose: str = "assistants"


# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #


class ProviderConfig(BaseModel):
    """Configuration for an AI provider."""
    name: str
    provider_type: str  # minimax, openai, anthropic, etc.
    api_key: str
    base_url: str
    is_active: bool = True
