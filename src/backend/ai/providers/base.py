"""Base class for OpenAI-compatible AI providers."""
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
from openai import AsyncOpenAI

from src.backend.ai.interface import IAIProvider
from src.backend.ai.models import (
    ChatRequest,
    ChatResponse,
    FileUploadResponse,
    ModelInfo,
    ProviderConfig,
    TTSRequest,
    TTSVoice,
    TokenUsage,
    ToolCall,
)

_THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL)


class OpenAICompatibleProvider(IAIProvider):
    """Base class for all providers that implement the OpenAI-compatible API.

    Subclasses only need to define:
    - PROVIDER_TYPE: str
    - DEFAULT_BASE_URL: str
    - MODELS: list[ModelInfo]
    """

    PROVIDER_TYPE: str = ""
    DEFAULT_BASE_URL: str = ""
    MODELS: list[ModelInfo] = []

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        base = config.base_url or self.DEFAULT_BASE_URL
        self._client = AsyncOpenAI(api_key=config.api_key, base_url=base)
        self._base_url = base
        self._api_key = config.api_key

    @property
    def provider_type(self) -> str:
        return self.PROVIDER_TYPE

    def list_models(self) -> list[ModelInfo]:
        return list(self.MODELS)

    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        kwargs = self._build_kwargs(request)
        response = await self._client.chat.completions.create(**kwargs, stream=False)

        choice = response.choices[0]
        content = choice.message.content or ""

        # Extract reasoning from <think> tags
        reasoning_content = None
        if request.reasoning:
            match = _THINK_PATTERN.search(content)
            if match:
                reasoning_content = match.group(1).strip()
                content = _THINK_PATTERN.sub("", content).strip()

        # Extract tool calls
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id, type=tc.type,
                    function_name=tc.function.name,
                    function_args=tc.function.arguments,
                )
                for tc in choice.message.tool_calls
            ]

        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return ChatResponse(
            model=response.model, provider=self.PROVIDER_TYPE, content=content,
            finish_reason=choice.finish_reason, usage=usage,
            tool_calls=tool_calls, reasoning_content=reasoning_content,
        )

    async def chat_completion_stream(self, request: ChatRequest) -> AsyncIterator[str]:
        kwargs = self._build_kwargs(request)
        stream = await self._client.chat.completions.create(**kwargs, stream=True)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _build_kwargs(self, request: ChatRequest) -> dict:
        messages = []
        for m in request.messages:
            msg: dict = {"role": m.role}
            if m.role == "tool" and m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
                msg["content"] = m.content or ""
            elif m.role == "assistant" and m.tool_calls:
                msg["content"] = m.content or ""
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function_name,
                            "arguments": tc.function_args,
                        },
                    }
                    for tc in m.tool_calls
                ]
            elif m.image_url:
                msg["content"] = [
                    {"type": "text", "text": m.content or ""},
                    {"type": "image_url", "image_url": {"url": m.image_url}},
                ]
            else:
                msg["content"] = m.content or ""
            messages.append(msg)

        kwargs: dict = {
            "model": request.model, "messages": messages,
            "temperature": request.temperature, "max_tokens": request.max_tokens,
            "top_p": request.top_p,
        }
        if request.tools:
            kwargs["tools"] = [
                {"type": t.type, "function": {"name": t.function.name,
                 "description": t.function.description,
                 "parameters": t.function.parameters.model_dump()}}
                for t in request.tools
            ]
            if request.tool_choice:
                kwargs["tool_choice"] = request.tool_choice
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs
